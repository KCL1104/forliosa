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

# An honest client name; never a browser disguise (see docs/research/data-sources-licensing.md §4.4).
USER_AGENT = "forliosa/0.1 (portfolio tracker; Forliosa data archiver)"


class RateLimiter:
    """Minimum interval between requests to the same host (thread-safe).

    Hosts that match a ``per_host`` suffix share one budget: ``data.sec.gov`` and ``www.sec.gov`` both count
    against ``sec.gov`` (SEC's fair-access limit is per requester, not per host name).
    """

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

    def bucket(self, host: str) -> str:
        """The key a host's requests are counted under: its ``per_host`` suffix, else the host itself."""
        for suffix in self.per_host:
            if host == suffix or host.endswith("." + suffix):
                return suffix
        return host

    def wait(self, host: str) -> float:
        """Block until the host's interval has passed; returns seconds slept."""
        interval = self.interval_for(host)
        key = self.bucket(host)
        with self._lock:
            now = self._clock()
            last = self._last.get(key)
            slept = 0.0
            if last is not None and interval > 0:
                remaining = interval - (now - last)
                if remaining > 0:
                    self._sleep(remaining)
                    slept = remaining
            self._last[key] = self._clock()
            return slept


# Polite intervals per host (docs/research/data-sources-licensing.md §4.4, open-data-inventory.md §12.2):
# TWSE ≥ 3 s, TPEx, TDCC, TAIFEX, the central bank and SITCA (the fund NAV file) ≥ 2 s. SEC EDGAR allows 10
# requests / s per requester across all of sec.gov; one process stays at ≤ 4 / s (0.25 s), so the API server and the
# worker together stay under 10 / s.
SEC_INTERVAL_SECONDS = 0.25
DEFAULT_LIMITER = RateLimiter(
    default_interval=0.0,
    per_host={"twse.com.tw": 3.0, "tpex.org.tw": 2.0, "tdcc.com.tw": 2.0, "taifex.com.tw": 2.0,
              "cbc.gov.tw": 2.0, "sitca.org.tw": 2.0, "finmindtrade.com": 0.25, "sec.gov": SEC_INTERVAL_SECONDS},
)

# Source allowlist: the only URLs the server may fetch. Official open data published under the Open
# Government Data License (TWSE / TPEx / TAIFEX OpenAPI, TDCC open data, the central bank's open-data API for
# 銀行間新臺幣對美元收盤匯率 — data.gov.tw 7232), shioaji-data's official files, and
# FinMind (only constructed under an explicit DATA_POLICY=personal opt-in). Website pages of TWSE / TPEx /
# TAIFEX / MIS / MOPS are deliberately absent: their terms forbid automated downloads without written consent.
# TAIFEX: only the /v1/ data endpoints (they answer 200 directly; /v1/swagger.json is a 302 and never needed).
# SEC EDGAR (US government public data; "free to access and reuse"): only the three JSON datasets Forliosa uses —
# the ticker -> CIK map, XBRL company facts and the submissions (filing list). Filing documents themselves are
# linked, never downloaded.
ALLOWED_URL_PREFIXES = (
    "https://openapi.twse.com.tw/v1/",
    "https://www.tpex.org.tw/openapi/",
    "https://opendata.tdcc.com.tw/",
    "https://openapi.taifex.com.tw/v1/",
    "https://cpx.cbc.gov.tw/api/OpenData/",
    # 金融監督管理委員會證券期貨局〈證券投資信託基金每日淨值〉(data.gov.tw 11109, OGDL): the dataset's one resource is
    # this CSV hosted by SITCA (投信投顧公會). Only the file itself — nothing else on www.sitca.org.tw is fetched.
    "https://www.sitca.org.tw/MemberK0000/F/03/nav.csv",
    "https://raw.githubusercontent.com/Sinotrade/shioaji-data/",
    "https://api.finmindtrade.com/",
    "https://www.sec.gov/files/company_tickers.json",
    "https://data.sec.gov/api/xbrl/companyfacts/",
    "https://data.sec.gov/submissions/",
    # News metadata (forliosa.news): the GDELT DOC 2.0 API (free, commercial use allowed with a citation) and, only
    # under DATA_POLICY=personal, Yahoo股市's RSS feeds (non-commercial terms). A self-hosted SearXNG is allowed per
    # fetcher (``extra_allowed``) when NEWS_SEARXNG_URL is set. News sites themselves are never fetched.
    "https://api.gdeltproject.org/api/v2/doc/doc",
    "https://tw.stock.yahoo.com/rss",
    # 「關於」 description (forliosa.services.company): Wikidata's API (CC0; find the article by ticker) and the
    # zh.wikipedia REST summary (CC BY-SA 4.0 excerpt, shown unchanged with attribution). Nothing else on Wikimedia.
    "https://www.wikidata.org/w/api.php",
    "https://zh.wikipedia.org/api/rest_v1/page/summary/",
)


def url_allowed(url: str) -> bool:
    return url.startswith(ALLOWED_URL_PREFIXES)


class HttpStatusError(ProviderUnavailable):
    """The upstream answered with a refusal status (403, 404, 429, a redirect …); ``status`` is the HTTP code."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


class HttpFetcher:
    def __init__(self, timeout: float = 20.0, limiter: RateLimiter | None = None, retries: int = 2,
                 client: httpx.Client | None = None, user_agent: str = USER_AGENT, backoff: float = 1.0,
                 extra_allowed: tuple[str, ...] = ()):
        self.limiter = limiter or DEFAULT_LIMITER
        self.extra_allowed = tuple(extra_allowed)
        self.retries = retries
        self.backoff = backoff
        self.client = client or httpx.Client(
            timeout=timeout, headers={"User-Agent": user_agent, "Accept": "application/json"},
            follow_redirects=False,  # a redirect (e.g. a WAF 307) is a refusal: stop, never chase it
        )

    def get_bytes(self, url: str, params: dict[str, Any] | None = None,
                  headers: dict[str, str] | None = None) -> bytes:
        host = urlparse(url).hostname or ""
        if not (url_allowed(url) or (self.extra_allowed and url.startswith(self.extra_allowed))):
            raise ProviderUnavailable(f"{url} 不在授權來源白名單（marketdata/http.py ALLOWED_URL_PREFIXES）")
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
                if resp.status_code in (402, 403, 404, 405, 407, 429, 451) or 300 <= resp.status_code < 400:
                    raise HttpStatusError(f"{host} 回應 HTTP {resp.status_code}", resp.status_code)
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
