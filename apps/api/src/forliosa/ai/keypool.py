"""Anthropic API keys as workspace *slots*: sticky routing per thread, headroom-based selection, failover.

Slots
-----
Keys come from ``CLAUDE_API_KEY_<n>`` (matched case-insensitively, so ``Claude_API_KEY_1`` works); the slot
number is ``n``. With no numbered key, ``ANTHROPIC_API_KEY`` is slot 0 (so is the ``AI_DEV_DUMMY_KEY``
placeholder). A ``.env`` file in the working directory is read too (real environment variables win). Each key
is expected to live in its **own workspace** with its own rate limits and spend limit, so a slot is also the
unit of prompt caching (caches are per workspace) and of replay (thinking blocks stay with the account that
produced them; web-search ``encrypted_content`` must be passed back unchanged to the same account). Optional
per-slot budgets: ``AI_KEY_<n>_MONTHLY_BUDGET_USD`` (estimated cost per UTC month, from ``ai_usage``).

Only slot numbers are ever logged or returned (``#2``) — never a key. Each slot has one reused ``Anthropic``
client with the SDK's own retries off (``max_retries=0``): retrying is this module's job.

State of a slot (kept in this process; month costs come from the database and are passed in by callers):

* ``disabled``    401 / 403: until restart.
* ``exhausted``   spend limit reached — 429 with ``error_code`` ``enforced_spend_limit_reached`` (until 00:00 UTC
  on the 1st of next month), 400 "You have reached your specified (workspace) API usage limits" (until the time
  the message names, else next month), 402 ``billing_error`` (re-checked after an hour).
* ``over_budget`` this UTC month's estimated cost ≥ ``AI_KEY_<n>_MONTHLY_BUDGET_USD``.
* ``cooling``     429 / 529 / 5xx / ``overloaded_error``: ``retry-after`` if sent (a *hard* wait), else
  ``AI_KEY_COOLDOWN_SECONDS`` (a *soft* guess — a soft-cooling slot may still be probed when nothing else is
  usable); also while the last ``anthropic-ratelimit-*-remaining`` header was 0, until its ``-reset`` time.
* ``ok``

Headroom (0–1) = the lowest ``remaining / limit`` of the last response's ``anthropic-ratelimit-{requests,
tokens,input-tokens,output-tokens}-*`` headers (until their reset), and ``1 − month cost / budget``.
``ranked()`` orders usable slots for new threads and background jobs: headroom (in 0.1 steps), then lowest
month cost, then fewest assignments in this process, then slot number; cooling slots last, soonest first.
``route()`` keeps a thread on its pinned slot while it is ``ok`` or recovers within the short sticky wait, and
otherwise picks the best other slot (the caller then continues the thread from a plain-text recap).
"""

from __future__ import annotations

import contextlib
import logging
import math
import os
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal, TypeVar

import anthropic

from forliosa.config import get_settings
from forliosa.timeutil import now_utc

log = logging.getLogger(__name__)

KEY_ENV = re.compile(r"^CLAUDE_API_KEY_(\d+)$", re.IGNORECASE)
BUDGET_ENV = re.compile(r"^AI_KEY_(\d+)_MONTHLY_BUDGET_USD$", re.IGNORECASE)
FALLBACK_ENV = "ANTHROPIC_API_KEY"
FALLBACK_SLOT = 0
DUMMY_KEY = "sk-ant-placeholder-injected-by-proxy"
EXPECTED_SLOTS = (1, 2, 3)  # listed by the admin status even when not configured
# Retryable on another key (``type`` covers errors that arrive inside a 200 stream, e.g. overloaded_error).
FAILOVER_TYPES = frozenset({"rate_limit_error", "overloaded_error", "api_error"})
RATE_LIMIT_KINDS = ("requests", "tokens", "input-tokens", "output-tokens")
RATE_LIMIT_DEFAULT_RESET = 60.0  # seconds, when a -reset header is missing or unreadable
SPEND_LIMIT_PREFIX = "You have reached your specified"  # 400 when a spend limit set in the Console is reached
BILLING_RECHECK_SECONDS = 3600.0
_RESUME_AT = re.compile(r"(\d{4}-\d{2}-\d{2})(?:\s+at\s+|T)(\d{2}:\d{2})(?::\d{2})?\s*UTC")

State = Literal["ok", "cooling", "disabled", "exhausted", "over_budget"]
T = TypeVar("T")


# -- configuration -------------------------------------------------------------------------------------------
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


def discover_slots(environ: Mapping[str, str] | None = None,
                   dotenv_path: str | Path | None = ".env") -> list[tuple[int, str]]:
    """``[(n, key)]`` for CLAUDE_API_KEY_<n> (any letter case) ordered by ``n``, else ``[(0, ANTHROPIC_API_KEY)]``.
    A key configured twice keeps its lowest slot number."""
    env = _env_with_dotenv(environ, dotenv_path)
    numbered = sorted((int(m.group(1)), value.strip()) for name, value in env.items()
                      if (m := KEY_ENV.match(name)) and value and value.strip())
    if not numbered:
        fallback = (env.get(FALLBACK_ENV) or "").strip()
        numbered = [(FALLBACK_SLOT, fallback)] if fallback else []
    out: list[tuple[int, str]] = []
    for n, key in numbered:
        if all(n != m and key != k for m, k in out):
            out.append((n, key))
    return out


def discover_keys(environ: Mapping[str, str] | None = None, dotenv_path: str | Path | None = ".env") -> list[str]:
    """Keys in slot order (see ``discover_slots``)."""
    return [k for _, k in discover_slots(environ, dotenv_path)]


def discover_budgets(environ: Mapping[str, str] | None = None,
                     dotenv_path: str | Path | None = ".env") -> dict[int, Decimal]:
    """``AI_KEY_<n>_MONTHLY_BUDGET_USD`` (any letter case) → ``{n: budget}``; empty, 0 or invalid = no budget."""
    out: dict[int, Decimal] = {}
    for name, value in _env_with_dotenv(environ, dotenv_path).items():
        m = BUDGET_ENV.match(name)
        if not m or not (value or "").strip():
            continue
        try:
            budget = Decimal(value.strip())
        except InvalidOperation:
            log.warning("ignoring %s: not a number", name.upper())
            continue
        if budget.is_finite() and budget > 0:
            out[int(m.group(1))] = budget
    return out


# -- errors --------------------------------------------------------------------------------------------------
class NoKeyAvailable(Exception):
    """No usable slot: none configured, or every slot is disabled, exhausted or over its budget."""


class KeysBusy(Exception):
    """Every usable slot is cooling down for longer than the caller wants to wait."""

    def __init__(self, retry_in: float):
        super().__init__(f"all API keys are cooling down (retry in {retry_in:.0f}s)")
        self.retry_in = retry_in


@dataclass(frozen=True)
class Failure:
    """How a failed call affects its slot. ``label`` (status + error type/code) is safe to log and show."""

    kind: Literal["disable", "exhaust", "cool", "connection"]
    seconds: float | None  # cooldown / exhaustion length; None = default cooldown (soft) or until restart
    label: str


def _next_month_utc(now: datetime) -> datetime:
    n = now.astimezone(UTC)
    return datetime(n.year + (n.month == 12), n.month % 12 + 1, 1, tzinfo=UTC)


def _resume_time(message: str, now: datetime) -> datetime:
    m = _RESUME_AT.search(message or "")
    if m:
        try:
            at = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:00+00:00")
            if at > now:
                return at
        except ValueError:
            pass
    return _next_month_utc(now)


def _retry_after(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    try:
        value = response.headers.get("retry-after")
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def classify_failure(exc: BaseException, now: datetime | None = None) -> Failure | None:
    """``None`` for errors that another key would not fix (400 bad request, 404 model …)."""
    if isinstance(exc, anthropic.APIConnectionError):  # includes timeouts
        return Failure("connection", None, type(exc).__name__)
    if not isinstance(exc, anthropic.APIStatusError):
        return None
    now = now or now_utc()
    status, etype = exc.status_code, (exc.type or "")
    code = getattr(exc, "error_code", None) or ""
    message = getattr(exc, "api_message", None) or ""
    label = f"{status} {etype or type(exc).__name__}" + (f" {code}" if code else "")
    if status in (401, 403):
        return Failure("disable", None, label)
    if "spend_limit" in code or (status == 400 and message.startswith(SPEND_LIMIT_PREFIX)):
        return Failure("exhaust", max(60.0, (_resume_time(message, now) - now).total_seconds()), label)
    if status == 402:
        return Failure("exhaust", BILLING_RECHECK_SECONDS, label)
    if status in (429, 529) or status >= 500 or etype in FAILOVER_TYPES:
        return Failure("cool", _retry_after(exc), label)
    return None


def is_failover_error(exc: BaseException) -> bool:
    """Errors worth retrying on another key."""
    return classify_failure(exc) is not None


# -- slots ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class RateLimit:
    remaining: int
    limit: int
    reset_at: float  # pool clock


@dataclass
class KeySlot:
    index: int  # the n of CLAUDE_API_KEY_<n> (0 = ANTHROPIC_API_KEY); safe to log
    client: Any
    budget_usd: Decimal | None = None
    cooldown_until: float = 0.0
    cooldown_hard: bool = False  # retry-after / a rate limit at 0: do not probe before it ends
    exhausted_until: float = 0.0
    disabled: bool = False
    failures: int = 0
    last_error: str | None = None
    assigned: int = 0  # requests / new threads routed here by this process
    workspace_id: str | None = None  # from the anthropic-workspace-id response header
    limits: dict[str, RateLimit] = field(default_factory=dict)


@dataclass(frozen=True)
class Route:
    slot: KeySlot
    wait: float  # seconds to sleep before using it (a short sticky wait), 0 = now


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@dataclass
class KeyPool:
    slots: list[KeySlot]
    cooldown_seconds: float = 60.0
    budgets: dict[int, Decimal] = field(default_factory=dict)
    clock: Callable[[], float] = time.monotonic
    wall: Callable[[], datetime] = now_utc
    sleep: Callable[[float], None] = time.sleep
    _lock: threading.RLock = field(default_factory=threading.RLock)

    @classmethod
    def from_keys(cls, keys: Iterable[str | tuple[int, str]], client_factory: Callable[[str], Any] | None = None,
                  cooldown_seconds: float = 60.0, budgets: Mapping[int, Decimal] | None = None,
                  **kw: Any) -> KeyPool:
        """``keys`` are ``(slot, key)`` pairs, or plain keys numbered 1, 2, 3 …"""
        settings = get_settings()

        def default_factory(key: str) -> Any:
            return anthropic.Anthropic(api_key=key, max_retries=0, timeout=settings.ai_request_timeout_seconds)

        factory = client_factory or default_factory
        pairs = [k if isinstance(k, tuple) else (i + 1, k) for i, k in enumerate(keys)]
        budgets = dict(budgets or {})
        slots = [KeySlot(n, factory(k), budget_usd=budgets.get(n)) for n, k in pairs]
        return cls(slots, cooldown_seconds=cooldown_seconds, budgets=budgets, **kw)

    @property
    def size(self) -> int:
        return len(self.slots)

    @property
    def available(self) -> bool:
        """At least one slot that is not disabled (budgets and spend limits are checked by ``ranked``)."""
        return any(not s.disabled for s in self.slots)

    def get(self, index: int | None) -> KeySlot | None:
        return next((s for s in self.slots if s.index == index), None) if index is not None else None

    # -- state -----------------------------------------------------------------------------------------------
    def wait_seconds(self, slot: KeySlot) -> float:
        """Seconds until the slot may be used again: its cooldown, or a rate limit at 0 until its reset."""
        now = self.clock()
        until = slot.cooldown_until
        for rl in slot.limits.values():
            if rl.remaining <= 0 and rl.reset_at > now:
                until = max(until, rl.reset_at)
        return max(0.0, until - now)

    def _hard_wait(self, slot: KeySlot) -> bool:
        now = self.clock()
        return (slot.cooldown_hard and slot.cooldown_until > now) or any(
            rl.remaining <= 0 and rl.reset_at > now for rl in slot.limits.values())

    def state(self, slot: KeySlot, cost: Decimal = Decimal(0)) -> State:
        if slot.disabled:
            return "disabled"
        if slot.exhausted_until > self.clock():
            return "exhausted"
        if slot.budget_usd is not None and cost >= slot.budget_usd:
            return "over_budget"
        return "cooling" if self.wait_seconds(slot) > 0 else "ok"

    def headroom(self, slot: KeySlot, cost: Decimal = Decimal(0)) -> float:
        now = self.clock()
        h = 1.0
        for rl in slot.limits.values():
            if rl.limit > 0 and rl.reset_at > now:
                h = min(h, max(0.0, rl.remaining / rl.limit))
        if slot.budget_usd:
            h = min(h, max(0.0, float(1 - cost / slot.budget_usd)))
        return h

    def ranked(self, costs: Mapping[int, Decimal] | None = None, exclude: Iterable[int] = ()) -> list[KeySlot]:
        """Usable slots, best first (see the module docstring). Disabled, exhausted and over-budget slots are
        left out, so an empty list means there is no capacity at all."""
        costs = costs or {}
        skip = set(exclude)
        with self._lock:
            ok: list[KeySlot] = []
            cooling: list[KeySlot] = []
            for s in self.slots:
                if s.index in skip:
                    continue
                st = self.state(s, costs.get(s.index, Decimal(0)))
                if st == "ok":
                    ok.append(s)
                elif st == "cooling":
                    cooling.append(s)

            def score(s: KeySlot) -> tuple:
                cost = costs.get(s.index, Decimal(0))
                return -math.floor(self.headroom(s, cost) * 10 + 1e-9), cost, s.assigned, s.index

            ok.sort(key=score)
            cooling.sort(key=lambda s: (self.wait_seconds(s), s.index))
            return ok + cooling

    def route(self, pinned: int | None, costs: Mapping[int, Decimal] | None = None, max_wait: float = 0.0,
              exclude: Iterable[int] = ()) -> Route:
        """The slot for a chat request. Sticky: the ``pinned`` slot while it is ``ok`` or recovers within
        ``max_wait`` seconds. Otherwise the best other slot by headroom; when every slot is cooling, the one that
        recovers first (waited for up to ``max_wait``, or probed right away when its cooldown is only a guess).
        Raises ``NoKeyAvailable`` (no capacity) or ``KeysBusy``."""
        costs = costs or {}
        skip = set(exclude)
        with self._lock:
            slot = self.get(pinned)
            if slot is not None and slot.index not in skip:
                st = self.state(slot, costs.get(slot.index, Decimal(0)))
                wait = self.wait_seconds(slot)
                if st == "ok" or (st == "cooling" and wait <= max_wait):
                    slot.assigned += 1
                    return Route(slot, wait)
            order = self.ranked(costs, skip)
            if not order:
                raise NoKeyAvailable("no usable API key")
            best = order[0]
            wait = self.wait_seconds(best)
            if wait > max_wait:
                if self._hard_wait(best):
                    raise KeysBusy(wait)
                wait = 0.0  # a guessed cooldown: probe it
            best.assigned += 1
            return Route(best, wait)

    # -- observations ----------------------------------------------------------------------------------------
    def observe(self, index: int | None, headers: Mapping[str, str] | None) -> None:
        """Record a response's rate-limit headers (``anthropic-ratelimit-*``) and workspace id for a slot."""
        slot = self.get(index)
        if slot is None or not headers:
            return
        now, wall = self.clock(), self.wall()
        with self._lock:
            ws = headers.get("anthropic-workspace-id")
            if ws:
                slot.workspace_id = ws
            for kind in RATE_LIMIT_KINDS:
                remaining = _int(headers.get(f"anthropic-ratelimit-{kind}-remaining"))
                limit = _int(headers.get(f"anthropic-ratelimit-{kind}-limit"))
                if remaining is None or limit is None:
                    continue
                reset = RATE_LIMIT_DEFAULT_RESET
                raw = headers.get(f"anthropic-ratelimit-{kind}-reset")
                if raw:
                    with contextlib.suppress(TypeError, ValueError):
                        reset = max(0.0, (datetime.fromisoformat(raw) - wall).total_seconds())
                slot.limits[kind] = RateLimit(remaining, limit, now + reset)

    def mark_failure(self, slot: KeySlot, exc: BaseException) -> Failure | None:
        failure = classify_failure(exc, self.wall())
        response = getattr(exc, "response", None)
        if response is not None:
            self.observe(slot.index, getattr(response, "headers", None))
        with self._lock:
            slot.failures += 1
            slot.last_error = failure.label if failure else type(exc).__name__
            if failure is None:
                return None
            if failure.kind == "disable":
                slot.disabled = True
                log.error("AI key #%d rejected (%s); disabled until restart", slot.index, failure.label)
            elif failure.kind == "exhaust":
                seconds = failure.seconds or BILLING_RECHECK_SECONDS
                slot.exhausted_until = self.clock() + seconds
                log.error("AI key #%d: spend limit reached (%s); skipped for %.1f h", slot.index, failure.label,
                          seconds / 3600)
            elif failure.kind == "connection":
                log.warning("AI key #%d: connection error (%s)", slot.index, failure.label)
            else:
                wait = failure.seconds if failure.seconds is not None else self.cooldown_seconds
                slot.cooldown_until = self.clock() + wait
                slot.cooldown_hard = failure.seconds is not None
                log.warning("AI key #%d: %s; cooling down %.0fs", slot.index, failure.label, wait)
        return failure

    def mark_success(self, slot: KeySlot) -> None:
        with self._lock:
            slot.failures = 0
            slot.cooldown_until = 0.0
            slot.cooldown_hard = False
            slot.last_error = None

    # -- one-shot calls (background jobs) --------------------------------------------------------------------
    def call(self, fn: Callable[[Any], T], costs: Mapping[int, Decimal] | None = None,
             only: int | None = None) -> tuple[T, int]:
        """Run ``fn(client)`` on the slot with the most headroom, failing over to the next; returns
        ``(result, slot)``. ``only`` pins the call to one slot (e.g. a ``pause_turn`` continuation, whose
        server-tool state belongs to that workspace). One retry after a pause when only one slot is usable.
        Raises the last error, or ``NoKeyAvailable``."""
        if only is not None:
            pinned = self.get(only)
            order = [pinned] if pinned is not None and not pinned.disabled else []
        else:
            order = self.ranked(costs)
        if not order:
            raise NoKeyAvailable("no usable API key")
        if len(order) == 1:
            order = order * 2
        last: BaseException | None = None
        tried: list[int] = []
        for slot in order:
            if slot.disabled or slot.exhausted_until > self.clock():
                continue
            if slot.index in tried:
                self.sleep(min(2.0, 0.5 * len(tried)))
            tried.append(slot.index)
            with self._lock:
                slot.assigned += 1
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

    # -- status (no secrets) ---------------------------------------------------------------------------------
    def status(self, costs: Mapping[int, Decimal] | None = None, calls: Mapping[int, int] | None = None,
               threads: Mapping[int, int] | None = None) -> list[dict[str, Any]]:
        costs, calls, threads = costs or {}, calls or {}, threads or {}
        now = self.clock()
        with self._lock:
            numbers = sorted({*EXPECTED_SLOTS, *(s.index for s in self.slots), *self.budgets})
            out = []
            for n in numbers:
                slot = self.get(n)
                cost = Decimal(costs.get(n, Decimal(0)))
                budget = slot.budget_usd if slot is not None else self.budgets.get(n)
                row: dict[str, Any] = {
                    "slot": n, "configured": slot is not None,
                    "state": self.state(slot, cost) if slot is not None else "not_configured",
                    "retry_in_seconds": None, "workspace_id": None,
                    "month_cost_usd": float(cost.quantize(Decimal("0.0001"))), "month_calls": int(calls.get(n, 0)),
                    "monthly_budget_usd": float(budget) if budget is not None else None,
                    "budget_remaining_usd": float(max(Decimal(0), budget - cost).quantize(Decimal("0.0001")))
                    if budget is not None else None,
                    "headroom": None, "rate_limits": {}, "threads": int(threads.get(n, 0)), "failures": 0,
                    "last_error": None,
                }
                if slot is not None:
                    wait = max(self.wait_seconds(slot), slot.exhausted_until - now, 0.0)
                    row.update({
                        "retry_in_seconds": math.ceil(wait) if wait > 0 else None,
                        "workspace_id": slot.workspace_id,
                        "headroom": round(self.headroom(slot, cost), 3),
                        "rate_limits": {k: {"remaining": rl.remaining, "limit": rl.limit}
                                        for k, rl in slot.limits.items() if rl.reset_at > now},
                        "failures": slot.failures, "last_error": slot.last_error,
                    })
                out.append(row)
            return out


_pool: KeyPool | None = None
_pool_lock = threading.Lock()


def build_pool() -> KeyPool:
    settings = get_settings()
    pairs = discover_slots()
    if not pairs and settings.ai_dev_dummy_key:
        pairs = [(FALLBACK_SLOT, DUMMY_KEY)]
    pool = KeyPool.from_keys(pairs, cooldown_seconds=settings.ai_key_cooldown_seconds, budgets=discover_budgets())
    log.info("AI key pool: %s%s", ", ".join(f"#{s.index}" for s in pool.slots) or "no keys",
             " (placeholder)" if pairs == [(FALLBACK_SLOT, DUMMY_KEY)] else "")
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
