"""Polite HTTP fetching: per-host rate limiting, retries with backoff, on-disk caching."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from forliosa.marketdata.base import ProviderUnavailable

log = logging.getLogger(__name__)

USER_AGENT = "forliosa/0.1 (portfolio tracker)"
# MIS rejects non-browser clients; a generic browser UA (no personal details) is used there.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


class RateLimiter:
    """Minimum interval between requests to the same host (thread-safe)."""

    def __init__(self, default_interval: float = 0.0, per_host: dict[str, float] | None = None):
        self.default_interval = default_interval
        self.per_host = per_host or {}
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self._sleep = time.sleep
        self._clock = time.monotonic

    def interval_for(self, host: str) -> float:
        for suffix, interval in self.per_host.items():
            if host == suffix or host.endswith("." + suffix):
                return interval
        return self.default_interval

    def wait(self, host: str) -> float:
        """Block until the host's interval has passed; returns seconds slept."""
        interval = self.interval_for(host)
        with self._lock:
            now = self._clock()
            last = self._last.get(host)
            slept = 0.0
            if last is not None and interval > 0:
                remaining = interval - (now - last)
                if remaining > 0:
                    self._sleep(remaining)
                    slept = remaining
            self._last[host] = self._clock()
            return slept


# TWSE (and MIS, which shares the firewall) ≥ 0.5 s between requests; TPEx likewise.
DEFAULT_LIMITER = RateLimiter(
    default_interval=0.0,
    per_host={"twse.com.tw": 0.5, "tpex.org.tw": 0.5, "finmindtrade.com": 0.25},
)


class HttpFetcher:
    def __init__(self, timeout: float = 20.0, limiter: RateLimiter | None = None, retries: int = 2,
                 client: httpx.Client | None = None, user_agent: str = USER_AGENT, backoff: float = 1.0):
        self.limiter = limiter or DEFAULT_LIMITER
        self.retries = retries
        self.backoff = backoff
        self.client = client or httpx.Client(
            timeout=timeout, headers={"User-Agent": user_agent, "Accept": "application/json"},
            follow_redirects=True,
        )

    def get_bytes(self, url: str, params: dict[str, Any] | None = None,
                  headers: dict[str, str] | None = None) -> bytes:
        host = urlparse(url).hostname or ""
        delay = self.backoff
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            self.limiter.wait(host)
            try:
                resp = self.client.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                last_exc = exc
            else:
                if resp.status_code == 200:
                    return resp.content
                if resp.status_code in (402, 403, 404, 405, 407, 429, 451):
                    raise ProviderUnavailable(f"{host} 回應 HTTP {resp.status_code}")
                last_exc = ProviderUnavailable(f"{host} 回應 HTTP {resp.status_code}")
            if attempt < self.retries:
                time.sleep(delay)
                delay *= 2
        raise ProviderUnavailable(f"無法連線 {host}：{last_exc}")

    def get_json(self, url: str, params: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None) -> Any:
        raw = self.get_bytes(url, params=params, headers=headers)
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise ProviderUnavailable(f"{urlparse(url).hostname} 回傳的不是 JSON") from exc


class DiskCache:
    """Content-addressed cache: files are stored under their sha256 so a manifest hash is the key."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def path_for(self, namespace: str, key: str, suffix: str = ".json") -> Path:
        return self.root / namespace / f"{key}{suffix}"

    def read(self, namespace: str, key: str, suffix: str = ".json") -> bytes | None:
        p = self.path_for(namespace, key, suffix)
        try:
            return p.read_bytes()
        except OSError:
            return None

    def write(self, namespace: str, key: str, data: bytes, suffix: str = ".json") -> None:
        p = self.path_for(namespace, key, suffix)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(p)
        except OSError as exc:  # cache is best-effort
            log.warning("cache write failed for %s: %s", p, exc)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
