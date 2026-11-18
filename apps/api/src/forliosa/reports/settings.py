"""The market reports' settings: the environment (``config.Settings``, contract §3.1) and the one database row an admin
changes at run time (``market_report_config``: the mode and the writer chosen per kind, §3.2). The blind test is gone
(產品負責人 2026-11-18): the mode is ``public`` or ``paused``; a ``trial`` left in the row reads as ``public``.

Writer resolution (§3.2, §4.5): ``writers[kind]`` from the database → the environment default (``AI_MREPORT_WRITE_*``;
the weekly has its own effort) → the month's budget tier (:func:`apply_tier`): ``medium`` lowers high / xhigh / max to
medium, ``sonnet`` switches to Claude Sonnet 5.5 at high, ``data_only`` writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from forliosa.config import Settings, get_settings
from forliosa.models import MarketReportConfig
from forliosa.timeutil import now_utc

MODES = ("public", "paused")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
WRITER_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5")  # what an admin may pick per kind (§14.2)
ADMIN_EFFORTS = ("low", "medium", "high", "xhigh")
TIERS = ("normal", "medium", "sonnet", "data_only")
SONNET = "claude-sonnet-5-5"


@dataclass(frozen=True)
class Writer:
    model: str
    effort: str

    def as_dict(self) -> dict[str, str]:
        return {"model": self.model, "effort": self.effort}

    @classmethod
    def parse(cls, raw: Any) -> Writer | None:
        if not isinstance(raw, dict):
            return None
        model, effort = raw.get("model"), raw.get("effort")
        if model not in WRITER_MODELS or effort not in EFFORTS:
            return None
        return cls(model, effort)


def config(db: Session, settings: Settings | None = None) -> MarketReportConfig:
    """The one config row, created on first read with ``MARKET_REPORTS_INITIAL_MODE``."""
    row = db.get(MarketReportConfig, 1)
    if row is not None:
        return row
    settings = settings or get_settings()
    row = MarketReportConfig(id=1, mode=mode_of(settings.market_reports_initial_mode), writers={}, updated_at=now_utc())
    db.add(row)
    try:
        db.commit()
    except IntegrityError:  # another process made it first
        db.rollback()
        row = db.get(MarketReportConfig, 1)
        assert row is not None
    return row


def mode_of(raw: str | None) -> str:
    """``paused`` stays paused; anything else (``public``, a ``trial`` left from before 2026-11-18) is public."""
    return "paused" if raw == "paused" else "public"


def mode(db: Session, settings: Settings | None = None) -> str:
    return mode_of(config(db, settings).mode)


def default_writer(kind: str, settings: Settings | None = None) -> Writer:
    s = settings or get_settings()
    effort = s.ai_mreport_write_effort_weekly if kind == "weekly" else s.ai_mreport_write_effort
    return Writer(s.ai_mreport_write_model, effort)


def chosen_writer(db: Session, kind: str, settings: Settings | None = None) -> Writer:
    """The admin's pick for ``kind``, else the environment default."""
    picked = Writer.parse((config(db, settings).writers or {}).get(kind))
    return picked or default_writer(kind, settings)


def apply_tier(writer: Writer, tier: str) -> Writer | None:
    """The writer under a budget tier; ``None`` for ``data_only`` (no model call)."""
    if tier == "data_only":
        return None
    if tier == "sonnet":
        return Writer(SONNET, "high")
    if tier == "medium" and writer.effort in ("high", "xhigh", "max"):
        return Writer(writer.model, "medium")
    return writer


def gather_model(settings: Settings | None = None) -> tuple[str, str]:
    s = settings or get_settings()
    return s.ai_mreport_gather_model, s.ai_mreport_gather_effort


def check_model(settings: Settings | None = None) -> tuple[str, str]:
    s = settings or get_settings()
    return s.ai_mreport_check_model, s.ai_mreport_check_effort
