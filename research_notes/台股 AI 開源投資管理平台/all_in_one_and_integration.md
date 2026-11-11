# All-in-one AI + portfolio platforms (Chinese-speaking OSS focus) and integration glue for Taiwan stocks

Research date: 2026-11-11. Star counts, licenses and last-push dates come from the public GitHub search API (`/search/repositories?q=repo:OWNER/NAME`), pulled on 2026-11-11 unless noted. The per-repo REST endpoint was blocked in this environment, so "last push" means `pushed_at`, which can include pushes to non-default branches. Feature claims come from each project's README or docs on its default branch.

Scope note: this file skips Ghostfolio and Portfolio Performance core tracking, TradingAgents, OpenBB, FinGPT, ai-hedge-fund and the FinMind/twstock libraries. Other researchers cover those. Ghostfolio appears here only for its AI and MCP integration features.

---

## Q1. Which open-source projects come closest to "Google Finance / Yahoo 股市 + AI analyst + my positions & performance" in one self-hostable package, and does Taiwan (.TW/.TWO, TWD) work?

### Takeaway
No project fully covers "quotes + valuation + AI analyst + holdings P&L + Taiwan." The closest is **ZhuLinsen/daily_stock_analysis (DSA)**: MIT, about 69.9k★, active daily. It has a web workbench with AI reports, an agent chat, a portfolio ledger (trades, cash, corporate actions, FIFO/avg cost, risk), alerts and many push channels. Since mid-2026 it has explicit `.TW`/`.TWO` support with 三大法人 data. Its Taiwan portfolio valuation in TWD is officially only "partial," and its UI is Simplified Chinese/English.
- **PanWatch** (MIT, about 2.4k★) is the most polished holdings + P&L + AI (TradingAgents) + alerts + PWA product. It covers only CN/HK/US.
- **go-stock** (GPL-3.0, about 8.1k★) is a feature-rich A-share desktop AI tool. Its holdings tracking is weak, it has no Taiwan support, and some features sit behind paid VIP tiers.
- **ValueCell** looks stale: last push 2026-03-09, and it has pivoted to a hosted service.
- **QuantDinger** and **Fincept Terminal** are trading/research terminals rather than position trackers, and both are open-core.
- Western trackers now ship AI. **Wealthfolio**, **Investbrain**, **Sure** and **Ghostfolio** all add AI chat and/or a built-in MCP server on top of real holdings. Wealthfolio has a Traditional Chinese UI. Investbrain is CC BY-NC, so it is not OSI-open.
- Taiwan-native all-in-ones exist (EquiLens, 台股情報站, FinPilot, StackWorth). Each is tiny (≤50★) and single-maintainer.

### Cited Findings

**A. ZhuLinsen/daily_stock_analysis (DSA, 股票智能分析系统). Strongest all-in-one, with explicit Taiwan support.**
- Metadata: 69,886★, 56,773 forks (users fork it to run the GitHub Actions workflow), last push 2026-11-10, MIT, Python — [GitHub API](https://api.github.com/search/repositories?q=repo:ZhuLinsen/daily_stock_analysis)
- Tagline: "基于 AI 大模型的 A股/港股/美股/日股/韩股/台股自选股智能分析系统，每日自动分析并推送「决策仪表盘」到企业微信/飞书/Telegram/Discord/Slack/邮箱" — [README](https://github.com/ZhuLinsen/daily_stock_analysis)
- Features: AI decision reports (conclusion, score, trend, buy/sell levels, risk alerts, catalysts, checklist). Web/desktop workbench with manual analysis, history, backtest, **持仓 (portfolio)**, config, and light/dark themes. Agent "策略问股" multi-turn chat with 15 built-in strategies. Import from image, CSV/Excel or clipboard. Runs via GitHub Actions, Docker or FastAPI — [README](https://github.com/ZhuLinsen/daily_stock_analysis)
- LLMs: Gemini, OpenAI-compatible (DeepSeek, 通义千问/Qwen), Claude, Ollama, plus sponsored aggregators (Modelflare, AIHubMix) — [README](https://github.com/ZhuLinsen/daily_stock_analysis)
- Data layer: AkShare, Tushare, Pytdx, Baostock, YFinance, Longbridge. News: SerpAPI, Tavily, Bocha, Brave, MiniMax, SearXNG and others — [README](https://github.com/ZhuLinsen/daily_stock_analysis)
- Portfolio module (`/portfolio`): multiple accounts, `fifo`/`avg` cost methods, KPI snapshot, risk summary (concentration, drawdown, stop-loss proximity, sector concentration), Top Positions chart. You can enter trades, cash ledger and corporate actions. CSV import with dry-run only ships parsers for mainland brokers `huatai`, `citic` and `cmb`. Online FX refresh. REST endpoints include `/api/v1/portfolio/snapshot`, `/risk`, `/trades`, `/cash-ledger` and `/corporate-actions` — [full-guide.md](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/full-guide.md)
- The AI is wired to holdings:
  - The portfolio page has a per-position "manual single-stock analysis" entry (`POST /api/v1/portfolio/positions/{symbol}/analysis`).
  - Latest AI DecisionSignals render next to each holding.
  - `GET /api/v1/portfolio/risk` adds a `decision_signal_risk` block that aggregates active sell/reduce/alert signals on held positions.
  - The agent can call `get_portfolio_snapshot`.
  - Source: [full-guide.md](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/full-guide.md)
- Broker holdings import: `python main.py --portfolio futu` reads real LONG stock positions read-only through Futu OpenD. Futu conversion supports only A-shares, HK and US; other Futu markets are skipped — [full-guide.md](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/full-guide.md)
- Alerts center: persistent rules, including `portfolio_holdings` and `portfolio_account` targets, plus a `portfolio_price_stale` rule. Market-level "Market Light" rules accept only `cn|hk|us|jp|kr` — [full-guide.md](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/full-guide.md)
- Notification channels: WeCom, Feishu, Telegram, Discord, Slack, email, PushPlus, Server酱³, ntfy, Gotify, Pushover and custom webhooks. **LINE is not listed** — [full-guide.md](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/full-guide.md)
- UI language switch supports only `zh` / `en`. A Traditional Chinese README exists (docs only) — [full-guide.md](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/full-guide.md); [README_CHT.md](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/README_CHT.md)
- **Taiwan support details** — [market-support.md](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/market-support.md)
  - Input is strictly suffix-based: TWSE `.TW` (e.g. `2330.TW`, `0050.TW`, `00878.TW`) and TPEx `.TWO` (e.g. `6488.TWO`). Bare `2330` is not recognized as Taiwan.
  - Taiwan flows into single-stock analysis, history, reports, DecisionSignal, Portfolio and Intelligence.
  - Daily and near-real-time quotes go **only through YfinanceFetcher**. AkShare and Tushare are not used for Taiwan.
  - A `TwInstitutionalFetcher` pulls 三大法人 buy/sell from TWSE T86 and the TPEx OpenAPI and injects it into the LLM prompt. The prompt carries Taiwan semantics (新台币, ±10% limits, 三大法人) and avoids A-share concepts.
  - Trading calendar is `XTAI`. Indices are `^TWII` and `^TWOII`. Amounts are labelled TWD.
  - **Not supported yet:** a Taiwan stock index/autocomplete; `MARKET_REVIEW_REGION=tw` (market review); Taiwan in alert MarketRegion and Market Light; full Taiwan fundamentals and breadth.
  - The doc says it does not complete the portfolio's TWD FX, cost or market-value logic: "台股 Portfolio 当前属于 partial valuation 市场."
- Valuation bands (PE/PB percentile bands) are not mentioned as a feature. Grepping the full guide for 市盈率/估值分位 turned up nothing relevant. Longbridge is described as filling in "量比、换手率、PE 等字段" for HK/US only — [README](https://github.com/ZhuLinsen/daily_stock_analysis)

**B. TNT-Likely/PanWatch. Best holdings + AI + alerts UX, no Taiwan.**
- Metadata: 2,446★, created 2026-01-23, last push 2026-11-08, MIT, Python. Topics include `akshare` and `deepseek` — [GitHub API](https://api.github.com/search/repositories?q=repo:TNT-Likely/PanWatch)
- "Monitor A-shares, Hong Kong, and U.S. stocks, manage your portfolios, and research ideas with TradingAgents. Self-host PanWatch with your preferred OpenAI-compatible provider or local models through Ollama." — [README](https://github.com/TNT-Likely/PanWatch)
- Features:
  - Multiple brokerage accounts, holdings and P&L.
  - A nine-agent TradingAgents deep analysis launched from a holding (the brain icon). It produces a bull/bear debate, risk review and PM decision memo in 3–5 minutes.
  - Scheduled pre-market, intraday and closing agents.
  - AND/OR price alerts with cooldowns.
  - AI-scored opportunities and paper trading with an equity curve.
  - Notifications via Telegram, WeCom, DingTalk, Feishu, Bark and webhooks.
  - Installable PWA, Docker one-liner (`sunxiao0721/panwatch`). UI in English, 简体中文 and 日本語.
  - Source: [README](https://github.com/TNT-Likely/PanWatch)
- Markets: "mainland China, Hong Kong and US markets." No Taiwan, and no LINE — [README](https://github.com/TNT-Likely/PanWatch)

**C. ArvinLovegood/go-stock. Rich A-share desktop AI tool, weak on holdings, no Taiwan.**
- Metadata: 8,120★, last push 2026-11-10, default branch `dev`, created 2024-12-17. GitHub reports GPL-3.0 and the `dev` LICENSE file is GPL v3 — [GitHub API](https://api.github.com/search/repositories?q=repo:ArvinLovegood/go-stock); [LICENSE (dev)](https://github.com/ArvinLovegood/go-stock/blob/dev/LICENSE). **Conflict:** the stale `master` README still says "Apache License 2.0" — [master README](https://github.com/ArvinLovegood/go-stock/blob/master/README.md)
- Desktop app built with Wails + NaiveUI. Ships for Windows; a macOS "绿色版" also ships. Development targets Windows 10+: "其他平台未测试或功能受限" — [dev README](https://github.com/ArvinLovegood/go-stock/blob/dev/README.md)
- Features (dev README):
  - Quotes for A-shares, HK and US, plus ETF search.
  - A built-in AI agent with React, PlanExecute and DeepAgents modes, 150+ AI data tools, a skill system, **MCP extensions** (MCP OAuth 2.1 since 2026-08) and a floating assistant. Vision input lets you ask about a screenshot or a K-line chart.
  - K-line analysis, capital flows, 龙虎榜, 涨停梯队, policy news, a knowledge base with long-term memory, daily review and pre-market strategy.
  - 交易日志, a trade-record import template, and "用户画像持仓推断" (inferring holdings from a user profile).
  - Push via Feishu and DingTalk.
  - Source: [dev README](https://github.com/ArvinLovegood/go-stock/blob/dev/README.md)
- LLMs: any OpenAI-format API, Ollama, LMStudio, DeepSeek, 智谱 GLM, and aggregators (SiliconFlow, 火山方舟). A 2026-04 issue reports errors with GPT-5.4 while DeepSeek and Qwen work — [dev README](https://github.com/ArvinLovegood/go-stock/blob/dev/README.md); [issue #154](https://github.com/ArvinLovegood/go-stock/issues/154)
- **Open-core flag:** VIP tiers ("vip2" at 28.8 RMB/month) unlock 24-hour market-news sync and the "go-stock Ai助手". Background buy/sell signal monitoring (2026-09-22) "需 VIP2 及以上赞助用户" — [dev README](https://github.com/ArvinLovegood/go-stock/blob/dev/README.md)
- Recent releases are near-daily (v2026.11.10.1 on 2026-11-10) and focus on signal scanners, MASS index and OKX crypto auto-trading. Release notes show no holdings/P&L tracker work — [Releases](https://github.com/ArvinLovegood/go-stock/releases)
- Taiwan: the README never mentions Taiwan or 台股. An issue search for 台湾 returns 0 results — [issue search](https://github.com/ArvinLovegood/go-stock/issues?q=%E5%8F%B0%E6%B9%BE)

**D. ValueCell-ai/valuecell. Popular but stale as OSS.**
- Metadata: 11,054★, created 2025-09-01, **last push 2026-03-09** (about 8 months stale as of 2026-11), Apache-2.0 — [GitHub API](https://api.github.com/search/repositories?q=repo:ValueCell-ai/valuecell)
- The README now says: "ValueCell now provides A-share deep research, market analysis and requires no deployment—access directly at valuecell.ai". This is a pivot to a hosted service — [README](https://github.com/ValueCell-ai/valuecell)
- Features: multi-agent research ("stock selection, research, tracking, and even trading"), a Strategy Agent for crypto, and live routing to Binance, OKX and Hyperliquid (contracts only). LLMs: OpenRouter, SiliconFlow, Azure, OpenAI-compatible, Google, OpenAI, DeepSeek. Markets: "US market, Crypto market, Hong Kong market, China market." Portfolio summaries and multi-channel delivery appear only as roadmap items. README in English, 简体 and 繁體 — [README](https://github.com/ValueCell-ai/valuecell)

**E. OpenByteInc/QuantDinger. Agentic trading OS, open-core.**
- Metadata: 13,697★, last push 2026-11-11, backend Apache-2.0. Separate repos QuantDinger-Vue (168★) and QuantDinger-Mobile (160★) carry their own "source-available" licenses — [GitHub API](https://api.github.com/search/repositories?q=QuantDinger); [README](https://github.com/OpenByteInc/QuantDinger)
- Features: multi-provider AI research, strategies, backtesting, paper and live execution (crypto exchanges, IBKR, Alpaca), and signal-only virtual accounts with positions, PnL and an equity curve. Agent Gateway plus an MCP server. LLMs: OpenRouter, OpenAI-compatible, Google, DeepSeek, Grok, MiniMax. README in 简体 and 繁體. Also sold through AWS Marketplace — [README](https://github.com/OpenByteInc/QuantDinger)
- It is not a holdings tracker. An A-share support request (#134) was closed. No Taiwan issues were found — [issue #134](https://github.com/OpenByteInc/QuantDinger/issues/134)

**F. Fincept-Corporation/FinceptTerminal. Bloomberg-style desktop terminal, open-core.**
- Metadata: 33,691★, last push 2026-11-09, AGPL-3.0, C++ — [GitHub API](https://api.github.com/search/repositories?q=repo:Fincept-Corporation/FinceptTerminal)
- Native C++20/Qt6 desktop app with embedded Python 3.11; latest release v4.5.2. 37 AI agents; bring your own key (OpenAI, Anthropic, Gemini, Groq, DeepSeek, OpenRouter, Ollama). Also portfolio optimisation, VaR/Sharpe, paper trading, 16 broker integrations and MCP tools. README translated into 简体 and 繁體 — [README](https://github.com/Fincept-Corporation/FinceptTerminal)
- **Open-core:** "This repo is the free AGPL-3.0 edition… Enterprise is the private, closed-source build." Enterprise costs $15/$30/$45 per user per month and adds managed live trading and deep research — [README](https://github.com/Fincept-Corporation/FinceptTerminal)

**G. hsliuping/TradingAgents-CN web UI (brief).**
- Metadata: 32,882★, last push 2026-09-22, license NOASSERTION — [GitHub API](https://api.github.com/search/repositories?q=repo:hsliuping/TradingAgents-CN)
- Mixed license: "专有部分（需商业授权）：`app/`（FastAPI后端）和 `frontend/`（Vue前端）目录." Commercial use needs authorization. Newer versions (v2.0/v3.0) add "持仓研究、Skill 系统、智能助手" under a staged-open-source policy. Markets: A/HK/US — [README](https://github.com/hsliuping/TradingAgents-CN)

**H. Western trackers that have added AI. Holdings are first-class; the AI is a chat/MCP layer.**
- **Wealthfolio** (now `wealthfolio/wealthfolio`): 9,418★, last push 2026-11-11, AGPL-3.0, Rust/Tauri desktop. Latest release v3.12.0 on 2026-11-01 — [GitHub API](https://api.github.com/search/repositories?q=wealthfolio); [Releases](https://github.com/wealthfolio/wealthfolio/releases)
  - The README lists "🤖 AI Assistant – Ask questions and import CSV files with a local model or your own API key, and connect AI agents such as Claude, ChatGPT or Cursor through MCP", plus an addon system, multi-currency and 11 languages — [README](https://github.com/wealthfolio/wealthfolio)
  - Release notes:
    - v3.8.0 added **Traditional Chinese**.
    - v3.10.0 added MCP tools (link transfers, import quotes, update activities, categorize).
    - v3.11.0 added "AI Agent Access" with ready-to-copy setup for Claude Code, Codex, ChatGPT desktop and Cursor, and the assistant "works with current Claude, GPT and Gemini models."
    - v3.12.0 added a "Red up, green down" colour option for China/Taiwan/Korea/Japan conventions, plus a market-data provider catalog and custom providers.
    - Source: [Releases](https://github.com/wealthfolio/wealthfolio/releases)
  - Open-core note: Wealthfolio Connect (brokerage sync and multi-device sync) is an optional paid subscription — [README](https://github.com/wealthfolio/wealthfolio)
- **Investbrain**: 940★, last push 2026-11-11, PHP — [GitHub API](https://api.github.com/search/repositories?q=repo:investbrainapp/investbrain)
  - **License is CC BY-NC 4.0** (Attribution-NonCommercial), so it is not OSI open source — [LICENSE.md](https://github.com/investbrainapp/investbrain/blob/main/LICENSE.md)
  - AI chat window on portfolio and holding pages (`AI_CHAT_ENABLED`). `CHAT_PROVIDER` accepts openai, anthropic, gemini, azure, groq, xai, deepseek, mistral or ollama.
  - Market data defaults to Yahoo Finance, with Finnhub, Alpha Vantage, Alpaca and Twelve Data as alternatives and comma-separated fallback. You can add custom provider classes.
  - Source: [self-hosting.md](https://github.com/investbrainapp/investbrain/blob/main/docs/self-hosting.md)
  - Also has a hosted cloud at investbra.in — [README](https://github.com/investbrainapp/investbrain)
- **Sure** (community fork of Maybe): 12,603★, last push 2026-11-11, AGPL-3.0. Maybe itself is archived (last push 2025-07-24, 54,194★) — [GitHub API](https://api.github.com/search/repositories?q=repo:we-promise/sure); [GitHub API (maybe)](https://api.github.com/search/repositories?q=repo:maybe-finance/maybe)
  - The built-in AI uses `OPENAI_ACCESS_TOKEN`, `OPENAI_MODEL` and `OPENAI_URI_BASE` (any OpenAI-compatible endpoint, including local models) for chat, auto-categorization and PDF processing — [.env.example](https://github.com/we-promise/sure/blob/main/.env.example)
  - Render templates come in "No AI", "Simple AI" and "External AI (OpenClaw)" variants — [README](https://github.com/we-promise/sure)
  - Sure is a personal-finance and budgeting app first; investments are one account type.

**I. Other Chinese-community AI + holdings projects (smaller or narrower)**
- **oficcejo/aiagents-stock**: 2,083★, last push 2026-10-10, **no license file** (GitHub: None), Streamlit. Six AI analysts for A/HK/US, AI 盯盘 with 持仓管理, "持仓定时分析" (a holdings list with batch and scheduled analysis), and email/DingTalk/Feishu push. Requires a DeepSeek key — [GitHub API](https://api.github.com/search/repositories?q=AI+%E7%82%92%E8%82%A1&sort=stars); [README](https://github.com/oficcejo/aiagents-stock)
- **jundizhou/easy-stock** ("A股 AI 投研"): 1,823★, last push 2026-11-11, license NOASSERTION, Go. Features "持仓 AI 巡检" (four-dimension scoring per holding) and "AI 持仓优化" (original vs. suggested portfolio). Local-first, A-share only — [README](https://github.com/jundizhou/easy-stock)
- **Open-Dev-Society/OpenStock**: 21,419★, AGPL-3.0. Finnhub quotes, TradingView charts, a 50-stock watchlist, email price alerts and a weekly AI news digest. **No holdings/P&L** — [README](https://github.com/Open-Dev-Society/OpenStock). An AGPL fork, ouyang-2019/OpenStock-Enhanced (37★, last push 2026-02-20), adds A/HK data, Gemini/DeepSeek/OpenAI analysis and Telegram/WeChat/Feishu/DingTalk push — [GitHub API](https://api.github.com/search/repositories?q=OpenStock&sort=stars)
- **x-pai/AlphaBot** (406★, NOASSERTION) is an OpenAI-based 股票分析助手 with scheduled market reports. **CodeNightOwl/ai-trading-assistant** (81★, MIT) covers review, portfolio, analysis and risk across A/HK/US, crypto and futures — [GitHub API](https://api.github.com/search/repositories?q=%E6%8C%81%E4%BB%93+AI&sort=stars)
- **Fire0206/Presight-AI** (知几, 34★) targets funds: real-time fund valuation, holdings tracking and AI research with RAG — [GitHub API](https://api.github.com/search/repositories?q=%E6%8C%81%E4%BB%93+AI&sort=stars)

**J. Taiwan-native all-in-ones (Traditional Chinese, Taiwan data). All very small.**
- **wakin61043/tw-trading-dashboard (EquiLens 衡析)**: 49★, created 2026-10-11, last push 2026-11-10, MIT — [GitHub API](https://api.github.com/search/repositories?q=%E5%8F%B0%E8%82%A1+%E5%84%80%E8%A1%A8%E6%9D%BF&sort=stars)
  - Self-hosted Taiwan dashboard with a Traditional Chinese UI (English also available).
  - Research scores, sector heatmap, an intraday radar (a Fugle WebSocket stream when a key is set) and day-trade monitoring.
  - Chip tracking through FinMind Sponsor (broker branches, shareholding distribution), custom price/volume alerts pushed to a phone PWA (EquiLens Pocket, Firebase push via a Cloudflare Worker), and an AI after-market report from Claude, OpenAI, Gemini or any OpenAI-compatible endpoint, including local models.
  - The README does not describe a holdings/P&L ledger.
  - Source: [README](https://github.com/wakin61043/tw-trading-dashboard)
- **JauWei/tw_stock_intel (台股情報站 v3)**: 3★, last push 2026-05-30, **no license**. FastAPI + yfinance + FinMind + Google News + Gemini single-page dashboard. Under 個人持股 it auto-calculates 成本/市值/損益/報酬率/權重. Holdings, indicators and 籌碼 go to Gemini for a 4–6 sentence Chinese assessment. Telegram price alerts scan every 5 minutes. FinMind provides monthly revenue and quarterly EPS — [README](https://github.com/JauWei/tw_stock_intel)
- **hu0937/FinPilot**: 26★, last push 2026-05-31, MIT. Taiwan + US daily quant platform: FinMind/FinLab for TW, yfinance for US, Telegram bot, Claude natural-language queries, a 持倉掃描器, and a strategy agent that runs `claude --print` (needs a Claude Code Pro/Max subscription) — [README](https://github.com/hu0937/FinPilot)
- **wppypewo/portfolio-tracker (StackWorth)**: 1★, MIT. TWD-denominated tracker for US ETFs, Taiwan stocks and crypto, with XIRR/TWR, Sharpe and drawdown. Next.js + Supabase PWA with Twelve Data, FinMind and CoinGecko free tiers. No AI — [README](https://github.com/wppypewo/portfolio-tracker)
- Other small Taiwan repos found by search, none with significant adoption:
  - kerr20801/taiwan-stock-ai-analyzer (51★, ML models + Telegram signals)
  - michaelbothsieh-crypto/tw-stock-health-dashboard (5★, AI + Telegram)
  - maplestartend/twstock-research (2★, includes 持股組合)
  - sacahan/CasualTrader (14★, Taiwan AI paper-trading on OpenAI Agents SDK + MCP, last push 2025-12-05)
  - Source: [GitHub search 台股 AI](https://api.github.com/search/repositories?q=%E5%8F%B0%E8%82%A1+AI&sort=stars); [GitHub search 台股 持股](https://api.github.com/search/repositories?q=%E5%8F%B0%E8%82%A1+%E6%8C%81%E8%82%A1&sort=stars)

### Inferences
- **Ranking for "Yahoo 股市 + AI analyst + my positions" with Taiwan in mind:**
  1. DSA is the only large, active project that has both a real holdings ledger and first-class `.TW/.TWO` analysis. It is the best base today. Gaps: TWD portfolio valuation, Taiwan market review, LINE push, a Traditional Chinese UI, and Taiwan broker CSV parsers.
  2. PanWatch has the best UX and holdings-centric AI. Adding Taiwan would mean writing a new market-data provider (its stack is akshare-oriented) plus calendar and settlement rules.
  3. A Western tracker (Wealthfolio, with its Traditional Chinese UI and red-up/green-down option, or Ghostfolio/Investbrain) plus MCP plus a Taiwan data MCP. This is the "assemble it yourself" route.
  4. go-stock is excellent for A-share research but unsuitable for Taiwan, and its holdings tracking is thin.
- Taiwan support in the Chinese-community projects almost always rides on **yfinance** (`.TW`/`.TWO`), as in DSA. Projects built on AkShare, Tushare, Eastmoney or 通达信 (go-stock, PanWatch, easy-stock, aiagents-stock) would need a new provider layer such as yfinance, FinMind or the TWSE/TPEx OpenAPI. A broker-API route (e.g. Futu) does not cover Taiwan.
- None of the main projects ships LINE notifications. DSA and PanWatch both support custom webhooks (and DSA supports ntfy/Gotify/Pushover), so a LINE Messaging API bridge is a small adapter rather than a core change.
- Valuation bands (PE/PB river charts, as on Yahoo 股市 or 財報狗) are not a documented feature of any all-in-one candidate. They would have to come from the data layer (e.g. FinMind PER/PBR datasets) or a separate tool.
- Licensing matters for a product built on these:
  - Clean permissive: DSA (MIT), PanWatch (MIT).
  - Copyleft: go-stock (GPL-3.0); Fincept, Wealthfolio, Sure and Ghostfolio (AGPL-3.0).
  - Non-commercial or proprietary parts: Investbrain (CC BY-NC); TradingAgents-CN app/frontend (proprietary); QuantDinger frontend (source-available).
  - No license, so legally not reusable: aiagents-stock, tw_stock_intel.

### Gaps
- I could not open the DSA, PanWatch or go-stock UIs to confirm chart depth (e.g. Yahoo-style technical overlays) or whether the DSA portfolio page actually computes TWD P&L correctly for `.TW` positions. The doc only says "partial valuation."
- PanWatch's exact data providers (beyond the `akshare` topic tag) and its exact LLM list are not spelled out in the README excerpt I read.
- Sure's securities price provider (Maybe used Synth before shutting down) was not confirmed, so `.TW` pricing in Sure is unknown.
- Fincept Terminal's Taiwan coverage and whether its portfolio module prices `.TW` tickers were not verified.
- Wealthfolio's official AI docs (wealthfolio.app) were unreachable from this environment. The supported-provider list (e.g. Ollama) is inferred from "local model or your own API key" in the README and the release notes naming Claude, GPT and Gemini.
- Release dates for DSA (it ships via Docker and Actions rather than tagged releases) and ValueCell's last release were not retrieved.

---

## Q2. Integration patterns: how do people wire an AI layer onto a portfolio tracker (MCP servers, APIs, add-ons)?

### Takeaway
By late 2026 the dominant pattern is **MCP**, and most trackers now ship it natively:
- Ghostfolio (experimental `ENABLE_FEATURE_MCP`, since v3.59.1 on 2026-08-23)
- Wealthfolio ("AI Agent Access", v3.10–3.11)
- Sure (`/mcp` with OAuth 2.0 + DCR)
- Investbrain (`/mcp` with OAuth)

Each lets Claude (web, desktop, Code), ChatGPT developer mode or Cursor read holdings and, if allowed, write transactions. Third-party MCP wrappers fill the remaining gaps: mhajder/ghostfolio-mcp adds a read-only mode, and pp-mcp reads Portfolio Performance `.portfolio` files. For Taiwan, you pair the tracker's MCP with a market-data MCP in the same client:
- twjackysu/TWSEMCPServer (186★)
- the official FinMind/FinMind-MCP (`uvx finmind-mcp`)
- Gratia2533/pipe-stock-analysis (FinMind + Finnhub)
- yfinance MCPs

The lighter fallbacks are Ghostfolio's "Copy AI prompt to clipboard" and REST APIs (DSA's `/api/v1/portfolio/*`). I found no official n8n or Open WebUI integration for any of these trackers.

### Cited Findings

**Built-in MCP servers in trackers**
- **Ghostfolio**:
  - Setting `ENABLE_FEATURE_MCP=true` "Enables the server of the Model Context Protocol (MCP) at `/mcp` (experimental)". The endpoint "accepts only requests to the host name of" `ROOT_URL`.
  - Clients use `POST <ROOT_URL>/mcp` with `Authorization: Bearer <MCP access token>`, created under My Ghostfolio → Access.
  - Permission levels: "Restricted view" reads the portfolio without monetary values; "View" includes values; "Restricted view and manage" and "View and manage" also allow importing activities and updating cash balances.
  - Source: [Ghostfolio README](https://github.com/ghostfolio/ghostfolio)
- Ghostfolio's MCP timeline, from the changelog:
  - 3.59.1 (2026-08-23): first server, with a get-holdings tool.
  - Later additions: activities, accounts, an import-activities tool, watchlist, asset-profile search, performance (3.78.0, 2026-10-03), ISIN in holdings (3.87.0, 2026-10-17), and a cash-balance update tool.
  - 3.91.0 (2026-10-23): "Refined the MCP server instructions based on the user's subscription."
  - 3.99.0 (2026-11-07): OAuth 2.1 discovery endpoints.
  - Source: [CHANGELOG](https://github.com/ghostfolio/ghostfolio/blob/main/CHANGELOG.md)
- Ghostfolio's other AI features:
  - "Copy AI prompt to clipboard" on the analysis page (2.133.1, 2025-01-09), plus a Duck.ai link (2.138.0, 2025-02-08).
  - "Extended the AI service by an access to OpenRouter" (2.175.0, 2025-06-28).
  - A dedicated OpenRouter engine for the `web_fetch` tool (3.62.0, 2026-08-27).
  - "Ghostfolio AI" activity import from CSV, JPEG, PDF or PNG (`POST api/v1/ai/activities`, 3.84.2, 2026-10-11, experimental).
  - All are marked experimental.
  - Source: [CHANGELOG](https://github.com/ghostfolio/ghostfolio/blob/main/CHANGELOG.md); [GitHub issue #4943 "Setup up AI SDK with OpenRouter community provider"](https://github.com/ghostfolio/ghostfolio/issues/4943)
- **Wealthfolio**: v3.11.0 "AI Agent Access has ready-to-copy setup for Claude Code, Codex and the ChatGPT desktop app, Cursor and other MCP apps". v3.12.0 adds spending permissions for agents and lets agents delete or void activities — [Releases](https://github.com/wealthfolio/wealthfolio/releases)
- Community Wealthfolio MCPs predate the built-in one: datamoc/WFmcp, toomy1992/wealthfolio-mcp, SamLyuubc/wealthfolio-mcp and wirux/mcp-wealthfolio (npm, read-only by default). Each has 0–1★. The Glama listing for toomy1992's server says it became obsolete "With Wealthfolio 3.0 build in AI" — [GitHub search](https://api.github.com/search/repositories?q=wealthfolio+mcp); [Glama listing](https://glama.ai/mcp/servers/@toomy1992/wealthfolio-mcp/blob/bff801df203898718a380ba2fa79fe9b052a1828/AGENTS.md)
- **Sure**:
  - "Sure includes a Model Context Protocol (MCP) server endpoint that allows external AI assistants like Claude.ai, Claude Desktop, GPT agents, or custom AI clients to query and act on your financial data."
  - Two auth modes: OAuth 2.0 with dynamic client registration (`/.well-known/oauth-*`, `POST /register`), or a static `MCP_API_TOKEN` + `MCP_USER_EMAIL`.
  - The docs warn that write tools (statement import, transaction and budget updates) are exposed.
  - Source: [docs/hosting/mcp.md](https://github.com/we-promise/sure/blob/main/docs/hosting/mcp.md); [docs/clients.md](https://github.com/we-promise/sure/blob/main/docs/clients.md)
  - Open issues show a `get_holdings` MCP tool exists, plus pending work on trade recording via MCP and read-only MCP authorization — [issue #4472](https://github.com/we-promise/sure/issues/4472); [issue #4725](https://github.com/we-promise/sure/issues/4725); [issue #4628](https://github.com/we-promise/sure/issues/4628)
- **Investbrain**:
  - The built-in MCP server lets an assistant "Read your profile, portfolios, transactions, and holdings; Create, update, and delete portfolios and transactions; … Look up current market data for any symbol."
  - Endpoint is `<APP_URL>/mcp` with OAuth. Hosted assistants (Claude web/desktop/mobile, ChatGPT) need a public HTTPS instance; local clients (Claude Code, Cursor, VS Code) can use `http://localhost:8000/mcp`.
  - Setup recipes: a Claude "Add custom connector," `claude mcp add --transport http investbrain …`, and ChatGPT developer mode.
  - Source: [docs/mcp.md](https://github.com/investbrainapp/investbrain/blob/main/docs/mcp.md); [self-hosting.md](https://github.com/investbrainapp/investbrain/blob/main/docs/self-hosting.md)
- **QuantDinger** exposes an Agent Gateway (`/api/agent/v1`) and an MCP server so Cursor, Claude Code and Codex can call approved tools "without receiving broker credentials or administrator JWTs" — [README](https://github.com/OpenByteInc/QuantDinger)
- **go-stock** acts as an MCP *client*. It mounts external MCP servers ("MCP 扩展", "MCP 服务器 OAuth 2.1 浏览器授权", DeepAgents "ToolSearch 动态工具检索"), and an open issue asks for preset MCP services — [dev README](https://github.com/ArvinLovegood/go-stock/blob/dev/README.md); [issue #191](https://github.com/ArvinLovegood/go-stock/issues/191)

**Third-party MCP wrappers for trackers**
- **mhajder/ghostfolio-mcp**: 22★, AGPL-3.0, last push 2026-11-09. Published on PyPI (`uvx ghostfolio-mcp`), GHCR and the official MCP Registry. Covers read and write with a configurable **read-only mode**, tag-based tool filtering, and Bearer or OIDC/OAuth for HTTP transports — [README](https://github.com/mhajder/ghostfolio-mcp); [GitHub API](https://api.github.com/search/repositories?q=ghostfolio+mcp)
- ANPC86/ghostfolio-nas-setup (1★, MIT, last push 2026-10-29) is a recipe: "Self-host Ghostfolio on a home NAS, load a sample portfolio, and connect an MCP server for AI assistants" — [GitHub API](https://api.github.com/search/repositories?q=ghostfolio+mcp)
- **Portfolio Performance**: Nokke32/pp-mcp (10★, MIT, last push 2026-11-07) is "A read-only MCP server that provides filtered account and portfolio data from one or more Portfolio Performance `.portfolio` files". It values holdings, computes realized and unrealized gains (FIFO or moving average), runs `simulate_sale`, and supports AES-encrypted files — [README](https://github.com/Nokke32/pp-mcp). A second option, dds-org/pp-mcp (2★, Apache-2.0), reads PP XML files — [GitHub API](https://api.github.com/search/repositories?q=portfolio+performance+mcp)
- **Sure**: adaofeliz/sure-mcp (0★, MIT) wraps the Sure API, but the built-in MCP makes it largely redundant — [GitHub API](https://api.github.com/search/repositories?q=sure+finance+mcp)
- **Standalone MCP with its own portfolio store**: wshobson/maverick-mcp (724★, MIT, last push 2026-11-09) is a "Stock market MCP server for Yahoo Finance data, technical analysis, portfolio tracking, and Python backtesting." It can "Record positions, calculate average cost and profit or loss, review risk, manage watchlists, and keep a trade journal." v1.2.1 has 38 core tools — [README](https://github.com/wshobson/maverick-mcp)
- LuxAlgo/broker-sdk (35★, MIT) offers "One normalized API for brokers & exchanges: accounts, positions…" for apps and AI agents — [GitHub API](https://api.github.com/search/repositories?q=portfolio+performance+mcp)

**Market-data MCP servers (to pair with a holdings MCP), with a Taiwan focus**
- **twjackysu/TWSEMCPServer**: 186★, MIT, last push 2026-10-22. Wraps the TWSE OpenAPI plus some real-time quotes, TPEx and TAIFEX OpenAPIs. Covers 三大法人, financial statements, ESG, margin and Put/Call. Example prompts are in Traditional Chinese ("三大法人今天買超哪些股票？") — [README](https://github.com/twjackysu/TWSEMCPServer); [GitHub API](https://api.github.com/search/repositories?q=twse+mcp)
- **FinMind/FinMind-MCP** (official): 5★, Apache-2.0, last push 2026-10-31. "FinMind 官方 MCP server… 75+ 種台股、期權、總經與全球金融資料." Install with `uvx finmind-mcp` and a `FINMIND_TOKEN`. The repo also ships an OpenAPI Action schema for a FinMind Custom GPT that shares the same knowledge pack — [README](https://github.com/FinMind/FinMind-MCP)
- **Gratia2533/pipe-stock-analysis**: 24★, MIT. "Self-hostable, read-only financial-market MCP… for Taiwan-listed securities and global stocks" using FinMind (anonymous access allowed) and Finnhub keys. Has a zh-TW README — [README](https://github.com/Gratia2533/pipe-stock-analysis)
- **kevinlin49361128-stack/stock-analyzer-mcp**: 10★, MIT shim. 95 tools with deep TWSE/TPEx, 三大法人 and monthly-revenue coverage, but the tools only work while the **closed-source** Stock Analyzer macOS app runs locally: "the analysis engine + market data + license-gated features live in the closed-source desktop app" — [README](https://github.com/kevinlin49361128-stack/stock-analyzer-mcp)
- Smaller Taiwan MCPs:
  - sacahan/CasualMarket (34★, last push 2025-12-07)
  - clsung/tw-stock-agent (16★, last push 2025-08-23, stale)
  - pyang2045/twsemcp (7★, last push 2025-08-16, stale)
  - taux-io/twse-mcp (3★)
  - asgard-ai-platform/mcp-tdcc (TDCC custody data)
  - Blave-TW/blave-quant-skill (42★, Taiwan stock and futures data skill)
  - heubme2020/datasinking (full-text financial reports including Taiwan, 22★)
  - Source: [GitHub search twse mcp](https://api.github.com/search/repositories?q=twse+mcp); [GitHub search taiwan stock mcp](https://api.github.com/search/repositories?q=taiwan+stock+mcp)
- Generic yfinance MCPs (Yahoo covers `.TW`/`.TWO`):
  - Alex2Yang97/yahoo-finance-mcp (368★)
  - narumiruna/yfinance-mcp (209★)
  - danishashko/yahoo-finance-mcp (24★)
  - Chinese-market: openstockdata/stock-data-mcp (multi-source A/HK/US/crypto with failover), jadenmong/akshare-mcp-server
  - Source: [GitHub search yfinance mcp](https://api.github.com/search/repositories?q=yfinance+mcp&sort=stars); [GitHub search 持股 AI](https://api.github.com/search/repositories?q=%E6%8C%81%E8%82%A1+AI&sort=stars)
- Hosted marketplaces (e.g. Vinkius) also list Ghostfolio MCP servers. These are third-party marketing pages, not official — [Vinkius listing](https://vinkius.com/apps/ghostfolio-investment-tracker-mcp)

**Non-MCP glue**
- **REST and holdings-as-watchlist feeds.** DSA exposes portfolio REST endpoints and can turn real Futu holdings into its analysis list (`--portfolio futu`). An external tracker's holdings can also be passed in as `STOCK_LIST` or `--stocks` — [full-guide.md](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/full-guide.md). PanWatch launches TradingAgents analysis directly from a holding row — [README](https://github.com/TNT-Likely/PanWatch)
- **Embedding an agent into a tracker fork.** Search found community/bootcamp-style Ghostfolio forks that embed LangGraph/FastAPI agents calling the Ghostfolio REST API with the user's bearer token. One design doc notes Ghostfolio already integrates the Vercel AI SDK and the OpenRouter provider. These are unofficial (a self-hosted Gitea fork) — [Ghostfolio agent fork AGENT_README](https://git.tp7.ddnss.de/topaLE/ghostfolio/raw/commit/1879169f345324a62007c852a4aae11da77593c1/AGENT_README.md)
- **n8n.** No Ghostfolio, Wealthfolio or Sure n8n node was found. Generic n8n templates instead read the portfolio from Google Sheets and send AI analysis by email or Discord. Per the search snippet, the n8n template analyzes a portfolio daily with Google Sheets, RSS, Groq and Gmail; I did not open it — [n8n template](https://n8n.io/workflows/15670); [growwstacks blog](https://growwstacks.com/blog/automate-financial-news-portfolio-tracking-n8n-ai/)

### Inferences
- The practical "AI layer on a tracker" recipe for a Taiwan investor in 2026:
  1. Run a tracker with a native MCP (Wealthfolio desktop, or Ghostfolio, Sure or Investbrain self-hosted).
  2. Add a Taiwan data MCP (TWSEMCPServer and/or FinMind-MCP).
  3. Add a yfinance MCP for US/global names.
  4. Connect all of them in one client (Claude Desktop/Code, ChatGPT developer mode, Cursor).
  
  The LLM then joins "my positions" with 三大法人, monthly revenue and PER/PBR from the Taiwan MCPs. This gives AI portfolio diagnosis without any all-in-one app.
- Hosted assistants (Claude.ai, ChatGPT) need the tracker's MCP reachable over public HTTPS with OAuth (Investbrain and Sure document this explicitly; Ghostfolio added OAuth 2.1 discovery on 2026-11-07). Local clients (Claude Code, Cursor) can use localhost. Privacy-conscious users should prefer local clients, read-only scopes (Ghostfolio "Restricted view", the mhajder read-only mode, the pp-mcp read-only design) and local LLMs.
- The mhajder/ghostfolio-mcp wrapper still adds value next to the built-in server: it is non-experimental, has a read-only switch and OIDC, and is in the MCP Registry. Built-in servers are evolving fast and are flagged experimental.
- go-stock's MCP-client capability means it could, in principle, gain Taiwan data by mounting TWSEMCPServer or FinMind-MCP. Its core quote/K-line UI would still lack Taiwan tickers.
- Ghostfolio's "Copy AI prompt" plus Duck.ai is the zero-infrastructure option: no API key, but manual and with no live data.

### Gaps
- I found no first-party docs or guides for **Open WebUI** connecting to Ghostfolio, Wealthfolio, Sure or Investbrain MCP servers (e.g. via an MCP-to-OpenAPI proxy). This is unverified.
- I found no published guide that combines Ghostfolio (or any tracker) with **TradingAgents** specifically. PanWatch's built-in "TradingAgents from a holding" is the only productized version found.
- I did not verify whether Ghostfolio's built-in MCP is available on self-hosted instances without Premium. The 3.91.0 note about "the user's subscription" suggests behavior varies by plan.
- Wealthfolio's official AI/MCP documentation pages (wealthfolio.app) were unreachable, so the tool list and permission model are taken from release notes only.
- Glama, Smithery and mcp.so registry pages for finance were not systematically crawled. Discovery relied on GitHub search, so low-star or non-GitHub servers may be missing.

---

## Q3. Which of these projects show genuine evidence of Taiwan users (issues, discussions, Traditional Chinese content)?

### Takeaway
**daily_stock_analysis** has the clearest Taiwan-user evidence:
- A Traditional Chinese feature request on 2026-11-10 asking for a 台股 market review. The maintainer's bot triaged it and linked a PR.
- A community issue (2026-06-24) that led to the TWSE/TPEx 三大法人 data layer.
- A Traditional Chinese README and a zh-TW how-to blog.

**Wealthfolio** shows product-level signals (a Traditional Chinese UI since v3.8.0 and a "red up, green down" option naming Taiwan) but no Taiwan-specific issues. go-stock, PanWatch, ValueCell and QuantDinger show **no** Taiwan-user evidence: no Taiwan issues and no Taiwan market support. The real Taiwan activity lives in small Traditional-Chinese-native repos (EquiLens, 台股情報站, FinPilot, StackWorth) and in Taiwan MCP servers (TWSEMCPServer, FinMind-MCP, pipe-stock-analysis).

### Cited Findings
- DSA issue #2482 (opened 2026-11-10 by vincentnet0313, in Traditional Chinese: "如標題,台股僅能分析個股與ETF, 大盤復盤能否增加台股選項"). An OpenReview bot replied in Simplified Chinese and linked PR #2489 — [issue #2482](https://github.com/ZhuLinsen/daily_stock_analysis/issues/2482)
- DSA issue #1777 (2026-06-24, by WenyuChiou): "[Feature] 台股三大法人买卖超（个股）— 离岸市场首个 heavy 数据块，基于免费官方 TWSE/TPEx OpenAPI". It is closed, and the shipped TwInstitutionalFetcher is documented in market-support.md — [issue #1777](https://github.com/ZhuLinsen/daily_stock_analysis/issues/1777); [market-support.md](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/market-support.md)
- DSA has a 繁體中文 README ("股票智能分析系統") — [README_CHT.md](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/README_CHT.md). A zh-TW blog guide is titled "daily_stock_analysis 怎麼用：用 LLM 做多市場股票分析和自動推送" (2026-06-22) — [knightli.com](https://knightli.com/zh-tw/2026/06/22/daily-stock-analysis-llm-stock-dashboard-guide/)
- A GitHub issue search for "台股" in the DSA repo returns 84 issues, though many match incidentally, e.g. roadmap issues — [GitHub issue search](https://github.com/ZhuLinsen/daily_stock_analysis/issues?q=%E5%8F%B0%E8%82%A1)
- Wealthfolio v3.8.0 added Traditional Chinese. v3.12.0's "Red up, green down" option matches "the convention used in China, Taiwan, South Korea and Japan" — [Releases](https://github.com/wealthfolio/wealthfolio/releases). An issue search for "TWD" surfaced only generic multi-currency bugs (e.g. #1473, #1414), none Taiwan-specific — [issue #1473](https://github.com/wealthfolio/wealthfolio/issues/1473)
- Ghostfolio: an issue search for "Taiwan" returns one result, #6202 "Ghostfolio in Chinese" (closed, 2026-01-17). I did not open it to check the Traditional/Simplified context — [issue #6202](https://github.com/ghostfolio/ghostfolio/issues/6202)
- go-stock: 0 issues for "台湾". Results for "台股" are unrelated (feature requests, model errors) — [GitHub issue search](https://github.com/ArvinLovegood/go-stock/issues?q=%E5%8F%B0%E8%82%A1). The pinyin/繁简 mapping in the changelog exists to match HK names like 恒生銀行, not Taiwan — [dev README](https://github.com/ArvinLovegood/go-stock/blob/dev/README.md)
- PanWatch: the two "台股"-matching issues are generic (#258, #103) — [issue #258](https://github.com/TNT-Likely/PanWatch/issues/258). ValueCell has 0 issues matching "taiwan" — [GitHub issue search](https://github.com/ValueCell-ai/valuecell/issues?q=taiwan). QuantDinger's "台股" matches are unrelated (#168, #134, #117) — [issue #134](https://github.com/OpenByteInc/QuantDinger/issues/134)
- Taiwan-native activity:
  - EquiLens UI is "shown in Traditional Chinese" and uses FinMind and Fugle (富果) — [README](https://github.com/wakin61043/tw-trading-dashboard)
  - 台股情報站 is written fully in Traditional Chinese — [README](https://github.com/JauWei/tw_stock_intel)
  - FinPilot is in Traditional Chinese with FinMind/FinLab — [README](https://github.com/hu0937/FinPilot)
  - TWSEMCPServer uses Traditional Chinese prompts — [README](https://github.com/twjackysu/TWSEMCPServer)
  - FinMind-MCP is official from FinMind (a Taiwan data vendor) — [README](https://github.com/FinMind/FinMind-MCP)
  - pipe-stock-analysis has a zh-TW README — [README](https://github.com/Gratia2533/pipe-stock-analysis)
  - Search also surfaced Taiwan broker-API agent skills, e.g. "讓 AI 更懂凱基 SuperPy API" (pypysuper-og/kgi-superpy-tw, 3★) — [GitHub search 台股 AI](https://api.github.com/search/repositories?q=%E5%8F%B0%E8%82%A1+AI&sort=stars)
- Several big Chinese projects publish Traditional Chinese READMEs (ValueCell, QuantDinger, Fincept Terminal). That is localization, not evidence of Taiwan users — [ValueCell README](https://github.com/ValueCell-ai/valuecell); [QuantDinger README](https://github.com/OpenByteInc/QuantDinger); [Fincept README](https://github.com/Fincept-Corporation/FinceptTerminal)

### Inferences
- Among large Chinese-community all-in-ones, DSA is the only one where Taiwan users are filing issues and getting features merged, such as 三大法人. That makes it the most promising base for a Taiwan-adapted fork or upstream contributions. The obvious next upstream asks are a Taiwan market review, TWD portfolio valuation, Taiwan broker CSV parsers (e.g. 元大/富邦/永豐 statements) and LINE push.
- Taiwan developers mostly build small, single-maintainer, Traditional-Chinese-native tools around FinMind, Fugle and TWSE OpenAPI. They are not adopting go-stock, PanWatch or ValueCell. The Taiwan ecosystem's strength is in data MCPs, which fits the "tracker + MCP" assembly pattern from Q2.

### Gaps
- PTT (Stock board), Mobile01, iThome and Medium were not searched directly. Web search returned no Traditional Chinese reviews of go-stock, PanWatch, Wealthfolio or Ghostfolio + AI, so community usage there is unconfirmed rather than disproven.
- The author location of knightli.com (a zh-TW localized post) and the nationality of DSA issue authors are not verifiable. "Taiwan user" is inferred from Traditional Chinese script and Taiwan-specific terms (大盤復盤, 三大法人).
- I did not check whether Wealthfolio's or Ghostfolio's Yahoo-based pricing handles `.TWO` (TPEx) tickers and TWD dividends correctly. The researchers covering those trackers should confirm.
