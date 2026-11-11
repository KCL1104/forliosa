# Taiwan-specific open-source stock projects and Taiwan market data sources (as of 2026-11-11)

*How this was researched: star counts, `pushed_at` (last push, used here as "last activity") and licenses come from the GitHub search API, run on 2026-11-11. The session's network blocked direct fetches of finmind.github.io, finmindtrade.com, openapi.twse.com.tw and developer.fugle.tw. Because of that, FinMind and Shioaji docs were read from the GitHub repos that build their doc sites: FinMind/FinMind.github.io at its 2026-11-08 commit, and Sinotrade/Sinotrade.github.io at its 2026-11-05 commit. TWSE OpenAPI endpoints were read from the swagger summary bundled in twjackysu/TWSEMCPServer. Fugle, MOPS, tax and broker facts not on GitHub came from web-search summaries and are marked as such.*

## Q-A: Which open-source projects are built specifically for Taiwan stocks (portfolio/庫存/績效 trackers, AI 台股分析, dashboards, screeners, LINE/Telegram bots, MCP servers)?

### Takeaway
The Taiwan ecosystem has many projects but few mature ones. The best-maintained and most-starred assets are data and AI-plumbing projects: FinMind ★2.9k, twstock ★1.5k, the TWSE MCP server ★186 and Shioaji Pro ★420. Taiwan-specific portfolio trackers are almost all solo projects with 0–2 stars. Even so, a few have rich, Taiwan-correct features: es94111/AssetPilot, maplestartend/twstock-research, wppypewo/StackWorth and DunkLiao/stock-ledger. None of them combines broker sync, Taiwan tax and fee handling, valuation bands and LLM analysis in one place.

### Cited Findings

**MCP servers (let Claude/ChatGPT query Taiwan market data)**
- **twjackysu/TWSEMCPServer**: ★186, last push 2026-10-22, MIT, Python 3.13+. The most complete Taiwan MCP server.
  - Data sources: the TWSE OpenAPI plus some real-time quotes, the TPEx OpenAPI, and TAIFEX.
  - MOPS: financial statements, cash flow, monthly revenue, multi-year dividends, investor conferences, major news, insider holdings and treasury buybacks. Covers listed, OTC, emerging and public companies.
  - TDCC: 集保 shareholding distribution, including a 13-week trend.
  - ETFs: premium/discount, holdings and unit changes.
  - Macro: business-cycle light signals, PMI and central-bank FX rates.
  - Deployment: a free hosted endpoint at `https://TW-Stock-MCP-Server.fastmcp.app/mcp` (streamable HTTP, sponsored by Prefect Horizon) with usage caps. For commercial or heavy use, the README recommends self-hosting via Docker. — [GitHub](https://github.com/twjackysu/TWSEMCPServer)
- **sacahan/CasualMarket**: ★34, last push 2025-12-07 (about 11 months idle), MIT. A FastMCP server with 23+ tools covering quotes, financial analysis, market info and **simulated trading**. Installs via `uvx`. Supports stdio for Claude Desktop and Docker+SSE. — [GitHub](https://github.com/sacahan/CasualMarket)
- **sacahan/CasualTrader**: ★14, last push 2025-12-05, no license. An AI trading-simulation platform you can watch live, built on the OpenAI Agents SDK plus MCP with 21 Taiwan-stock tools. — [GitHub](https://github.com/sacahan/CasualTrader)
- **taux-io/twse-mcp**: ★3, last push 2026-11-09, MIT, TypeScript.
  - A free hosted remote MCP server ("unofficial; not endorsed by TWSE").
  - Covers real-time quotes, PER, PBR, dividend yield, monthly revenue YoY, dividends, ex-dividend notices, margin and short balances, SBL availability, and the market-holiday calendar.
  - It notes that "證交所的公開資料只有最新一天", so it has saved daily closes itself since 2026-09-29. — [GitHub](https://github.com/taux-io/twse-mcp)
- **jiansoft/stock-mcp-go**: ★2, last push 2026-11-11, MIT, Go, Streamable HTTP. 74 tools covering quotes, financials, valuation and screening. Includes `get_dividend_history` (cash and stock dividends) and `get_upcoming_dividends` for current holdings. All tools are read-only except `set_portfolio_targets`. Supports HMAC API keys and an admin UI, and is backed by a separate `stock_rust` Data API. — [GitHub](https://github.com/jiansoft/stock-mcp-go)
- **Gratia2533/pipe-stock-analysis**: ★24, last push 2026-08-08, MIT. A self-hostable, read-only MCP server for Taiwan and global stocks: you supply your own FinMind token (anonymous access is possible at lower limits) and Finnhub key. Runs on Docker Compose with an OAuth-protected endpoint. — [GitHub](https://github.com/Gratia2533/pipe-stock-analysis)
- **fugle-dev/fugle-mcp-server**: ★10, last push 2026-10-23, MIT, TypeScript. The official Fugle MCP server. Provides quotes, history and optional **trading** through the **Taishin (台新) or Fubon (富邦)** SDK. Needs national ID, account password and certificate password. Available via `npx @fugle/mcp-server` or Docker. — [GitHub](https://github.com/fugle-dev/fugle-mcp-server)
- **fugle-dev/fugle-marketdata-mcp-server**: ★13, last push 2025-07-04. An older market-data-only MCP server. — [GitHub search](https://github.com/fugle-dev/fugle-marketdata-mcp-server)
- **Sinotrade/mcp-server-shioaji**: official SinoPac. Exposes Shioaji quotes, history and stock lists to AI assistants. Last push 2025-03-31, so stale. — [GitHub](https://github.com/Sinotrade/mcp-server-shioaji)
- **asgard-ai-platform/mcp-tdcc**: ★3, last push 2026-04-06, MIT, on PyPI as `mcp-tdcc` 0.1.0. Eight tools over TDCC open data: shareholding tiers, weekly and monthly custody changes, director holdings, and a generic query over 100+ endpoints. No API key needed. — [GitHub](https://github.com/asgard-ai-platform/mcp-tdcc)
- **Other MCP servers and skills**:
  - clsung/tw-stock-agent: ★16, MIT, **stale** (last push 2025-08-23, "under architecture refactor"). — [GitHub](https://github.com/clsung/tw-stock-agent)
  - pyang2045/twsemcp: ★7, **stale** (last push 2025-08-16). — [GitHub](https://github.com/pyang2045/twsemcp)
  - kevinlin49361128-stack/stock-analyzer-mcp: ★10, 81 tools, bundled with a macOS app. — [GitHub](https://github.com/kevinlin49361128-stack/stock-analyzer-mcp)
  - heubme2020/datasinking: ★22, financial reports from several countries including Taiwan as Markdown, via REST plus MCP. — [GitHub](https://github.com/heubme2020/datasinking)
  - Blave-TW/blave-quant-skill: ★42, last push 2026-11-10, Taiwan stock and futures data for agents. — [GitHub](https://github.com/Blave-TW/blave-quant-skill)
  - Tzuyuu0716/taiwan-stock-analysis: Claude Skill plus MCP covering listed, OTC and emerging stocks, including 集保. — [GitHub](https://github.com/Tzuyuu0716/taiwan-stock-analysis)
- **FinMind**: publishes `llms.txt` and `llms-full.txt` plus an "Agent Skill" tutorial so that Claude Code and similar agents can query its datasets. — [FinMind README](https://github.com/FinMind/FinMind)

**Portfolio / 庫存 / 績效 trackers (Taiwan-specific)**
- **es94111/AssetPilot**: ★1, last push 2026-11-06, **AGPL-3.0**, version 4.112.3. Self-hosted personal-asset platform (web plus Android) built with Next.js 16 and Node ≥24, deployed via Docker. The richest Taiwan-correct feature set found:
  - Prices and corporate actions: TWSE OpenAPI quotes, with TWSE/TPEx prices auto-refreshed during trading hours; **除權息 auto-sync**; dividend records carry both a cash and a **stock-dividend (股票股利)** field.
  - P&L: **FIFO full-precision per-lot P&L** using decimal.js.
  - Fees and tax: auto-computes **手續費 0.1425% with a NT$20 minimum** and **證交稅 0.3% (0.1% for ETFs and warrants)**, with manual override.
  - 定期定額 rolls forward when TWSE is closed; delisted stocks are frozen.
  - Security: DB encrypted with ChaCha20-Poly1305; login via Google, LINE or Passkey.
  - AI: **MCP OAuth 2.1**, so ChatGPT or Claude can connect to the ledger. — [GitHub](https://github.com/es94111/AssetPilot)
- **maplestartend/twstock-research**: ★2, last push 2026-06-20, MIT. A local, self-hosted stack (FastAPI on Python 3.12, Next.js 15 / React 19, SQLite).
  - Holdings: KPIs with intraday market value, **FIFO realized P&L**, an ATR stop and Chandelier exit, and Excel export.
  - Research: 除權息 calendar with yield estimates, multi-factor scoring, and dividend backtests.
  - AI: **optional Anthropic LLM narratives**.
  - Data: TWSE/TPEx OpenAPI, FinMind free tier, yfinance and MOPS. It deliberately ships no data files because of Yahoo's no-redistribution terms. — [GitHub](https://github.com/maplestartend/twstock-research)
- **wppypewo/portfolio-tracker (StackWorth)**: ★1, last push 2026-11-09, MIT, Next.js + Supabase.
  - Scope: US ETFs, Taiwan stocks, crypto and manual assets, all denominated in TWD.
  - Metrics: **XIRR and TWR** side by side; the XIRR solver validates its residual; drawdown is cashflow-adjusted.
  - Also has a decision journal, historical replay and attribution, and monthly reports.
  - Uses free-tier Twelve Data, FinMind and CoinGecko, and pins `Asia/Taipei` dates. — [GitHub](https://github.com/wppypewo/portfolio-tracker)
- **DunkLiao/stock-ledger**: ★0, last push 2026-06-23, no license, Next.js + SQLite.
  - Cost basis: **moving-average cost**.
  - Fees and tax: **configurable 手續費 discount** and 證交稅 at 0.3% for stocks or 0.1% for ETFs.
  - Dividends are credited to the settlement-account balance.
  - **Imports broker CSVs**; exports a monthly PDF report. — [GitHub](https://github.com/DunkLiao/stock-ledger)
- **kenshu528-oss/Stock-Portfolio-System**: ★1, last push 2026-11-11. React + Vite + Express. Multi-account, Yahoo Finance quotes, and dividend tracking that can adjust cost price. — [GitHub](https://github.com/kenshu528-oss/Stock-Portfolio-System)
- **WebberningMoney/tw-stock-portfolio-manager**: ★1, last push 2026-09-29, MIT. A Python Tkinter + SQLite macOS app using yfinance prices and a scraper for Yahoo TW dividend policy. — [GitHub](https://github.com/WebberningMoney/tw-stock-portfolio-manager)
- **haha1811/stock-journal**: last push 2026-05-14. Python + SQLite. Multi-account, inventory, a dividend calendar, and auto 0.3% tax on sells. — [GitHub](https://github.com/haha1811/stock-journal)
- **Other small trackers**:
  - chiefchkimo/portfolio-tracker: local; Taiwan/US quotes with Gemini analysis. — [GitHub](https://github.com/chiefchkimo/portfolio-tracker)
  - InchIK/DividendTracker: ★1, Taiwan stock and ETF dividends with ex-dates and payout schedules. — [GitHub](https://github.com/InchIK/DividendTracker)
  - changchiyou/stonks_everyday: ★2, Kotlin, an Android 台股記帳 widget. — [GitHub](https://github.com/changchiyou/stonks_everyday)
  - hanyu1017/TWStock: stale, last push 2025-11-21. — [GitHub](https://github.com/hanyu1017/TWStock)
  - jionghanhuang-ai/taiwan-stock-manager: stale, last push 2025-09-19. — [GitHub](https://github.com/jionghanhuang-ai/taiwan-stock-manager)
- **muzsor/twstock-calc**: MIT, last push 2026-10-19. A pure-front-end, offline PWA calculator rather than a tracker. Covers:
  - 手續費 discounts and a custom minimum.
  - 證交稅 at 0.3%, 0.1% (ETF) or 0.15% (day trading).
  - Short-borrow fees.
  - 除權息 reference price and 配股 share counts.
  - **二代健保 2.11%**, combining cash and par-value stock dividends against the NT$20,000 threshold.
  - **股利所得稅: combined vs separate** taxation comparison. — [GitHub](https://github.com/muzsor/twstock-calc)
- **Broker-sync tools**:
  - **joehwang/goldenegg-tw-holdings-cli**: ★0, last push 2026-07-28. A CLI that aggregates holdings from **富邦 (fubon_neo 2.2.8), 永豐 (shioaji), 玉山 (esun-trade) and 台新 Nova (taishin_sdk 1.0.2)** for AI agents. Runs on macOS ARM64 and needs each broker's API enablement and certificates. — [GitHub](https://github.com/joehwang/goldenegg-tw-holdings-cli)
  - **lulu930128/open-market-intelligence (OMI)**: ★62, last push 2026-11-06, Apache-2.0. A "Taiwan-first" local research workspace whose architecture diagram includes "Broker account: positions · cost · cash → Portfolio valuation". Also exposes MCP. — [GitHub](https://github.com/lulu930128/open-market-intelligence)

**AI analysis, dashboards and screeners**
- **wakin61043/tw-trading-dashboard (EquiLens)**: ★49, last push 2026-11-10, MIT. A self-hosted Taiwan trading dashboard on 127.0.0.1, plus a PWA reachable through a Cloudflare Tunnel. Features:
  - Four-factor research scores, a sector heatmap and an intraday radar.
  - **AI after-market report via Claude, OpenAI, Gemini or any OpenAI-compatible (local) endpoint**.
  - Data: TWSE/TPEx open data, FinMind (free or Sponsor) and Fugle WebSocket. Fugle subscription caps are 5 (Basic), 300 (Developer) and 2,000 (Advanced). — [GitHub](https://github.com/wakin61043/tw-trading-dashboard)
- **kerr20801/taiwan-stock-ai-analyzer**: ★51, last push 2026-10-24, MIT. Ensemble LSTM/XGBoost/LightGBM/RF/ARIMA with dynamic weights, pre-, intra- and post-market pipelines, **local Ollama LLM reports**, and Telegram push. Data from yfinance and twstock. — [GitHub](https://github.com/kerr20801/taiwan-stock-ai-analyzer)
- **kevin801221/stock-strategies-only**: ★138, last push 2026-09-26, MIT. A daily screening bot (fundamental, technical and backtest) that pushes to Telegram and runs free on GitHub Actions. — [GitHub](https://github.com/kevin801221/stock-strategies-only)
- **hu0937/FinPilot**: ★26, last push 2026-05-31, MIT. A Taiwan + US daily quant platform with Telegram, **Claude natural-language queries** and a strategy-research agent. Data from FinLab, FinMind and yfinance. — [GitHub](https://github.com/hu0937/FinPilot)
- **michaelbothsieh-crypto/tw-stock-health-dashboard**: ★5, last push 2026-09-26, MIT. A Next.js dashboard plus Telegram bot with a 3-tier LLM fallback: Groq Llama 3.3 70B, then Gemini 1.5 Flash, then rule-based. — [GitHub](https://github.com/michaelbothsieh-crypto/tw-stock-health-dashboard)
- **Other AI analysis and research projects**:
  - yangchunyi0814/ai-stock-report-generator: ★43. — [GitHub](https://github.com/yangchunyi0814/ai-stock-report-generator)
  - HenryLinyy/invest-committee: ★6, a Claude Code Agent Skill. — [GitHub](https://github.com/HenryLinyy/invest-committee)
  - herecomesmickey/taiwan-stock-ai-valuation: ★2, Claude scoring across 7 modules. — [GitHub](https://github.com/herecomesmickey/taiwan-stock-ai-valuation)
  - iadr-dev/Miru: Apache-2.0, a chat agent for Taiwan/US stocks. — [GitHub](https://github.com/iadr-dev/Miru)
  - box1401/stock-rag-agentic: LangGraph multi-agent. — [GitHub](https://github.com/box1401/stock-rag-agentic)
  - kimi0217/twse-report-rag: a local RAG over annual reports using pgvector and Ollama. — [GitHub](https://github.com/kimi0217/twse-report-rag)
- **Timeverse/My-TW-Coverage**: ★569, last push 2026-03-25, MIT. A research database of **1,735 TWSE+OTC companies across 99 sectors**, with supply-chain wikilinks (e.g. 207 companies in Apple's supply chain). Useful as LLM context. — [GitHub](https://github.com/Timeverse/My-TW-Coverage)
- **Sinotrade/shioaji-data**: last push 2026-11-10. SinoPac's official public dataset "for Shioaji and AI agents":
  - Company cards, customers and suppliers, industry chains and themes.
  - Daily market cap.
  - **Monthly revenue** (accumulated since 2023-10).
  - **Quarterly statements** (from 2023Q1).
  - Partly AI-compiled; served via a `manifest.json` with sha256 hashes. — [GitHub](https://github.com/Sinotrade/shioaji-data)
- **Sinotrade/shioaji-pro-app**: ★420, last push 2026-11-11, AGPL-3.0. A React 19 trading terminal over the Shioaji HTTP API + SSE. The UI is open source; the Tauri desktop shell, **AI agent** and backtest modules are proprietary downloads. — [GitHub](https://github.com/Sinotrade/shioaji-pro-app)
- Screeners:
  - xang1234/stock-screener: ★417, CANSLIM/Minervini, 12 markets including Taiwan. — [GitHub](https://github.com/xang1234/stock-screener)
  - carsonchou/tw-stock-radar: ★7, 1,800+ stocks with AI signals. — [GitHub](https://github.com/carsonchou/tw-stock-radar)
  - Yen60229/Taiwan_StockRadar: self-hosted, FastAPI + React + Docker. — [GitHub](https://github.com/Yen60229/Taiwan_StockRadar)
  - grissomlin/taiwan-stock-monitor: ★173, last push 2025-12-25. — [GitHub](https://github.com/grissomlin/taiwan-stock-monitor)

**LINE / Telegram bots**
- x3388638/tw-stock-telegram-bot: ★76, MIT, JS, **stale (last push 2024-08-21)**. — [GitHub](https://github.com/x3388638/tw-stock-telegram-bot)
- tbdavid2019/telegram-bot-stock2: ★12, AGPL-3.0, last push 2026-11-09. Taiwan/US quotes, K-line charts, Prophet forecasts and AI analysis. — [GitHub](https://github.com/tbdavid2019/telegram-bot-stock2)
- tian841224/stock-bot-golang: ★4, Telegram + LINE, Go + PostgreSQL. — [GitHub](https://github.com/tian841224/stock-bot-golang)
- terryuuang/TWSE_LINE_BOT: ★2, MIT, FastAPI LINE bot with AI Q&A. — [GitHub](https://github.com/terryuuang/TWSE_LINE_BOT)
- KCC6128/finance-linebot: a grounded RAG LINE bot over FinMind data and news with citations. — [GitHub](https://github.com/KCC6128/finance-linebot)

**Abandoned or legacy scrapers**
- toomore/grs: ★444, last push 2016-11-30. — [GitHub](https://github.com/toomore/grs)
- Asoul/tsrtc: ★462, last push 2017-08-10. — [GitHub](https://github.com/Asoul/tsrtc)
- Asoul/tsec: ★375, last push 2019-05-16. — [GitHub](https://github.com/Asoul/tsec)
- ch-lai/TWStock-Screener: last push 2019. — [GitHub](https://github.com/ch-lai/TWStock-Screener)

### Inferences
- No single Taiwan project combines all of the following: (1) broker auto-sync, (2) Taiwan-correct cost basis with 除權息, 配股, 零股, fees, 證交稅 and 二代健保, (3) PE/PB band valuation pages like Yahoo's, and (4) LLM analysis over holdings. The closest building blocks are:
  - AssetPilot for the ledger and its MCP hook.
  - goldenegg or Shioaji/Fubon SDKs for broker sync.
  - TWSEMCPServer or FinMind for data and AI tooling.
  - muzsor/twstock-calc as a reference for tax and fee formulas.
- AGPL-3.0 on AssetPilot, shioaji-pro-app and telegram-bot-stock2 matters if code is reused in a hosted platform. MIT or Apache projects are safer to fork.
- Star counts are a poor maturity signal here. AssetPilot (★1, v4.112) and StackWorth (★1, five CI gates) look more engineered than many higher-starred projects, but both are single-maintainer.

### Gaps
- Could not verify AssetPilot's handling of 配股 when computing cost basis (it records stock dividends, but the README does not say how they adjust cost), or whether any tracker models 二代健保 or 股利所得稅 within portfolio returns. Only the calculator does.
- Star counts for Sinotrade/mcp-server-shioaji were not captured. ArvinLovegood/go-stock (★8.1k, GPL-3.0) appeared in the "台股" search, but its Taiwan support was not verified; it is primarily China A-share focused.
- GitHub code search was not available because the token was invalid, so projects whose descriptions lack the search terms may have been missed.

## Q-B: Which data libraries and APIs supply Taiwan quotes, history, PER/PBR/yield, financial statements, monthly revenue, dividends, 三大法人, 融資融券, 集保 and news? What do they cost, what are the limits, and what are the terms?

### Takeaway
For a self-hosted platform, the practical stack is:
- Free government open data (TWSE/TPEx OpenAPI, which gives the latest day only, plus the TWSE/TPEx website JSON endpoints for history).
- FinMind for normalized history, including daily PER/PBR. The free tier allows 300–600 requests/hour; **commercial use requires Sponsor Pro at NT$3,330/month**.
- Fugle or a broker API (Shioaji, Fubon Neo) for real-time quotes.

MOPS is a moving target. It switched to a redesigned SPA on 2025-02-23, and the old site now lives at `mopsov.twse.com.tw`, slated for phased shutdown. yfinance is convenient but has data gaps and no redistribution rights.

### Cited Findings

**FinMind** (open-source SDK, Apache-2.0; ★2,882; PyPI `FinMind` 2.1.0 released 2026-10-24)
- Plans, priced in TWD and paid one-off with no auto-renewal:

  | Plan | Monthly | Yearly | API limit | Datasets |
  |---|---|---|---|---|
  | Free | free | free | **300 req/hr**, or **600 req/hr** when registered | 45 |
  | Backer | **NT$699** | NT$5,499 | 1,600 req/hr | 81 |
  | Sponsor | **NT$999** | NT$8,888 | 6,000 req/hr | 97 |
  | Sponsor Pro | **NT$3,330** | NT$29,620 | 20,000 req/hr | all, plus whole-day all-product download |

  — [FinMind Pricing](https://finmind.github.io/Pricing/)
- **Free tier includes:** 台灣股價資料表, **個股 PER/PBR 資料表 (TaiwanStockPER)**, 加權指數, margin and short, 三大法人 by stock, foreign holdings, SBL, the three financial statements, **股利政策表 and 除權除息結果表**, **月營收**, delisting and split reference prices, and **台股相關新聞 (TaiwanStockNews)**. — [FinMind Pricing](https://finmind.github.io/Pricing/)
- **Backer adds:** 還原股價 (`TaiwanStockPriceAdj`), tick history, weekly and monthly K, **股權持股分級表 (shareholding distribution)**, market value, industry chain, and whole-market single-date download. — [FinMind Pricing](https://finmind.github.io/Pricing/)
- **Sponsor adds:** minute K, broker branch (分點) data, **real-time snapshots**, and active-ETF daily holdings. — [FinMind Pricing](https://finmind.github.io/Pricing/)
- **License:**
  - Free, Backer and Sponsor are **non-commercial only**.
  - **SaaS, AI, app or internal-company use needs Sponsor Pro**.
  - Redistributing raw data, building a mirror API, or showing real-time data in public web/app UIs is **prohibited for every tier**.
  - Attribution to "FinMind" is required.
  - A suggested workaround for real-time and branch data: let end users enter their own Sponsor-level FinMind account. — [FinMind Pricing](https://finmind.github.io/Pricing/); [Commercial Use Q&A](https://finmind.github.io/CommercialUse/)
- Exceeding the quota returns HTTP 402 "Requests reach the upper limit". Usage can be checked at `GET https://api.web.finmindtrade.com/v2/user_info`. Repeated 4xx errors trigger a **30-minute IP ban** (403 "ip banned"). — [API usage](https://finmind.github.io/api_usage_count/); [Ban IP policy](https://finmind.github.io/BanIPPolicy/)
- There are 94 Taiwan datasets. `taiwan_stock_tick_snapshot` requires name, phone and address in the member center, and **returns 403 from 2027-01-31 if they are missing**. Intraday tables report volume in lots for TWSE/TPEx but in shares for 興櫃. — [FinMind llms.txt](https://finmind.github.io/llms.txt)

**twstock** (mlouielu/twstock; ★1,534; MIT; last push 2026-06-23; PyPI 1.5.1 released 2026-04-23)
- Fetches TWSE and TPEx prices and real-time quotes, and implements the "四大買賣點" signals. The README warns that **TWSE allows 3 requests per 5 seconds, beyond which you get banned**. — [GitHub](https://github.com/mlouielu/twstock)
- Open issues show fragility:
  - "Unable to obtain TPEX data" (#129, opened 2024-11-04, still open).
  - Related #130 and #131 (Nov 2024, closed).
  - "從2024/10/25後無法取得債卷ETF的歷史資料" (#132, open).
  - "Add 興櫃 fetching" (#155, opened 2026-04-22, open).
  
  — [twstock #129](https://github.com/mlouielu/twstock/issues/129); [#155](https://github.com/mlouielu/twstock/issues/155)
- Ports to other languages: chunkai1312/node-twstock (TS, MIT, last push 2026-05-10; exposes fields such as `stockDividendShares` 每仟股無償配股) and miles170/twstock-go (BSD-3, last push 2026-11-09). — [node-twstock](https://github.com/chunkai1312/node-twstock); [twstock-go](https://github.com/miles170/twstock-go)

**TWSE OpenAPI** (`openapi.twse.com.tw/v1`; Swagger at `/v1/swagger.json`)
- Free, under the Open Government Data license, updated daily. — [data.gov.tw dataset 11547](https://data.gov.tw/en/datasets/11547)
- 143 endpoints. Relevant ones:

  | Endpoint | Data |
  |---|---|
  | `/exchangeReport/BWIBBU_ALL` | 上市個股日本益比、殖利率及股價淨值比 |
  | `/exchangeReport/BWIBBU_d` | PER, yield and PBR by date |
  | `/exchangeReport/STOCK_DAY_ALL` | daily trading data |
  | `STOCK_DAY_AVG_ALL`, `FMSRFK_ALL`, `FMNPTK_ALL` | daily close with monthly average, monthly and yearly trading data |
  | `MI_INDEX` | market summary |
  | `/exchangeReport/TWT48U_ALL` | **除權除息預告表** |
  | `/opendata/t187ap45_L` | **股利分派情形** |
  | `/opendata/t187ap05_L`, `t187ap05_P` | **每月營業收入** (listed and public companies) |
  | `t187ap06_L_*`, `t187ap07_L_*` | 綜合損益表 and 資產負債表, by industry type |
  | `t187ap14_L` | EPS by industry |
  | `t187ap17_L` | 營益分析 |
  | `t187ap03_L` | 公司基本資料 |
  | `t187ap04_L` | 每日重大訊息 |
  | `MI_MARGN` | 融資融券餘額 |
  | `MI_QFIIS_*` | 外資持股 |
  | `TWT53U` | 零股行情 |
  | `TWTB4U` | 當沖標的 |
  | `SBL/TWT96U` | 可借券賣出 |
  | `holidaySchedule` | market holidays |

  — [TWSE swagger summary (via TWSEMCPServer)](https://github.com/twjackysu/TWSEMCPServer/blob/master/staticFiles/swagger_api_summary.json)
- **Per-stock 三大法人 (T86) is not in the OpenAPI list.** TWSEMCPServer fetches it from the website JSON endpoint `www.twse.com.tw/rwd/zh/fund/T86`. It also uses `/rwd/zh/afterTrading/BWIBBU_d`, `/exchangeReport/STOCK_DAY`, `/rwd/zh/marginTrading/TWT93U` and `/rwd/zh/exRight/TWT49U`, and the real-time `mis.twse.com.tw/stock/api/getStockInfo.jsp`. — [TWSEMCPServer source](https://github.com/twjackysu/TWSEMCPServer)
- OpenAPI data covers **only the latest trading day**, so history must come from the website endpoints or be archived yourself. — [taux-io/twse-mcp README](https://github.com/taux-io/twse-mcp)
- TWSEMCPServer throttles all `*.twse.com.tw` subdomains (openapi, www, mis, mops, mopsov) as a single site: "Subdomains of one exchange may sit behind the same IP-blocking firewall". Its default interval is 0.5 s. — [TWSEMCPServer utils/api_client.py](https://github.com/twjackysu/TWSEMCPServer)
- **PER method:** closing price ÷ EPS over the last four reported quarters (from MOPS). Not calculated when EPS is ≤ 0. — [TWSE BWIBBU page via search](https://www.twse.com.tw/zh/trading/historical/bwibbu.html)
- **Real-time and delayed data officially require a signed agreement and fees** with TWSE as an information vendor. The MIS endpoint is undocumented; community notes say it needs a session cookie and that over-polling can trigger blocks lasting hours. — [TWSE info-vendor FAQ](https://www.twse.com.tw/pcversion/en/page/products/info-vendor/faq.html); [Asoul/tsrtc](https://github.com/Asoul/tsrtc)

**TPEx (上櫃) OpenAPI** (`www.tpex.org.tw/openapi/`, `swagger.json`)
- Endpoints used in practice:
  - `tpex_mainboard_daily_close_quotes`
  - **`tpex_mainboard_peratio_analysis`** (上櫃 PER, yield, PBR)
  - `tpex_odd_stock`
  - `tpex_index`
  - `tpex_disposal_information`
  - `tpex_trading_warning_information`
  - `mopsfin_t187ap03_O`

  Website JSON endpoints used for history: `/www/zh-tw/afterTrading/peQryDate`, `/insti/dailyTrade` (三大法人), `/margin/balance`, `/bulletin/exDailyQ` (除權息) and `/ETF/list`. — [TWSEMCPServer source](https://github.com/twjackysu/TWSEMCPServer)
- The OTC PER/yield/PBR dataset fields are: date, code, name, 本益比, 每股股利, 殖利率, 股價淨值比. — [NCHC SciDM dataset](https://scidm.nchc.org.tw/en/dataset/best_wish17262); [data.gov.tw 11633](https://data.gov.tw/dataset/11633)

**MOPS 公開資訊觀測站**
- The redesigned MOPS took over `mops.twse.com.tw` on **2025-02-23**. The old site moved to **`mopsov.twse.com.tw`**, with a three-phase transition that ends by shutting `mopsov` off. Changes include RWD, a restructured menu and a function index, which breaks DOM-based scrapers. — [web-search summary of TWSE/CTEE notices](https://www.ctee.com.tw/news/20250113700198-439901); [TWSE UI/UX briefing PDF](https://dsp.twse.com.tw/public/static/downloads/computerPlanningOperationsDepartment/02-3【宣導議題】公開資訊觀測站UIUX優化_20241205174950.pdf)
- The new SPA uses a private JSON backend, `https://mops.twse.com.tw/mops/api/*`:
  - `t164sb03`, `t164sb04`, `t164sb05`: financial statements.
  - `t05st01`: major news.
  - It has "no public docs, so it can change without notice". TWSEMCPServer pins it with contract tests and keeps `mopsov.twse.com.tw/mops/web` as a legacy fallback. — [TWSEMCPServer tests/contract/test_mops_api.py](https://github.com/twjackysu/TWSEMCPServer)
- A 2025-03 iThome question reports Selenium scrapers on `mopsov` failing to read new pop-up windows. — [iThome Q&A](https://ithelp.ithome.com.tw/questions/10216990)

**TDCC 集保股權分散表**
- The open-data CSV (`getOD.ashx?id=1-5`) is updated after the last business day of each week and **keeps only the current week**. The per-stock query site offers about one year of history. — [iThome article](https://ithelp.ithome.com.tw/articles/10293719)
- Community archives: wirelessr/tdcc-opendata-archive (last push 2026-11-07) backs up the 1-5 dataset daily. TWSEMCPServer uses `opendata.tdcc.com.tw/getOD.ashx` and `www.tdcc.com.tw/portal/zh/smWeb/qryStock`. — [tdcc-opendata-archive](https://github.com/wirelessr/tdcc-opendata-archive); [TWSEMCPServer](https://github.com/twjackysu/TWSEMCPServer)

**Fugle 富果 MarketData API** (from web-search summaries of developer.fugle.tw)
- Plans:

  | Plan | Price | WebSocket | Intraday REST |
  |---|---|---|---|
  | **Basic** | free | **5 subscriptions** | not captured |
  | **Developer** | **NT$1,499/month** | 300 subscriptions, 2 connections | 600 req/min |
  | **Advanced** | **NT$2,999/month** | 2,000 subscriptions | 2,000 req/min |

  A subscription page lists **NT$2,599** for a tier instead, so the price is unconfirmed. Exceeding limits returns 429. — [Fugle pricing (search summary)](https://developer.fugle.tw/docs/pricing/); [EquiLens README for the Basic 5 cap](https://github.com/wakin61043/tw-trading-dashboard)
- REST endpoints are grouped as intraday, snapshot and historical under `api.fugle.tw/marketdata/v1.0/stock/`. WebSocket channels include trades, candles, books and aggregates. v0.3 was shut down on 2024-01-31. — [Fugle getting started](https://developer.fugle.tw/docs/data/http-api/getting-started)
- SDKs: `fugle-marketdata` for Python (2.8.0, released 2026-10-15, MIT), Node, and Go (`fugle-marketdata-go`). — [PyPI](https://pypi.org/project/fugle-marketdata/); [GitHub fugle-dev](https://github.com/fugle-dev/fugle-marketdata-python)
- **The Fugle trading API docs stopped being updated in 2025/11**; ordering moves to partner-broker SDKs. `fugle-trade` on PyPI was last released 2024-07-16. — [Fugle trading intro (search summary)](https://developer.fugle.tw/docs/trading/intro/)

**Shioaji 永豐金** (`shioaji` 1.7.11 on PyPI, released 2026-11-05; Sinotrade/Shioaji ★533)
- Python bindings over a C++/Rust core. rshioaji adds an **HTTP API + SSE server at localhost:8080**, giving access from JS/TS, Go, C/C++, C#, Rust and Java. Runs on Linux, macOS and Windows; Docker images are available. — [Shioaji docs](https://sinotrade.github.io/); [rshioaji](https://github.com/Sinotrade/rshioaji)
- **Daily traffic limits** for stocks (odd lots excluded), based on 30-day API turnover:

  | 30-day API turnover | Daily traffic cap |
  |---|---|
  | NT$0 | 500 MB |
  | NT$1 to NT$100M | 2 GB |
  | over NT$100M | 10 GB |

  — [Shioaji limits](https://sinotrade.github.io/zh/tutor/limit/)
- **Request limits:**
  - Market data (snapshots, ticks, kbars): 50 requests per 10 s; during the session, at most 10 `ticks` and 270 `kbars` calls.
  - Account queries: 25 per 5 s.
  - Orders: 250 per 10 s.
  - At most 200 subscriptions.
  - At most **5 connections per person_id**.
  - Subscription pushes do not count toward traffic. — [Shioaji limits](https://sinotrade.github.io/zh/tutor/limit/)
- **Onboarding:**
  - Requires a SinoPac bank account plus a securities account, opened as "DAWHO+大戶投".
  - API documents must be signed at the 簽署中心, separately for securities and futures.
  - A **test report in simulation mode** (login + place_order) must be completed before production access.
  - An API key is created with 2FA, an expiry date, an optional IP restriction, and scoped permissions: 行情/資料, **帳務 (account)**, 交易, 正式環境.
  - A CA certificate is loaded for orders.
  - No API fee was stated in the docs reviewed. — [Shioaji prepare/terms](https://sinotrade.github.io/zh/tutor/prepare/terms/); [token](https://sinotrade.github.io/zh/tutor/prepare/token/); [open_account](https://sinotrade.github.io/zh/tutor/prepare/open_account/)

**Other broker APIs**
- **Fubon Neo**: `fubon-neo` on PyPI, 2.3.1, first published there 2026-10-16. SDKs for Python, Node.js, C++, C# and Go. API-key login with per-function permissions (market data, orders, account). Requires a signed risk statement and a .pfx certificate. — [PyPI](https://pypi.org/project/fubon-neo/); [Fubon TradeAPI entry (via vocus note)](https://www.vocus.cc/article/672d8492fd89780001fdd134); [TaiwanNews on the Go SDK](https://www.taiwannews.com.tw/zh/news/6359399)
- **KGI SuperPy**: `kgisuperpy` 2.1.2, released 2026-09-22. Requires an account, accepting the terms, a token, and signing the 證券API風險預告書. — [PyPI](https://pypi.org/project/kgisuperpy/); [kgi-superpy-tw skill](https://github.com/pypysuper-og/kgi-superpy-tw)
- **Yuanta (元大) SPARK API**, per a secondary iThome comparison table:
  - Python and C# on Windows, macOS and Linux.
  - Quotes, orders (including cloud conditional orders), and accounts with inventory P&L.
  - No asset or volume threshold; requires a risk notice and an API test.
  - Older COM/Delphi/WPF components also exist. Not verified against official Yuanta docs. — [iThome article](https://ithelp.ithome.com.tw/articles/10405357)
- **E.SUN (玉山)**: `esun-trade` is not on PyPI; the wheel is downloaded from the broker. Certificate plus consent form; review takes 1–3 business days. — [E.SUN API prerequisites](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/prerequisites/); [goldenegg broker docs](https://github.com/joehwang/goldenegg-tw-holdings-cli)

**yfinance (.TW / .TWO)**: `yfinance` 1.8.0, released 2026-11-03, Apache-2.0
- Issue #2309: a missing trading day, **2025-02-20, for both 2330.TW and 1259.TWO**. — [yfinance #2309](https://github.com/ranaroussi/yfinance/issues/2309)
- Yahoo's "Close" is split-adjusted only; "Adj Close" also adjusts for dividends and capital-gain distributions. — [Yahoo history page for a .TWO ticker](https://ca.finance.yahoo.com/quote/715565.TWO/history/)
- maplestartend/twstock-research flags Yahoo's "不可重散布資料" legal constraint and ships no data. — [GitHub](https://github.com/maplestartend/twstock-research)

**TEJ** (commercial)
- The `tejapi` Python package (MIT client) was last released 2025-01-08. TEJ promotes a "免費試用版" of TEJ API and the TQuant Lab / zipline-tej backtesting stack (tejtw/TQuant-Lab ★94, MIT, last push 2026-09-01). **No public price list was found.** — [PyPI tejapi](https://pypi.org/project/tejapi/); [WelcomeToTejApi](https://github.com/tejtw/WelcomeToTejApi); [TQuant-Lab](https://github.com/tejtw/TQuant-Lab)

**News**
- **鉅亨網 (cnyes/Anue)**: an **unofficial**, undocumented JSON API at `api.cnyes.com/media/api/v1/` (e.g. `search/news?q=`), with no key needed according to a third-party skill page. Commercial feeds go through official cnyes partnerships; paid Apify scrapers also exist. — [search summary incl. Apify actor](https://apify.com/bakos_bence/anue-news.md); [cnyes about](https://www.cnyes.com/cnyes_about/cnyes_pas01.html)
- FinMind `TaiwanStockNews` is free-tier. — [FinMind Pricing](https://finmind.github.io/Pricing/)

**Goodinfo, CMoney and Histock scraping**
- Goodinfo has a ServiceTerms page. A web search did not surface explicit anti-scraping wording, but blocking by request rate is commonly reported. — [Goodinfo ServiceTerms](https://goodinfo.tw/tw/ServiceTerms.asp)
- Community Goodinfo scrapers are mostly small or stale, e.g. matthklo/twstockfilter (★39, last push 2025-01-15) and allenyummy/GoodInfo (last push 2021). — [twstockfilter](https://github.com/matthklo/twstockfilter)

**TWSE AI terms**
- TWSE publishes an "AI 服務條款". It governs TWSE's own AI and GenAI services (Q&A, summaries), not third-party scraping. — [TWSE aiuse](https://www.twse.com.tw/zh/terms/aiuse.html)

**Ready-made datasets**
- voidful/tw_stocker: ★198, last push 2026-07-16. A daily-updated Taiwan OHLCV CSV dataset with a SHA-256 manifest. — [GitHub](https://github.com/voidful/tw_stocker)
- catcat222222/twchips: ★74, MIT, not on PyPI. Pulls TAIFEX and TWSE institutional and margin data with no token. — [GitHub](https://github.com/catcat222222/twchips)

### Inferences
- **Yahoo-style PE/PB band (河流圖) pages** can be built from:
  - daily PER/PBR history: FinMind `TaiwanStockPER` (free), TWSE `BWIBBU_d` or website `/rwd/zh/afterTrading/BWIBBU_d`, and TPEx `peQryDate`.
  - trailing-4Q EPS and book value per share: FinMind statements or the MOPS API.

  Because TWSE does not compute PER when EPS ≤ 0, bands will have gaps for loss-making firms.
- For a self-hosted single-user deployment, FinMind's free or Sponsor tier is allowed for personal use. Hosting it as a multi-user or SaaS product means Sponsor Pro, or users bringing their own tokens. Real-time data cannot be rendered to the public at any tier.
- TWSE "free" real-time scraping via MIS sits in a gray zone: official real-time and delayed data are licensed. Broker APIs such as Shioaji, Fubon and Fugle, which give account holders real-time data, are the legitimate route.

### Gaps
- Could not read the full TPEx swagger or confirm TPEx OpenAPI rate limits.
- No official TWSE OpenAPI rate limit was found. Only community guidance exists: 3 requests per 5 s per twstock, 0.5 s per TWSEMCPServer.
- Fugle pricing is inconsistent (NT$2,999 vs NT$2,599), and the Basic tier's REST rate limit and Fugle's historical depth were not captured.
- No TEJ, CMoney or Histock pricing or terms were found. The Yuanta SPARK details come from a secondary source.
- The exact date `mopsov` will be decommissioned was not confirmed.

## Q-C: Can broker APIs (Shioaji, Fugle, Fubon Neo and others) pull actual positions (庫存) and realized P&L automatically?

### Takeaway
Yes. Every major Taiwan broker API exposes holdings, and most also expose realized P&L, so automatic sync is technically feasible:
- **Shioaji**: `list_positions`, including odd lots, and `list_profit_loss`.
- **Fubon Neo**: `inventories`, `unrealized_gains_and_loses` and `realized_gains_and_loses` (plus a summary call).
- **KGI**: `InventorySum`, `Inventory` and `RealizePL`.
- **E.SUN**: `get_inventories`.
- **Taishin Nova**: `accounting.inventories`.

The friction is onboarding (per-broker certificates, risk-disclosure signing, sometimes Windows-only tools) and per-broker SDKs. Fugle no longer offers its own trading API path.

### Cited Findings
- **Shioaji: unrealized positions.**
  - `api.list_positions(account, unit=Unit.Common | Unit.Share)` returns `StockPosition` with code, direction, quantity, average price, last price and pnl.
  - `Unit.Share` returns **零股 (odd-lot)** positions.
  - The same call is available via the CLI (`shioaji portfolio positions --unit share`) and via HTTP (`POST /api/v1/portfolio/position_unit`). — [Shioaji 未實現損益](https://sinotrade.github.io/zh/tutor/accounting/position/)
- **Shioaji: realized P&L and other account data.**
  - `api.list_profit_loss(account, begin_date, end_date)` returns per-trade rows with pnl, date, dseq, price and pr_ratio.
  - Other account endpoints: `list_profit_loss_detail`, `account_balance`, `list_settlements` and `margin`.
  - All account queries share a limit of 25 per 5 s. — [Shioaji 已實現損益](https://sinotrade.github.io/zh/tutor/accounting/profit_loss/); [Shioaji limits](https://sinotrade.github.io/zh/tutor/limit/)
- **Fubon Neo (Python):**
  - Holdings and P&L: `accounting.inventories` (庫存查詢), `unrealized_gains_and_loses`, `realized_gains_and_loses` and `realized_gains_and_loses_summary`.
  - Cash and margin: `bank_remain`, `query_settlement` and `maintenance`.
  - Futures and options: `close_position_record` and `query_hybrid_position`. — [Fubon Neo docs index (via neoapi-skill llms.txt)](https://github.com/phenomenoner/neoapi-skill); [Fubon Inventories doc](https://www.fbs.com.tw/TradeAPI/docs/trading/library/python/accountManagement/Inventories.txt)
- **Fubon Neo in practice.** goldenegg merges `sdk.accounting.inventories(acc)` with `sdk.accounting.unrealized_gains_and_loses(acc)` to get cost price and unrealized P&L. Its sample output includes `today_qty`, `tradable_qty` and a separate `odd` (零股) sub-object. — [goldenegg broker/fubon/client.py](https://github.com/joehwang/goldenegg-tw-holdings-cli)
- **KGI SuperPy:**
  - `Account.InventorySum("A"|"B")`: aggregate holdings in board lots or shares.
  - `Account.Inventory(FType=...)`: P&L and maintenance rate, with cash, margin, short and odd-lot breakdowns.
  - `Account.RealizePL("M"|"D", start, end)`: realized P&L, defaulting to the last 30 days. — [kgi-superpy-tw references/accounts.md](https://github.com/pypysuper-og/kgi-superpy-tw); [KGI InventorySum doc](https://superpy.kgieworld.com.tw/kgipythonapi/guide/tw/accountInventorySum)
- **E.SUN:** `sdk.get_inventories()`. **Taishin Nova:** `sdk.accounting.inventories(acc)` returning `position_summaries` with current_quantity, average_price, current_price and stock_evaluation. — [goldenegg broker/esun & broker/tssco](https://github.com/joehwang/goldenegg-tw-holdings-cli)
- **Onboarding friction:** every broker requires enabling API service, signing a 風險聲明書 or consent form, applying for and downloading a certificate, and obtaining keys. Some brokers do not activate immediately. — [goldenegg README](https://github.com/joehwang/goldenegg-tw-holdings-cli)
- **Shioaji supports read-only keys.** Its API keys can be limited to 行情 + 帳務 permissions, without 交易, and restricted by IP. That allows holdings sync without order rights. — [Shioaji token](https://sinotrade.github.io/zh/tutor/prepare/token/)
- **Fubon's certificate tool (TCEM) is Windows-only.** Mac and Linux users must generate the certificate on Windows and copy it over. — [fugle-mcp-server README](https://github.com/fugle-dev/fugle-mcp-server)
- **Fugle no longer offers its own trading path.** Its trading API docs froze in 2025/11 and point to partner brokers. Its MCP server now trades and queries through the Taishin or Fubon SDKs. — [Fugle trading intro (search summary)](https://developer.fugle.tw/docs/trading/intro/); [fugle-mcp-server](https://github.com/fugle-dev/fugle-mcp-server)
- **Yuanta SPARK** reportedly provides 帳務 and 庫存損益 queries (secondary source). — [iThome article](https://ithelp.ithome.com.tw/articles/10405357)

### Inferences
- A tracker could use broker APIs to reconcile current holdings and pull realized P&L. Full performance history (TWR/XIRR, dividends received) would still need a transaction ledger. The APIs reviewed expose positions and P&L windows, not a complete multi-year trade and dividend history. KGI's `RealizePL` defaults to 30 days, for example.
- Broker sync requires storing national ID, passwords and certificates. That is a strong reason for a self-hosted, local-only design: goldenegg is local CLI only, and EquiLens and OMI bind to 127.0.0.1.

### Gaps
- Could not confirm how far back each broker's realized-P&L query reaches, or whether any API exposes dividend receipts or 配股 credits.
- Yuanta's and Cathay's official API documentation was not reviewed.

## Q-D: Which Taiwan-specific accounting details matter for performance tracking (除權息, 配股, 零股, 手續費折扣, 證交稅, 二代健保, 股利所得稅), and which projects handle them?

### Takeaway
A Taiwan tracker must model:
- 手續費 at 0.1425% × the broker discount, with a minimum of typically NT$20, and as low as NT$1 for 盤中零股 at some brokers.
- 證交稅 on sells: 0.3% for stocks, 0.1% for ETFs, and 0.15% for day trades, with the day-trade rate extended to 2027-12-31.
- Cash and stock dividends: 配股 adds 0.1 share per NT$1 of stock dividend at the NT$10 par value.
- 二代健保 at 2.11% on any single dividend payment of NT$20,000 or more.
- Annual 股利所得稅: either combined with an 8.5% credit capped at NT$80,000, or separate at 28%.

Only AssetPilot (fees, tax, 除權息 sync, FIFO) and the muzsor calculator (every item, including 二代健保 and dividend tax) handle most of these. Other trackers implement only fees and 證交稅.

### Cited Findings
- **Fee rules:**
  - 手續費 is 0.1425% for both odd lots and board lots, with a NT$20 minimum at many brokers.
  - Some brokers cut the 盤中零股 minimum to NT$1: Yuanta and Cathay per a 2020 report, and Fubon and Cathay per Money101. Sources are from around 2020, so current schedules may differ.
  - 證交稅 is charged only on sells. — [TechNews](https://technews.tw/?p=662051); [Money101](https://www.money101.com.tw/blog/零股-交易時間-手續費-股票)
- **Day-trade 證交稅 at 0.15%:** the Legislative Yuan's third reading on 2024-12-31 extended the halved rate to **2027-12-31**. — [Focus Taiwan](https://focustaiwan.tw/business/202412310013); [Taipei Times](https://www.taipeitimes.com/News/biz/archives/2025/01/01/2003829438)
- **二代健保:** a 2.11% supplementary premium applies when a **single** dividend payment reaches NT$20,000. A reform to annual aggregation (non-wage income above NT$20,000 per year, withholding cap raised from NT$10M to NT$50M) was proposed for 2027 but the Executive Yuan **shelved it (暫緩)**. — [TVBS](https://news.tvbs.com.tw/politics/3037184); [money101 補充保費](https://www.money101.com.tw/blog/二代健保-補充保費-費率)
- **股利所得稅:**
  - Combined taxation: an 8.5% credit capped at **NT$80,000 per household**, refundable. Full credit applies up to about NT$941,176 of dividends.
  - Separate taxation: a flat 28% with no credit.
  - Rule of thumb: marginal rates of 20% or below favor combined; 30% or above favor separate. — [Money101 2026 guide](https://www.money101.com.tw/blog/所得稅-申報-股利課稅-計算-分開計稅-合併計稅-股票); [StockFeel](https://www.stockfeel.com.tw/股利所得稅-分離-合併/)
- **除權息 formulas, as implemented in muzsor/twstock-calc:**
  - Reference price = (pre-ex price − cash dividend) / (1 + stock dividend / 10).
  - Shares after 配股 = holdings × (1 + stock dividend / 10).
  - Fractional (畸零股) shares are paid in cash at par.
  - 二代健保 counts cash plus stock dividends at par toward the NT$20,000 threshold. — [twstock-calc](https://github.com/muzsor/twstock-calc)
- **Project coverage:**
  - **AssetPilot**: auto fee (0.1425%, NT$20 minimum) and tax (0.3% / 0.1%) with override, TWSE 除權息 auto-sync, cash and stock dividend fields, FIFO decimal.js P&L, and 定期定額 holiday roll-forward. — [AssetPilot](https://github.com/es94111/AssetPilot)
  - **DunkLiao/stock-ledger**: moving-average cost, configurable fee discount, tax at 0.3% or 0.1%, P&L with and without dividends, and broker CSV import. — [stock-ledger](https://github.com/DunkLiao/stock-ledger)
  - **maplestartend/twstock-research**: FIFO realized P&L, a 除權息 calendar, dividend backtests, and split data from FinMind. — [twstock-research](https://github.com/maplestartend/twstock-research)
  - **StackWorth**: XIRR, TWR and cashflow-adjusted drawdown, with dividends counted as income. — [StackWorth](https://github.com/wppypewo/portfolio-tracker)
  - **haha1811/stock-journal**: auto 0.3% tax only. — [stock-journal](https://github.com/haha1811/stock-journal)
  - **Mason0416/Strategy-System**: a backtester that models two-sided fees and the halved day-trade tax. — [GitHub](https://github.com/Mason0416/Strategy-System)
  - **ZXLlama/taiwan-trader-skills**: uses Decimal for fee and tax calculations in simulated trading. — [GitHub](https://github.com/ZXLlama/taiwan-trader-skills)
- **Data inputs for corporate actions:**
  - FinMind free tier: 股利政策表, 除權除息結果表, 減資恢復買賣參考價格, 分割後參考價 and 變更面額恢復買賣參考價格.
  - FinMind Backer: 還原股價. — [FinMind Pricing](https://finmind.github.io/Pricing/)
  - TWSE OpenAPI: `TWT48U_ALL` (除權除息預告表) and `t187ap45_L` (股利分派情形). — [TWSE swagger summary](https://github.com/twjackysu/TWSEMCPServer/blob/master/staticFiles/swagger_api_summary.json)
  - yfinance: "Adj Close" is dividend-adjusted, but it has had missing days for TW and TWO tickers. — [yfinance #2309](https://github.com/ranaroussi/yfinance/issues/2309)

### Inferences
- Odd lots matter for sync and for cost. Shioaji and Fubon return odd-lot positions separately (`Unit.Share`, the `odd` sub-object), so a tracker must merge board-lot and odd-lot positions. Odd-lot trades are also where minimum-fee assumptions (NT$1 vs NT$20) most distort returns.
- 二代健保 is charged per payment, not per year, so it should be deducted at dividend-receipt time. 股利所得稅 is an annual, household-level choice and is better shown as an estimated after-tax return than deducted per lot.
- Using adjusted prices (FinMind `TaiwanStockPriceAdj` or Yahoo Adj Close) for performance while separately recording dividends double-counts dividends. Trackers should use raw prices plus explicit dividend and 配股 events.

### Gaps
- No tracker was found that automatically applies 二代健保 or 股利所得稅 to portfolio performance. Only the calculator handles them.
- Current per-broker minimum fees and 零股 fee schedules for 2026 were not verified; sources are from around 2020.
- Whether the shelved 二代健保 annual-aggregation reform will be revived after November 2026 is unknown.
