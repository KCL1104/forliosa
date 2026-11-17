"""What the market reports spend: per call, per model that actually ran, per month, and the budget tier (contract §4).

* Every API call is booked per model that ran (:func:`usage_by_model`): with server-side fallbacks the top-level
  ``usage`` describes only the attempt that produced the answer, while ``usage.iterations`` records every attempt
  (the declined model's ``message`` entry, the serving model's ``fallback_message`` entry, compaction and advisor
  entries). When iterations are present they are summed per model instead of the top-level counts (never both).
  One ``ai_usage`` row per model, priced at that model's rates (``pricing.charge``: an unknown model at the highest
  known price, never a cheaper guess).
* Features: ``mreport_gather`` / ``mreport_write`` / ``mreport_check`` for live editions, ``mreport_trial`` for every
  call of a blind-test edition (its gathering included). ``user_id`` is empty (site-paid); ``thread_id`` is the run id
  (the gather id for a gathering).
* The month (Taipei, like ``store.month_start``) counts the three live features; the blind test has its own cap.
* Tier (§4.5, live editions only): below 70 % of AI_MREPORT_MONTHLY_BUDGET_USD normal; 70–90 % medium effort; 90–100 %
  Sonnet 5.5 at high; from 100 % data only. Then one step further down while the month plus the attempt's upper
  estimate (:data:`EST_MAX_USD`) would pass the budget. A budget of 0 means data-only editions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa.ai import store
from forliosa.ai.pricing import CallUsage, charge
from forliosa.config import Settings, get_settings
from forliosa.models import AiUsage
from forliosa.reports.settings import TIERS

LIVE_FEATURES = ("mreport_gather", "mreport_write", "mreport_check")
TRIAL_FEATURE = "mreport_trial"
FEATURE_OF_STEP = {"gather": "mreport_gather", "write": "mreport_write", "revise": "mreport_write",
                   "check": "mreport_check"}

# One attempt incl. its gathering and check, upper bound (USD); tune after the blind test.
EST_MAX_USD: dict[str, dict[str, float]] = {
    "premarket": {"normal": 2.0, "medium": 1.6, "sonnet": 0.9},
    "close": {"normal": 2.0, "medium": 1.6, "sonnet": 0.9},
    "weekly": {"normal": 3.5, "medium": 2.8, "sonnet": 1.5},
}
XHIGH_FACTOR = 1.4  # a blind-test variant at xhigh is estimated this much above "normal"


# -- one call ------------------------------------------------------------------------------------------------------
def server_tool_searches(usage: Any) -> int:
    stu = getattr(usage, "server_tool_use", None) if usage is not None else None
    return int(getattr(stu, "web_search_requests", 0) or 0) if stu is not None else 0


def server_tool_fetches(usage: Any) -> int:
    stu = getattr(usage, "server_tool_use", None) if usage is not None else None
    return int(getattr(stu, "web_fetch_requests", 0) or 0) if stu is not None else 0


def usage_by_model(msg: Any, requested: str) -> dict[str, CallUsage]:
    """One entry per model that actually ran. With server-side fallbacks the top-level usage is only the last
    attempt, so the iterations are summed instead (never both). Server-tool requests go to the serving model."""
    usage = getattr(msg, "usage", None)
    its = list(getattr(usage, "iterations", None) or []) if usage is not None else []
    served = getattr(msg, "model", None) or requested
    if its:
        out: dict[str, CallUsage] = {}
        # "message" (model may be None -> requested), "fallback_message", "compaction", "advisor_message"
        for it in its:
            model = getattr(it, "model", None) or requested
            out.setdefault(model, CallUsage()).add(CallUsage(
                input_tokens=getattr(it, "input_tokens", 0) or 0,
                output_tokens=getattr(it, "output_tokens", 0) or 0,
                cache_creation_input_tokens=getattr(it, "cache_creation_input_tokens", 0) or 0,
                cache_read_input_tokens=getattr(it, "cache_read_input_tokens", 0) or 0))
        u = out.setdefault(served, CallUsage())
        u.web_search_requests += server_tool_searches(usage)
        u.web_fetch_requests += server_tool_fetches(usage)
        return out
    return {served: CallUsage.from_sdk(usage)}


def fallback_used(msg: Any) -> bool:
    """A fallback model served (a ``fallback_message`` iteration) or a ``fallback`` block marks a hand-off."""
    usage = getattr(msg, "usage", None)
    if any(getattr(it, "type", None) == "fallback_message" for it in (getattr(usage, "iterations", None) or [])):
        return True
    return any(getattr(b, "type", None) == "fallback" for b in (getattr(msg, "content", None) or []))


def served_models(msg: Any, requested: str) -> list[str]:
    return list(usage_by_model(msg, requested))


@dataclass
class Booked:
    cost_usd: Decimal
    by_model: dict[str, CallUsage]
    rows: list[int] = field(default_factory=list)  # ai_usage ids

    def as_dict(self) -> dict[str, Any]:
        """For ``market_report_runs.calls`` (no content, counts only)."""
        return {"cost_usd": float(self.cost_usd), "served_models": list(self.by_model),
                "usage": {m: u.as_dict() for m, u in self.by_model.items()}}


def book_call(db: Session, msg: Any, *, requested: str, feature: str, thread_id: str | None,
              key_slot: int | None) -> Booked:
    """One ``ai_usage`` row per model that ran (site-paid: no user). Returns the total and the split."""
    by_model = usage_by_model(msg, requested)
    stop = getattr(msg, "stop_reason", None)
    total, ids = Decimal(0), []
    for model, u in by_model.items():
        row = store.record_usage(db, user_id=None, thread_id=thread_id, feature=feature, model=model,
                                 key_slot=key_slot, usage=u, stop_reason=stop)
        total += Decimal(row.cost_usd or 0)
        ids.append(row.id)
    return Booked(total, by_model, ids)


def cost_of(msg: Any, requested: str) -> Decimal:
    """What a call costs, without booking it (estimates, tests)."""
    return sum((charge(m, u) for m, u in usage_by_model(msg, requested).items()), Decimal(0))


# -- totals --------------------------------------------------------------------------------------------------------
def month_spend(db: Session, now: datetime | None = None) -> Decimal:
    """This Taipei month's live report spending (the blind test is not in it)."""
    total = db.scalar(select(func.coalesce(func.sum(AiUsage.cost_usd), 0)).where(
        AiUsage.feature.in_(LIVE_FEATURES), AiUsage.created_at >= store.month_start(now)))
    return Decimal(str(total or 0))


def trial_spend(db: Session) -> Decimal:
    """Everything the blind test has spent so far."""
    total = db.scalar(select(func.coalesce(func.sum(AiUsage.cost_usd), 0)).where(AiUsage.feature == TRIAL_FEATURE))
    return Decimal(str(total or 0))


# -- budget tier ---------------------------------------------------------------------------------------------------
def tier_of_spend(spent: Decimal, budget: Decimal) -> str:
    if budget <= 0:
        return "data_only"
    share = spent / budget
    if share >= 1:
        return "data_only"
    if share >= Decimal("0.9"):
        return "sonnet"
    if share >= Decimal("0.7"):
        return "medium"
    return "normal"


def tier(db: Session, kind: str, now: datetime | None = None, settings: Settings | None = None) -> str:
    """The tier of a live attempt of ``kind`` now: by the month's share of the budget, then lowered while the attempt's
    upper estimate would not fit what is left."""
    s = settings or get_settings()
    budget = Decimal(str(s.ai_mreport_monthly_budget_usd))
    spent = month_spend(db, now)
    t = tier_of_spend(spent, budget)
    while t != "data_only" and spent + Decimal(str(EST_MAX_USD[kind][t])) > budget:
        t = TIERS[TIERS.index(t) + 1]
    return t


def trial_estimate(kind: str, effort: str | None) -> Decimal:
    """The upper estimate of one blind-test variant (xhigh / max: :data:`XHIGH_FACTOR` above)."""
    est = Decimal(str(EST_MAX_USD[kind]["normal"]))
    if effort in ("xhigh", "max"):
        est *= Decimal(str(XHIGH_FACTOR))
    return est


def trial_reserved(db: Session) -> Decimal:
    """What the blind-test variants still running may yet spend: each one's estimate less what it has booked (its
    booked calls are already in :func:`trial_spend`)."""
    from forliosa.models import MarketReport, MarketReportRun

    rows = db.execute(select(MarketReport.kind, MarketReportRun.writer, MarketReportRun.cost_usd)
                      .join(MarketReport, MarketReport.id == MarketReportRun.report_id)
                      .where(MarketReportRun.purpose == "trial", MarketReportRun.status == "running"))
    total = Decimal(0)
    for kind, writer, cost in rows:
        total += max(trial_estimate(kind, (writer or {}).get("effort")) - Decimal(str(cost or 0)), Decimal(0))
    return total


def trial_fits(db: Session, kind: str, effort: str, settings: Settings | None = None) -> bool:
    """A blind-test variant may start while the trial's spending, what the running variants may yet spend and its own
    estimate stay within the trial cap (the three variants of an edition start one after the other: each sees the
    ones queued before it)."""
    s = settings or get_settings()
    return trial_spend(db) + trial_reserved(db) + trial_estimate(kind, effort) \
        <= Decimal(str(s.ai_mreport_trial_budget_usd))
