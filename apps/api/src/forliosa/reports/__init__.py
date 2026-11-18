"""市場報告：盤前重點、盤後重點、市場週報 (產品負責人 2026-11-17「照建議」; contract
``market-reports/build/contract.md``, memo of the same day).

One shared report per edition for every signed-in user (no public address), written from a data pack the server
builds from the archive and from named media reports the gathering found and checked:

1. **Data pack** (:mod:`.pack`, :mod:`.marketcalc`, :mod:`.blocks`, :mod:`.calendars`, :mod:`.timing`): every number
   with an id, its subject and date; the rule-made stock and sector lists; the calendar; the charts (G1–G7) and
   tables. Data policy first; only rows that existed at the cut-off.
2. **Gathering** (web search, Claude Sonnet 5.5 at low effort; allowed domains only) → verified reports (X ids).
3. **Writing** (Claude Opus 5.5 at high effort, streamed, server-side fallbacks) → JSON whose every sentence cites ids.
4. **Checks**: rule validators, then a compliance read (Claude Haiku 5.5); one revision; else a section is dropped;
   else the data-only edition.
5. **Publishing** (versions kept two years, corrections marked) and pushes to group channels (text and a link).

Content boundary A1: facts, scheduled events, named sources' statements, past sector and stock comparisons and
rule-picked stocks only — no outlook of our own, no direction, target, support or advice. Dates, never 「明天」.

Status: ``cd apps/api && uv run python -m forliosa.reports status``. Every edition is public for every signed-in user,
written once with Opus 5.5 at high (the blind test was removed on 2026-11-18). Site-paid, US$80 a month with stepwise
downgrades (:mod:`.accounting`); the reports' own key slot ``CLAUDE_API_KEY_4`` when set.
"""
