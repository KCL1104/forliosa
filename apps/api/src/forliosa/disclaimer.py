"""全站的免責文字（產品負責人 2026-11-17：「清楚標示我們只是替使用者整理資訊，不是在為他們做投顧服務」）.

The same strings as the frontend's ``apps/web/src/lib/disclaimer.ts`` (``tests/test_disclaimer.py`` compares the two);
the full statement is ``docs/legal/disclaimer.md`` (the ``/disclaimer`` page) and the terms' §2.

* :data:`SHORT` — once in every push / channel message (trades, weekly digest, daily report, the "channel connected"
  messages) and in the data export. Build pushes with ``services.notifications.signed`` (it adds the line).
* :data:`AI_LABEL` / :data:`AI_NOTE` — a push with an AI-written paragraph (weekly digest, daily report): the paragraph
  starts with ``AI_LABEL`` and the last line is ``AI_NOTE`` + ``SHORT`` (``signed(..., ai=True)``), the push version
  of the ``AI`` line under the same content on the web.
* :data:`AI` — under AI-written content: ``done.disclaimer`` and ``GET /ai/usage`` (chat answers), the ``disclaimer``
  of group weekly digests and daily reports.
* :data:`ANALYST` — the ``disclaimer`` of ``/instruments/{symbol}/analyst-views`` (third-party ratings and targets).

A disclaimer does not make advice-like content acceptable: the AI prompts keep their own rules (no buy/sell calls, no
targets of our own, no predictions).
"""

from __future__ import annotations

SHORT = "Forliosa 只替你整理公開資訊與你自己的紀錄，不是投資顧問，不提供投資建議；投資決定請自己判斷。"
AI = "AI 只替你整理資訊，可能有錯；Forliosa 不是投資顧問，不提供投資建議。"
ANALYST = ("以下是媒體報導的第三方機構看法，可能不完整或未經授權轉載；Forliosa 只替你整理，不代表本站意見，"
           "也不是投資建議。")
# Pushes with an AI-written paragraph (DESIGN.md: AI-written text is told apart by 「AI 整理」 and the line under it)
AI_LABEL = "AI 整理："
AI_NOTE = "AI 整理的部分可能有錯。"
