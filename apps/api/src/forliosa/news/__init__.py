"""個股頁「新聞報導」: media headlines (original title, outlet, time, link to the original site) per symbol.

Product owner 2026-11-12 (PRODUCT.md 「相關新聞」 and 「個股頁補強」 1–2; research:
``docs/research/news-and-external-sources.md``). Only metadata is stored — never article text, descriptions or
images — for 30 days; outlets that ask to be removed go on the takedown blocklist.

* :mod:`forliosa.news.sources` — GDELT DOC 2.0 (default), SearXNG (off by default), Yahoo股市 RSS (personal only)
* :mod:`forliosa.news.ai_search` — AI web search fills gaps (system-paid, monthly cap)
* :mod:`forliosa.news.normalize` / :mod:`forliosa.news.outlets` — spacing, suffixes, outlet names, relevance,
  de-duplication, blocklist matching
* :mod:`forliosa.news.service` — the worker batch, storage, retention and the ``/news`` read path
* ``python -m forliosa.news`` — ``refresh``, ``block`` / ``unblock`` / ``blocked`` (takedowns), ``purge``
"""
