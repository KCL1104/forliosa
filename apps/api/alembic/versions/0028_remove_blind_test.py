"""市場報告: the blind test removed (產品負責人 2026-11-18: 「盲測的部分就直接拔掉吧」)

Reports are public for every signed-in user, written once with the default writer (Opus 5.5 at high) and pushed
with the normal public push. The data:

* ``market_report_config.mode``: ``trial`` becomes ``public`` (``paused`` / ``public`` stay as they are).
* Every blind-test edition (``market_reports.trial``) becomes a normal public edition: its current version becomes
  the variant written with the default writer (``claude-opus-5-5`` at ``high``), else variant A, else the
  alphabetically first label (B before C), each label's newest version, made a plain version (``variant`` null: the
  label stays on its run, ``market_report_versions.run_id`` → ``market_report_runs.variant``); ``state = ai`` and
  ``ai_published_at`` = that version's time. Two exceptions keep the pick from replacing what the new pipeline
  should write:

  - an edition whose current version is already a plain AI version (``edition = ai``, ``variant`` null: a worker on
    the new code wrote it before the api ran this migration) keeps it;
  - an edition still open (``pushed_at`` and ``closed_at`` both null, e.g. today's close when the deploy is late)
    takes only the default writer's variant; without one it keeps its data edition, and the normal pipeline writes
    it once with Opus 5.5 at high before its push. An open edition with no variant at all (today's close made at
    14:10 as a blind-test one) is the same: it keeps its data edition.

  ``visibility = public`` and ``trial = false`` for all of them, so today's 11/18 premarket shows one report to
  everyone. ``pushed_at`` is left as it is (a blind-test push already went: it is not pushed again; the push deadline
  of a past edition has passed anyway). A close edition's 23:45 / 06:40 ``tables`` versions were built from its data
  edition while it was a blind-test one, so the kept variant carries the 15:40 tables: rebuild them once after the
  deploy with ``python -m forliosa.reports tables --promoted`` (no model call, never pushed).
* Nothing is dropped: the votes, the runs (their ``variant`` / ``purpose``), the other variants' versions and the
  config's ``trial_audience`` / ``trial_started_on`` / ``revealed_at`` columns stay (history; the code no longer
  reads them).

Downgrade: nothing for the data (the blind test is not brought back; the old code reads these editions as normal
public ones).

Revision ID: 0028_remove_blind_test
Revises: 0027_channel_four_switches
Create Date: 2026-11-18 13:00:00.000000
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

import forliosa.db

revision: str = '0028_remove_blind_test'
down_revision: str | None = '0027_channel_four_switches'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_WRITER = ('claude-opus-5-5', 'high')  # AI_MREPORT_WRITE_MODEL / _EFFORT (and _EFFORT_WEEKLY) defaults

config = sa.table('market_report_config', sa.column('id', sa.Integer), sa.column('mode', sa.String))
reports = sa.table('market_reports', sa.column('id', sa.String), sa.column('trial', sa.Boolean),
                   sa.column('visibility', sa.String), sa.column('state', sa.String),
                   sa.column('current_version_id', sa.String),
                   sa.column('pushed_at', forliosa.db.TZDateTime(timezone=True)),
                   sa.column('closed_at', forliosa.db.TZDateTime(timezone=True)),
                   sa.column('first_published_at', forliosa.db.TZDateTime(timezone=True)),
                   sa.column('ai_published_at', forliosa.db.TZDateTime(timezone=True)))
versions = sa.table('market_report_versions', sa.column('id', sa.String), sa.column('report_id', sa.String),
                    sa.column('version', sa.Integer), sa.column('variant', sa.String),
                    sa.column('edition', sa.String), sa.column('writer', sa.JSON),
                    sa.column('created_at', forliosa.db.TZDateTime(timezone=True)))


def _writer(raw: Any) -> tuple[Any, Any]:
    if isinstance(raw, str):  # a driver that hands JSON back as text
        import json

        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    return (raw.get('model'), raw.get('effort')) if isinstance(raw, dict) else (None, None)


def pick(rows: list[Any], *, open_: bool = False) -> Any | None:
    """The version to keep for one blind-test edition: per label its newest version; the default writer's, else A,
    else the alphabetically first label (B before C). An open edition (``open_``) takes only the default writer's:
    without one the normal pipeline writes it."""
    newest: dict[str, Any] = {}
    for row in rows:
        if row.variant and (row.variant not in newest or row.version > newest[row.variant].version):
            newest[row.variant] = row
    if not newest:
        return None
    for label in sorted(newest):
        if _writer(newest[label].writer) == DEFAULT_WRITER:
            return newest[label]
    if open_:
        return None
    return newest.get('A') or newest[sorted(newest)[0]]


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(config.update().where(config.c.mode == 'trial').values(mode='public'))
    trial = list(bind.execute(sa.select(reports.c.id, reports.c.first_published_at, reports.c.current_version_id,
                                        reports.c.pushed_at, reports.c.closed_at)
                              .where(reports.c.trial == sa.true())))
    for report_id, first_published, current_id, pushed_at, closed_at in trial:
        values: dict[str, Any] = {'trial': False, 'visibility': 'public'}
        cur = bind.execute(sa.select(versions.c.edition, versions.c.variant)
                           .where(versions.c.id == current_id)).first() if current_id else None
        if cur is not None and cur.edition == 'ai' and cur.variant is None:
            # a live AI version is already current (a worker on the new code wrote it first): keep it
            bind.execute(reports.update().where(reports.c.id == report_id).values(**values))
            continue
        rows = list(bind.execute(sa.select(versions.c.id, versions.c.version, versions.c.variant,
                                           versions.c.writer, versions.c.created_at)
                                 .where(versions.c.report_id == report_id, versions.c.variant.is_not(None),
                                        versions.c.edition == 'ai')))
        chosen = pick(rows, open_=pushed_at is None and closed_at is None)
        if chosen is not None:
            values.update(current_version_id=chosen.id, state='ai', ai_published_at=chosen.created_at,
                          first_published_at=first_published or chosen.created_at)
            bind.execute(versions.update().where(versions.c.id == chosen.id).values(variant=None))
        bind.execute(reports.update().where(reports.c.id == report_id).values(**values))


def downgrade() -> None:
    pass  # the data stays as it is: the blind test is not brought back (see the docstring)
