"""A round-robin pool of Anthropic API keys with failover.

Keys come from environment variables named ``CLAUDE_API_KEY_<n>`` (matched case-insensitively, so
``Claude_API_KEY_1`` works; ordered by ``n``), falling back to ``ANTHROPIC_API_KEY``. A ``.env`` file in the
working directory is read too (real environment variables win). With ``AI_DEV_DUMMY_KEY=1`` and no key, a
placeholder is sent so a proxy that injects the real key can be used.

Every request starts at the next key (round robin). On 429 / 529 / ``overloaded_error`` / 5xx the key is
cooled down and the next key is tried; on 401 the key is disabled until restart. Only the key's 1-based
index is ever logged — never the key itself. Each key has one reused ``Anthropic`` client whose own retries
are off (``max_retries=0``): retrying is this pool's job, on a different key.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import anthropic

from forliosa.config import get_settings

log = logging.getLogger(__name__)

KEY_ENV = re.compile(r"^CLAUDE_API_KEY_(\d+)$", re.IGNORECASE)
FALLBACK_ENV = "ANTHROPIC_API_KEY"
DUMMY_KEY = "sk-ant-placeholder-injected-by-proxy"
# Retryable on another key (``type`` covers errors that arrive inside a 200 stream, e.g. overloaded_error).
FAILOVER_TYPES = frozenset({"rate_limit_error", "overloaded_error", "api_error"})

T = TypeVar("T")


def _env_with_dotenv(environ: Mapping[str, str] | None, dotenv_path: str | Path | None) -> dict[str, str]:
    merged: dict[str, str] = {}
    if dotenv_path is not None and Path(dotenv_path).is_file():
        try:
            from dotenv import dotenv_values

            merged.update({k: v for k, v in dotenv_values(dotenv_path).items() if v is not None})
        except Exception:  # pragma: no cover - a broken .env must not stop the app
            log.warning("could not read %s for AI keys", dotenv_path)
    merged.update(os.environ if environ is None else environ)
    return merged


def discover_keys(environ: Mapping[str, str] | None = None, dotenv_path: str | Path | None = ".env") -> list[str]:
    """Keys in order: CLAUDE_API_KEY_1, _2, … (any letter case), else ANTHROPIC_API_KEY. Duplicates dropped."""
    env = _env_with_dotenv(environ, dotenv_path)
    numbered: list[tuple[int, str]] = []
    for name, value in env.items():
        m = KEY_ENV.match(name)
        if m and value and value.strip():
            numbered.append((int(m.group(1)), value.strip()))
    keys = [v for _, v in sorted(numbered)]
    if not keys:
        fallback = (env.get(FALLBACK_ENV) or "").strip()
        if fallback:
            keys = [fallback]
    return list(dict.fromkeys(keys))


class NoKeyAvailable(Exception):
    """No usable key: none configured, or every key was rejected (401)."""


@dataclass
class KeySlot:
    index: int  # 1-based, safe to log
    client: Any
    cooldown_until: float = 0.0
    disabled: bool = False
    failures: int = 0


def is_failover_error(exc: BaseException) -> bool:
    """Errors worth retrying on another key."""
    if isinstance(exc, anthropic.APIConnectionError):
        return True
    if isinstance(exc, anthropic.AuthenticationError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code in (429, 529) or exc.status_code >= 500:
            return True
        return (exc.type or "") in FAILOVER_TYPES
    return False


def _retry_after(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    try:
        value = response.headers.get("retry-after")
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@dataclass
class KeyPool:
    slots: list[KeySlot]
    cooldown_seconds: float = 60.0
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _next: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def from_keys(cls, keys: list[str], client_factory: Callable[[str], Any] | None = None,
                  cooldown_seconds: float = 60.0, **kw: Any) -> KeyPool:
        settings = get_settings()

        def default_factory(key: str) -> Any:
            return anthropic.Anthropic(api_key=key, max_retries=0, timeout=settings.ai_request_timeout_seconds)

        factory = client_factory or default_factory
        return cls([KeySlot(i + 1, factory(k)) for i, k in enumerate(keys)], cooldown_seconds=cooldown_seconds, **kw)

    @property
    def size(self) -> int:
        return len(self.slots)

    @property
    def available(self) -> bool:
        return any(not s.disabled for s in self.slots)

    def attempt_order(self, prefer: int | None = None) -> list[KeySlot]:
        """Usable slots for one request: round-robin start, healthy keys first, then cooling ones (soonest
        to recover first). At least two attempts when there is only one key (one retry after a pause).

        ``prefer`` (a key index) keeps follow-up calls of the same chat turn on the key that served it, without
        advancing the rotation: prompt caches are per workspace and thinking blocks per account."""
        with self._lock:
            live = [s for s in self.slots if not s.disabled]
            if not live:
                raise NoKeyAvailable("no usable API key")
            now = self.clock()
            preferred = next((s for s in live if s.index == prefer and s.cooldown_until <= now), None)
            if preferred is not None:
                start = self.slots.index(preferred)
            else:
                start = self._next % len(self.slots)
                self._next += 1
            rotated = self.slots[start:] + self.slots[:start]
            healthy = [s for s in rotated if not s.disabled and s.cooldown_until <= now]
            cooling = sorted((s for s in rotated if not s.disabled and s.cooldown_until > now),
                             key=lambda s: s.cooldown_until)
            order = healthy + cooling
            if len(order) == 1:
                order = order * 2
            return order

    def mark_failure(self, slot: KeySlot, exc: BaseException) -> None:
        with self._lock:
            slot.failures += 1
            if isinstance(exc, anthropic.AuthenticationError):
                slot.disabled = True
                log.error("AI key #%d rejected (401); disabled until restart", slot.index)
                return
            if isinstance(exc, anthropic.APIConnectionError):
                log.warning("AI key #%d: connection error (%s)", slot.index, type(exc).__name__)
                return
            wait = _retry_after(exc) or self.cooldown_seconds
            slot.cooldown_until = self.clock() + wait
            status = getattr(exc, "status_code", "?")
            log.warning("AI key #%d: %s %s; cooling down %.0fs", slot.index, status,
                        getattr(exc, "type", None) or type(exc).__name__, wait)

    def mark_success(self, slot: KeySlot) -> None:
        with self._lock:
            slot.failures = 0
            slot.cooldown_until = 0.0

    def call(self, fn: Callable[[Any], T]) -> tuple[T, int]:
        """Run ``fn(client)`` with failover; returns ``(result, key_index)``. Raises the last error."""
        last: BaseException | None = None
        tried: set[int] = set()
        for slot in self.attempt_order():
            if slot.disabled:
                continue
            if slot.index in tried:
                self.sleep(min(2.0, 0.5 * len(tried)))
            tried.add(slot.index)
            try:
                result = fn(slot.client)
            except Exception as exc:
                if not is_failover_error(exc):
                    raise
                self.mark_failure(slot, exc)
                last = exc
                continue
            self.mark_success(slot)
            return result, slot.index
        if last is not None:
            raise last
        raise NoKeyAvailable("no usable API key")


_pool: KeyPool | None = None
_pool_lock = threading.Lock()


def build_pool() -> KeyPool:
    settings = get_settings()
    keys = discover_keys()
    if not keys and settings.ai_dev_dummy_key:
        keys = [DUMMY_KEY]
    pool = KeyPool.from_keys(keys, cooldown_seconds=settings.ai_key_cooldown_seconds)
    log.info("AI key pool: %d key(s)%s", pool.size, " (placeholder)" if keys == [DUMMY_KEY] else "")
    return pool


def get_key_pool() -> KeyPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = build_pool()
        return _pool


def set_key_pool(pool: KeyPool | None) -> None:
    """Tests inject a pool of fake clients; ``None`` rebuilds from the environment on next use."""
    global _pool
    with _pool_lock:
        _pool = pool
