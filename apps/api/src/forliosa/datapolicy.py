"""Data-source policy (``DATA_POLICY``) and the human-readable source labels in responses.

* ``personal`` (default): every configured source may be used. Non-commercial ones (FinMind, the
  unofficial TWSE MIS endpoint, the TWSE website outside the OpenAPI, Yahoo) are listed in every
  response's ``sources`` with the suffix 「非商用」.
* ``commercial``: only government open data — TWSE / TPEx OpenAPI, TDCC open data, the official
  files of shioaji-data — and our own archive built from them. Non-commercial providers are not
  constructed at all, archive rows that came from them are ignored, and endpoints that only have a
  non-commercial source (news, TWSE per-stock institutional flows, intraday points) return empty data.

Source *keys* are the short names stored in ``QuoteData.source`` and the archive tables' ``source``
column (``twse-openapi``, ``finmind`` …); ``label()`` turns a key into the text shown to users.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

Policy = Literal["personal", "commercial"]

NON_COMMERCIAL_SUFFIX = "（非商用）"

# key -> (label, commercially usable)
_SOURCES: dict[str, tuple[str, bool]] = {
    "twse-openapi": ("臺灣證券交易所 OpenAPI（政府資料開放授權條款第 1 版）", True),
    "tpex-openapi": ("證券櫃檯買賣中心 OpenAPI（政府資料開放授權條款第 1 版）", True),
    "tdcc-opendata": ("臺灣集中保管結算所開放資料（政府資料開放授權條款第 1 版）", True),
    "shioaji-data": ("shioaji-data 官方資料（證交所、櫃買中心、公開資訊觀測站；政府資料開放授權條款第 1 版）", True),
    "ledger": ("本系統帳本", True),
    "rules": ("Forliosa 規則計算", True),
    "demo": ("示範資料（模擬）", True),
    "finmind": ("FinMind" + NON_COMMERCIAL_SUFFIX, False),
    "twse-mis": ("證交所 MIS 盤中行情・非官方" + NON_COMMERCIAL_SUFFIX, False),
    "twse-web": ("證交所網站資料・非 OpenAPI" + NON_COMMERCIAL_SUFFIX, False),
    "yahoo": ("Yahoo Finance" + NON_COMMERCIAL_SUFFIX, False),
}
# Provider names (MARKET_DATA_PROVIDERS) that are not commercially usable.
NON_COMMERCIAL_PROVIDERS = frozenset({"finmind", "twse_mis", "yahoo"})
_ALIASES = {"twse_mis": "twse-mis", "twse_openapi": "twse-openapi", "tpex_openapi": "tpex-openapi",
            "shioaji_data": "shioaji-data", "jitter": "demo"}


def _key(part: str) -> str:
    part = part.strip().lower()
    return _ALIASES.get(part, part)


def is_commercial_source(source: str) -> bool:
    """Every part of a composite source (``twse-mis+shioaji-data``) must be commercially usable."""
    parts = [_key(p) for p in source.split("+") if p.strip()]
    return all(_SOURCES.get(p, ("", False))[1] for p in parts) if parts else True


def allowed(source: str, policy: Policy) -> bool:
    return policy == "personal" or is_commercial_source(source)


def provider_allowed(name: str, policy: Policy) -> bool:
    return policy == "personal" or name.strip().lower() not in NON_COMMERCIAL_PROVIDERS


def label(source: str) -> str:
    key = _key(source)
    if key in _SOURCES:
        return _SOURCES[key][0]
    return source


def labels(sources: Iterable[str]) -> list[str]:
    """Labels for source keys (composite keys are split on ``+``), de-duplicated in order."""
    out: list[str] = []
    for s in sources:
        for part in (s or "").split("+"):
            if part.strip():
                out.append(label(part))
    return list(dict.fromkeys(out))


def allowed_sources(policy: Policy) -> list[str] | None:
    """Archive ``source`` values a query may use (``None`` = no restriction)."""
    if policy == "personal":
        return None
    return [k for k, (_, ok) in _SOURCES.items() if ok]
