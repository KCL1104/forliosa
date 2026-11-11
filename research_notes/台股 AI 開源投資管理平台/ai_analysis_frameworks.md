# Open-source AI / LLM stock-analysis frameworks: how usable they are for Taiwan stocks (TWSE/TPEx), as of 2026-11-11

How this was checked: on 2026-11-11 each repository was shallow-cloned through git, and its README, CHANGELOG, LICENSE and code were read and grepped for `.TW`, `Taiwan`, `TWSE`, `FinMind`, `zh-TW` and similar terms. Last-commit dates in these notes come from `git log -1` on the default branch. The session could not reach the GitHub REST API (`gh api` was refused with HTTP 403). Star and fork counts are therefore the rounded numbers shown on each GitHub page, fetched 2026-11-11, and are less precise than API counts. ithelp.ithome.com.tw and docs.openbb.co could not be resolved from this session, so iThome 鐵人賽 posts and the OpenBB docs could not be read.

---

## Q1. What does each project do (deep single-stock analysis, multi-agent debate, reports, backtesting, portfolio-level analysis, chat over data)?

### Takeaway
Only a few projects take a ticker and return a full LLM analyst report:
- **TradingAgents** and its forks
- **TradingAgents-CN**
- **FinRobot (Desktop/Equity)**
- **Dexter**

**ai-hedge-fund** has become a paper-trading and backtesting "fund OS". Several other projects are not single-stock report tools at all:
- **FinGPT**: models and fine-tuning.
- **FinRL**: reinforcement learning.
- **Qlib / RD-Agent**: quant factor and model research.
- **OpenBB ODP**: a data layer.
- **Fincept / ValueCell / AI-Trader**: terminals and platforms.

### Cited Findings

**TradingAgents (TauricResearch/TradingAgents)**
- **Pipeline.** Four analyst agents (Fundamentals, Sentiment, News, Technical) run in parallel. A bull researcher and a bear researcher debate their reports. A Trader turns the debate into a proposal, a Risk Management team assesses it, and a Portfolio Manager approves or rejects it. — [README](https://github.com/TauricResearch/TradingAgents/blob/main/README.md)
- **Sentiment Analyst.** It "aggregates news headlines, StockTwits, and Reddit chatter into a single sentiment read." — [README](https://github.com/TauricResearch/TradingAgents/blob/main/README.md)
- **Backtesting.** `run_backtest` runs the same pipeline over a grid of tickers and dates and scores decisions once their holding window has traded. — [README](https://github.com/TauricResearch/TradingAgents/blob/main/README.md)
- **Memory log.** A persistent log at `~/.tradingagents/memory/trading_memory.md` settles past decisions. It records raw return and alpha against the regional benchmark and writes a reflection that later runs read. — [README](https://github.com/TauricResearch/TradingAgents/blob/main/README.md)
- **Report formats.** Reports are saved as Markdown and HTML (`report_html.py`). — [repo tree](https://github.com/TauricResearch/TradingAgents/tree/main/tradingagents)
- **Paper.** arXiv 2412.20138. The paper claims better cumulative return, Sharpe ratio and maximum drawdown than baselines. — [arXiv](https://arxiv.org/pdf/2412.20138v6)
- **Trading-R1.** The same organisation announced Trading-R1 (a separate repo, early access, Nov 2026). — [README](https://github.com/TauricResearch/TradingAgents/blob/main/README.md)

**Mai0313/TradingAgents (Taiwan-oriented fork)**
- **Pipeline.** Analyst Team → "Situation Summariser" → Research Team → Trader → Risk Management → Portfolio Management.
- **Structured output.** The Risk Judge emits a `TradeRecommendation` with signal, size, target, stop, horizon, confidence and rationale.
- **Commands.** `tui`, `cli`, `reflect` and `backtest`. The backtest reports Sharpe, hit rate and drawdown.
- Source for all three points: [README](https://github.com/Mai0313/TradingAgents/blob/main/README.md)

**TradingAgents-CN (hsliuping)**
- **v3.0 "AI 助手" features:**
  - single-stock multi-agent debate research with 5 depth levels
  - natural-language screening over "6000+" stocks
  - a smart assistant with web search and tools
  - a Skill centre
  - paper trading (模拟交易) with review (复盘)
  - Source: [README](https://github.com/hsliuping/TradingAgents-CN/blob/v3.0/README.md)
- **Portfolio analysis.** The v3.0.0 changelog (2026-09-22) lists "组合分析：持仓组合的风险收益分析（VaR、压力测试、Brinson 归因等 20+ 工具）" among the features shared by the Community and Pro editions. — [CHANGELOG](https://github.com/hsliuping/TradingAgents-CN/blob/v3.0/CHANGELOG.md)
- **Pro-only features.** Scheduled and batch analysis, Word/PDF report export, Agent workshop, and a strategy/trading system. — [README](https://github.com/hsliuping/TradingAgents-CN/blob/v3.0/README.md)

**ai-hedge-fund (virattt), now the `aihf` package v2.7.2**
- **Rewrite.** The project is now a terminal app with two modes:
  - **Paper trading:** fake money, a hash-chained ledger in `~/.hedge-fund/paper/<name>/`, an approval step before trades, and a kill switch.
  - **Backtesting:** an equity curve against a benchmark.
  - Source: [README](https://github.com/virattt/ai-hedge-fund/blob/main/README.md)
- **Vision.** CIO allocator → strategy "pods" (value, event, macro) → master risk → execution → books. — [VISION.md](https://github.com/virattt/ai-hedge-fund/blob/main/VISION.md)
- **Shipped strategy files.** `deep-value`, `earnings-drift`, `fundamental-ls`, `inflections`. — [repo](https://github.com/virattt/ai-hedge-fund/tree/main/hedge_fund/strategies)
- **v1 personas still being ported.** The roadmap says the remaining v1 investor personas (the famous "Buffett/Munger…" agents) still need porting to v2. — [ROADMAP.md](https://github.com/virattt/ai-hedge-fund/blob/main/ROADMAP.md)
- **No live trading.** "The system does not actually make any trades." — [README](https://github.com/virattt/ai-hedge-fund/blob/main/README.md)

**Dexter (virattt)**
- **What it is.** An "autonomous financial research agent", described as "Think Claude Code, but built specifically for financial research". It does task planning, self-validation, loop detection and step limits. — [README](https://github.com/virattt/dexter/blob/main/README.md)
- **Data.** Income statements, balance sheets and cash-flow statements. — [README](https://github.com/virattt/dexter/blob/main/README.md)
- **Extras.** A WhatsApp gateway, cron jobs and skills such as `write-memo`. — [src tree](https://github.com/virattt/dexter/tree/main/src)
- **Mode of use.** Chat with data, aimed at Q&A and research memos rather than a fixed report template.

**FinRobot (AI4Finance-Foundation)**
- **Four generations:**
  - V0: AutoGen notebooks (`pip install finrobot`)
  - V1: `finrobot_equity`, a self-hosted web app that turns a ticker into an HTML/PDF equity-research report
  - V2: `finrobot_desktop`, the "Production" version (PydanticAI + FastAPI + React/Tauri)
  - V3: DeepSeek-Harness, in development
  - Source: [README](https://github.com/AI4Finance-Foundation/FinRobot/blob/master/README.md)
- **Desktop architecture.** A Lead Agent runs Data → Analysis → Modeling → Synthesis → Report sub-agents plus three debate agents. It produces a 13-chapter report with a 12-month target price and confidence level. — [README](https://github.com/AI4Finance-Foundation/FinRobot/blob/master/README.md)
- **Deterministic numbers.** DCF, DDM, LBO, WACC and comps come from pure-Python operators, not from the LLM ("deterministic compute, LLM narration"). — [README](https://github.com/AI4Finance-Foundation/FinRobot/blob/master/README.md)
- **Audit operators.** Six of them, including `currency_caliber` and `narrative_numeric_grounding`, check the narrative against the numbers. — [finrobot_desktop/README](https://github.com/AI4Finance-Foundation/FinRobot/blob/master/finrobot_desktop/README.md)
- **Skills.** 56 analyst playbooks. — [README](https://github.com/AI4Finance-Foundation/FinRobot/blob/master/README.md)

**FinGPT (AI4Finance-Foundation)**
- **Model project, not an agent app.** It publishes LoRA-fine-tuned financial LLMs (sentiment models v3.1–v3.3 on ChatGLM2-6B and Llama2-7B/13B), an instruction-tuning benchmark, and FinGPT-Forecaster.
- **Last "What's New" entry:** "Nov, 2023: FinGPT-Forecaster".
- Source: [README](https://github.com/AI4Finance-Foundation/FinGPT/blob/master/README.md)

**FinMem (pipiku915/FinMem-LLM-StockTrading)**
- A single-asset LLM trading agent with layered memory and character design. It is the code for arXiv 2311.13743 (ICLR 2024 workshop). The default config is TSLA, over the window 2022-06-30 to 2022-10-11. — [GitHub page](https://github.com/pipiku915/FinMem-LLM-StockTrading)

**FinRL (AI4Finance-Foundation)**
- A deep-reinforcement-learning trading library, not an LLM analyst. Sibling repos are FinRL-Meta (data and environments) and FinRL-Trading. — [AI4Finance org page](https://github.com/orgs/AI4Finance-Foundation/repositories?type=all&sort=stargazers)

**Microsoft Qlib**
- An AI quant research platform. It ships the Alpha158/Alpha360 factor sets for the US and China markets and builds its data from Yahoo Finance with crawler scripts. — [GitHub page](https://github.com/microsoft/qlib)

**Microsoft RD-Agent**
- RD-Agent(Q) automates factor and model research:
  - `fin_factor`: factor proposal/implementation loop
  - `fin_model`: model loop
  - `fin_quant`: both together
- It claims "approximately 2× higher ARR" than benchmark factor libraries with over 70% fewer factors, at a cost under $10.
- Source: [GitHub page](https://github.com/microsoft/RD-Agent)

**OpenBB**
- **ODP.** The "Open Data Platform by OpenBB (ODP)" is the open-source data-integration layer: "connect once, consume everywhere" into Python, OpenBB Workspace, Excel, MCP servers and REST APIs. — [README](https://github.com/OpenBB-finance/OpenBB/blob/develop/README.md)
- **Workspace.** OpenBB Workspace is the "enterprise UI for analysts to visualize datasets and leverage AI agents", hosted at pro.openbb.co. — [README](https://github.com/OpenBB-finance/OpenBB/blob/develop/README.md)

**ValueCell**
- Agents: DeepResearch (fundamental documents), Strategy (crypto auto-trading on Binance, Hyperliquid and OKX), and News Retrieval (scheduled news). — [README](https://github.com/ValueCell-ai/valuecell/blob/main/README.md)

**AI-Trader (HKUDS)**
- Now an "Agent-Native Trading Platform" at ai4trade.ai. External agents (Claude Code, Codex and others) register via a SKILL.md, share signals and debate. It has Polymarket paper trading and an experiment/challenge console. — [README](https://github.com/HKUDS/AI-Trader/blob/main/README.md)

**Fincept Terminal**
- A native C++20/Qt6 desktop terminal with embedded Python 3.11.
- **Analytics:** DCF, portfolio optimisation, VaR/Sharpe, derivatives, and an 18-module QuantLib suite.
- **AI:** "37 trader/investor, economic and geopolitics agents".
- Source: [README](https://github.com/Fincept-Corporation/FinceptTerminal/blob/main/README.md)

### Inferences
- If the goal is "give me a 台積電 research report", the realistic candidates are TradingAgents (or a fork), FinRobot Desktop and Dexter.
- If the goal is "quant signals on TW data", the candidates are Qlib + RD-Agent after building a custom data pipeline.
- FinGPT, FinMem and FinRL are research codebases and are not end-user analysis tools.

### Gaps
- No primary source was found that benchmarks any of these tools on Taiwan equities. No TW backtest results were found anywhere.
- iThome 鐵人賽 articles could not be read (host unreachable). One 2026 series on "基本面與技術面組合投資模型" describes a multi-agent scoring design, but its tie to TradingAgents or 台股 is unverified. — [search result](https://ithelp.ithome.com.tw/articles/10420896)

---

## Q2. Data sources, Taiwan ticker support out of the box (2330.TW, 2317.TW, 0050.TW, .TWO), Taiwan-specific issues/PRs/forks, and how hard it is to plug in FinMind or TWSE OpenAPI

### Takeaway
- **TradingAgents upstream** is the most Taiwan-ready. It accepts any Yahoo-suffixed ticker (`2330.TW`, `6488.TWO`), and since v0.5.2 it benchmarks `.TW`/`.TWO` against TAIEX (`^TWII`). All Taiwan data still flows through Yahoo Finance. Upstream did not merge the two community PRs that would have added a TWSE/TPEx data vendor or Taiwan-specific profiles.
- **Mai0313/TradingAgents** adds numeric-code lookup (`2330`), zh-TW output and Taiwan-locale Google News. It is archived and has 4 stars.
- **Mostly US-only data:** ai-hedge-fund, Dexter, FinGPT-Forecaster, FinMem and the financial-datasets MCP.
- **China-only data:** TradingAgents-CN v3 (Tushare/AkShare/BaoStock, A-shares only) and ValueCell.
- **Pluggable by design:** ai-hedge-fund (a `DataClient` protocol), TradingAgents (a vendor router), OpenBB (provider extensions) and Qlib (CSV → bin), which makes a FinMind/TWSE adapter feasible.

### Cited Findings

**TradingAgents upstream**
- **Data vendors:** `alpha_vantage`, `fred`, `polymarket`, `reddit`, `sec_edgar`, `stocktwits`, `yahoo`. There is no Taiwan vendor. — [dataflows/vendors](https://github.com/TauricResearch/TradingAgents/tree/main/tradingagents/dataflows/vendors)
- **Market coverage.** "TradingAgents works with any market Yahoo Finance covers, using the exchange-suffixed ticker. Company identity and the alpha benchmark resolve automatically per market." Listed examples include 0700.HK, 7203.T, AZN.L, .NS/.BO, .TO, .AX, .SS/.SZ. — [README](https://github.com/TauricResearch/TradingAgents/blob/main/README.md)
- **Taiwan benchmark mapping.** `default_config.py` maps `".TW": "^TWII"  # Taiwan (TAIEX)` and `".TWO": "^TWII"  # Taipei OTC (TPEx has no Yahoo index; TAIEX)`. Tests assert `("2330.TW", "^TWII"), ("6488.TWO", "^TWII")`. — [default_config.py](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/default_config.py); [tests/test_memory_log.py](https://github.com/TauricResearch/TradingAgents/blob/main/tests/test_memory_log.py)
- **Changelog.** v0.5.2 (2026-09-29): "Benchmarks for Taiwan, Korea, Singapore and the main European exchanges. (#1392)". — [CHANGELOG](https://github.com/TauricResearch/TradingAgents/blob/main/CHANGELOG.md)
- **Issue that prompted it.** Issue #1392, "benchmark_map missing .TW … non-US tickers silently scored against SPY", closed 2026-09-24. — [issue search](https://github.com/TauricResearch/TradingAgents/issues?q=taiwan)
- **Fundamentals are US-centred.** US statements come from SEC EDGAR, point-in-time. "Other companies' statements come from Yahoo Finance … a run dated in the past is told they are withheld, since Yahoo cannot say which figures were public." So a backtest or historical run on 2330.TW gets no fundamentals. — [README](https://github.com/TauricResearch/TradingAgents/blob/main/README.md)
- **PR #1159**, "Add Taiwan (TWSE/TPEx) data vendor via the twmd client". Opened 2026-07-21 by Anthonychiu1205 and closed 2026-09-24 with no merge shown.
  - It used the third-party `twmarketdata` package (twmarketdata.com).
  - It covered daily TWSE/TPEx prices, monthly revenue (月營收) and official statements. Sample tickers 2330, 2317, 2454, 0050 and 2603 worked without a key.
  - It excluded news and technical indicators.
  - No maintainer reason was shown.
  - Source: [PR #1159](https://github.com/TauricResearch/TradingAgents/pull/1159)
- **Issue #1156** asks whether a TWSE/TPEx vendor would be welcome. It is open with no maintainer reply. The author says yfinance "can price .TW symbols" but lacks monthly revenue disclosures and official financial statements. — [issue #1156](https://github.com/TauricResearch/TradingAgents/issues/1156)
- **PR #1348**, "Taiwan market foundation" by rita112025-cpu (2026-09-15). It proposed `^TWOII` for TPEx, a `market_profiles` module, and skipping StockTwits/Reddit for Taiwan tickers because "coverage is mostly empty or off-topic". It was closed without merge. The maintainer (Yijia-Xiao) commented: "Implemented in 47ac1f2: Taiwan tickers are measured against TAIEX." Only the benchmark part was adopted. — [PR #1348](https://github.com/TauricResearch/TradingAgents/pull/1348)
- **Conflict on the TPEx index.** Upstream code says TPEx has no Yahoo index and uses TAIEX for `.TWO`. PR #1348 proposed `^TWOII`. — [default_config.py](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/default_config.py) vs [PR #1348](https://github.com/TauricResearch/TradingAgents/pull/1348)

**Other TradingAgents forks**
- **Mai0313/TradingAgents** (Taiwan-oriented):
  - `TAIWAN_SUFFIXES = (".TW", ".TWO")`; bare codes such as `2330` and `8069` are resolved through Yahoo Finance Search.
  - yfinance supplies OHLCV, fundamentals, indicators, news, insider trades, analyst ratings, institutional holders, short interest and dividends.
  - The `.TW` suffix routes Google News RSS to `TW:zh-Hant` for local-language news.
  - Its code notes Yahoo reports financials "in the issuer's native currency (TWD for TWSE)".
  - Sources: [dataflows/tickers.py](https://github.com/Mai0313/TradingAgents/blob/main/src/tradingagents/dataflows/tickers.py); [README](https://github.com/Mai0313/TradingAgents/blob/main/README.md); [dataflows/yfinance.py](https://github.com/Mai0313/TradingAgents/blob/main/src/tradingagents/dataflows/yfinance.py)
- **simonlin1212's `tradingagents-astock`** (Docker image `birdxs/tradingagents-astock`) shows the regional-fork pattern: upstream US sources are swapped for mootdx + 东财 + 新浪 + 同花顺, with China-specific analyst roles added. — [Docker Hub](https://hub.docker.com/r/birdxs/tradingagents-astock) (search snippet only)
- **No FinMind-based fork found.** No TradingAgents fork using FinMind was found. A search for "FinMind TradingAgents fork Taiwan" returned none. — [search](https://pypi.org/project/tradingagents/0.5.0/)

**TradingAgents-CN**
- **v3.0 is A-share only:** "本系统仅支持 A 股市场研究". Data comes from Tushare, AKShare and BaoStock. — [README](https://github.com/hsliuping/TradingAgents-CN/blob/v3.0/README.md); [CHANGELOG](https://github.com/hsliuping/TradingAgents-CN/blob/v3.0/CHANGELOG.md)
- **Earlier versions were broader.** v1.0.1 (tag dated 2026-04-15) advertised "A股/港股/美股". The code still contains `HKStockProvider` and `OptimizedUSDataProvider` classes. No Taiwan code was found in a grep. — [v1.0.1 README](https://github.com/hsliuping/TradingAgents-CN/blob/v1.0.1/README.md)

**ai-hedge-fund**
- **Data source.** Financial Datasets (financialdatasets.ai) via API key, or x402 pay-per-call in USDC on Base ("last 365 days of data, non-professional use"). — [README](https://github.com/virattt/ai-hedge-fund/blob/main/README.md)
- **Pluggable data layer.** "Any class with these methods can be used as a data provider." The `DataClient` protocol has `get_prices`, `get_snapshot`, `get_financial_metrics`, and more. The docstring example is a `YFinanceClient`. Providers must be point-in-time and must raise on infrastructure failures. — [data/protocol.py](https://github.com/virattt/ai-hedge-fund/blob/main/hedge_fund/data/protocol.py)

**Dexter**
- Calls `api.financialdatasets.ai`, with optional Exa/Tavily/Perplexity/LangSearch web search. — [README](https://github.com/virattt/dexter/blob/main/README.md); [src](https://github.com/virattt/dexter/tree/main/src)

**FinRobot Desktop**
- Seven providers with failover: FMP, Finnhub, yfinance, SEC EDGAR, Adanos, NewsAggregator and FX. Each has a health state. — [README](https://github.com/AI4Finance-Foundation/FinRobot/blob/master/README.md); [finrobot_desktop/README](https://github.com/AI4Finance-Foundation/FinRobot/blob/master/finrobot_desktop/README.md)

**FinGPT-Forecaster**
- "Currently trained on US market data (DOW 30). For other markets (including China stock market), you would need to … fine-tune the model on the target market data." — [README](https://github.com/AI4Finance-Foundation/FinGPT/blob/master/README.md)

**OpenBB**
- **Providers in the `openbb` 5.0.0 metapackage:** bls, cboe, cftc, deribit, ecb, eia, famafrench, federal_reserve, finra, fred, government_us, imf, jodi, nasdaq, oecd, sec, tmx. yfinance and FMP are not among them. — [openbb_platform/pyproject.toml](https://github.com/OpenBB-finance/OpenBB/blob/develop/openbb_platform/pyproject.toml)
- **yfinance and FMP ship separately.** `openbb-yfinance` 2.1.0 (uploaded 2026-11-01) and `openbb-fmp` 1.6.1 (2026-05-26) are separate PyPI packages licensed `AGPL-3.0-only`. — [PyPI openbb-yfinance](https://pypi.org/project/openbb-yfinance/); [PyPI openbb-fmp](https://pypi.org/project/openbb-fmp/)
- **One extension per data source.** Each data source is its own extension (`pip install openbb-yfinance`). — [OpenBB docs (search snippet)](https://docs.openbb.co/platform/extensions/data_extensions)
- **No Taiwan provider.** No Taiwan/TWSE/TPEx path exists anywhere in the repo tree (grep of `git ls-tree`). — [repo](https://github.com/OpenBB-finance/OpenBB/tree/develop)

**Qlib**
- **Yahoo collector regions:** `["CN", "US", "BR"]` (default CN). There is no Taiwan collector. — [scripts/data_collector/yahoo/collector.py](https://github.com/microsoft/qlib/blob/main/scripts/data_collector/yahoo/collector.py)
- **Official data.** The official dataset is "disabled temporarily". Users are pointed to the community `chenditc/investment_data` dataset and to a guide for converting CSV into Qlib format. — [GitHub page](https://github.com/microsoft/qlib)

**ValueCell**
- "Cover US market, Crypto market, Hong Kong market, China market." Taiwan is not mentioned. Asian expansion beyond that (Nikkei) is roadmap-only. — [README](https://github.com/ValueCell-ai/valuecell/blob/main/README.md)

**AI-Trader**
- Alpha Vantage, with a yfinance fallback for US stock prices (2026-06-08 update). — [README](https://github.com/HKUDS/AI-Trader/blob/main/README.md)

**Fincept Terminal**
- "100+ connectors: FRED, IMF, World Bank, DBnomics, AkShare, Polygon, Kraken, Yahoo Finance, government APIs." Taiwan is not mentioned. — [README](https://github.com/Fincept-Corporation/FinceptTerminal/blob/main/README.md)

**MCP servers with Taiwan data**
- **pyang2045/twsemcp:** MIT; `npx twse-mcp`. Tool groups: Market Data (6), Financial Reports (6), Trading Analysis (3), Investment Research (7). It covers daily prices, TAIEX/sector indices, P/E, dividend yield, quarterly statements, foreign holdings, ETF rankings and holidays. It is TWSE only (no TPEx tools are listed). Last commit 2025-08-16, so it is stale. — [README](https://github.com/pyang2045/twsemcp); [LobeHub listing v1.1.0](https://lobehub.com/zh-TW/mcp/pyang2045-twsemcp)
- **FinMind/FinMind-MCP (official):** PyPI `finmind-mcp`, run with `uvx finmind-mcp`, needs a FinMind token. It exposes 75+ datasets (Taiwan stocks, options, macro, global data) to Claude Desktop, Claude Code, Gemini CLI, Cursor and Windsurf. Example prompts include "2330 institutional investor trading" and "TSMC monthly revenue". — [GitHub](https://github.com/FinMind/FinMind-MCP); [PyPI](https://pypi.org/project/finmind-mcp/)
- **"TWSE OpenAPI MCP Server" (unofficial, Glama):** TWSE plus TAIFEX data, added to Claude as a custom connector by URL. — [Glama](https://glama.ai/mcp/servers/gqck33kupd)

**General-purpose MCP servers (not Taiwan-specific)**
- **narumiruna/yfinance-mcp:** MIT; last commit 2026-11-08 (PR #188); about 135–149 stars per third-party directories. — [Enterprise DNA](https://enterprisedna.co/directories/mcp/narumiruna-yfinance-mcp); [Claude Marketplaces](https://claudemarketplaces.com/mcp/narumiruna/yfinance-mcp)
- **financial-datasets/mcp-server:** MIT; last commit 2025-06-05 (stale); backed by the same US-centric Financial Datasets API. — [repo](https://github.com/financial-datasets/mcp-server)

### Inferences
- **Upstream TradingAgents with `2330.TW`, `2317.TW`, `0050.TW` or `6488.TWO`:** it should run end-to-end today. Prices and technicals come from Yahoo; fundamentals come from Yahoo only for current-date runs; the news is mostly English Yahoo news; StockTwits/Reddit will be near-empty.
- **Data gaps in that setup.** The run is missing:
  - 月營收 (monthly revenue)
  - 三大法人 (institutional investor flows)
  - 融資融券 (margin trading data)
  - 集保 (TDCC custody data)
  - Chinese-language news
- **0050.TW (ETF).** It will get prices but little meaningful "fundamentals"; ETF-aware analysis is not built in.
- **Effort to add a FinMind/TWSE vendor.** Moderate, roughly a few hundred lines, in TradingAgents (vendor router plus tool functions) and ai-hedge-fund (implement `DataClient`). PR #1159 is a ready template. Its closure suggests upstream prefers regional vendors to live in forks or external packages; the issue #1156 question was never answered.
- **OpenBB.** Supports custom provider extensions (the repo has a `cookiecutter/` directory). A FinMind provider extension would expose Taiwan data to Python, REST, the MCP server and Workspace at once.
- **Qlib.** Needs a custom TW collector (FinMind/TWSE → CSV → `dump_bin`).

### Gaps
- The merge state of PR #1393 ("add Taiwan and seven other missing markets to benchmark_map", closed 2026-09-24) could not be confirmed. The behaviour exists upstream either way.
- PR #190 (Traditional Chinese CLI and multi-market, closed 2025-08-11) could not be inspected in detail.
- No GitHub API search for Taiwan forks could be run (API blocked), so other TW forks may exist.
- Whether FinRobot Desktop's yfinance/FX providers handle `.TW` tickers and TWD conversion correctly was not tested.
- Where `openbb-yfinance` is now developed (which repo) was not determined.

---

## Q3. Chinese-language output (especially Traditional Chinese 繁體中文) and Chinese news sentiment (鉅亨網, 經濟日報, MoneyDJ, PTT)

### Takeaway
- **Traditional-Chinese reports are possible but not first-class upstream.** TradingAgents takes a free-text output language, so "Traditional Chinese" can be typed as a custom language. Its built-in menu offers only "Chinese (中文)", and a PR adding a Traditional Chinese option was closed.
- **zh-TW by default** only in the archived Mai0313 fork.
- **Simplified Chinese:** TradingAgents-CN (Simplified UI, A-shares only).
- **`zh` output flag:** FinRobot Desktop has `--lang en|zh`.
- **Chinese news sentiment.** No project ships Taiwanese news sources (cnyes/鉅亨, 經濟日報, MoneyDJ, PTT Stock board) for sentiment. The closest is Mai0313's Google News RSS with `TW:zh-Hant` locale.

### Cited Findings
- **TradingAgents menu.** The CLI offers English, "Chinese (中文)", Japanese, Korean, Hindi, Spanish, Portuguese, French, German, Arabic, Russian, and "Custom language". The custom option takes free text. — [cli/prompts.py](https://github.com/TauricResearch/TradingAgents/blob/main/cli/prompts.py)
- **How TradingAgents applies the language.** It appends "Write your entire response in {lang}, except the labelled lines … ("**Rating**:" line, "FINAL TRANSACTION PROPOSAL:")" to every agent whose output reaches the report. The env var is `TRADINGAGENTS_OUTPUT_LANGUAGE`. Multi-language support arrived in v0.2.3 (2026-03-29). — [agents/context.py](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/context.py); [CHANGELOG](https://github.com/TauricResearch/TradingAgents/blob/main/CHANGELOG.md)
- **Closed Traditional Chinese PRs.**
  - PR #1534, "fix: add Traditional Chinese option and guard empty strategic actions", closed 2026-10-16.
  - PR #190, "Internationalize CLI to Traditional Chinese and add multi-marke[t]…", closed 2025-08-11.
  - Source: [issue/PR search](https://github.com/TauricResearch/TradingAgents/issues?q=taiwan)
- **Mai0313 fork.**
  - `response_language` defaults to `zh-TW` and also supports zh-CN, en-US, ja-JP, ko-KR and de-DE.
  - The `.TW`/`.TWO` suffix maps to news locale `("zh-TW", "TW", "TW:zh-Hant")`.
  - README.zh-TW.md exists.
  - Sources: [config.py](https://github.com/Mai0313/TradingAgents/blob/main/src/tradingagents/config.py); [dataflows/tickers.py](https://github.com/Mai0313/TradingAgents/blob/main/src/tradingagents/dataflows/tickers.py); [README](https://github.com/Mai0313/TradingAgents/blob/main/README.md)
- **Western social sources do not cover Taiwan.** PR #1348 says StockTwits/Reddit coverage for Taiwan tickers is "mostly empty or off-topic". — [PR #1348](https://github.com/TauricResearch/TradingAgents/pull/1348)
- **TradingAgents-CN.** README, UI and agent roles (大盘/板块/市场/基本面/新闻分析师, 乐观/审慎研究员) are in Simplified Chinese. — [README](https://github.com/hsliuping/TradingAgents-CN/blob/v3.0/README.md)
- **FinRobot Desktop.** CLI commands accept `--lang en|zh`. — [finrobot_desktop/README](https://github.com/AI4Finance-Foundation/FinRobot/blob/master/finrobot_desktop/README.md)
- **ValueCell.** Has a Traditional Chinese README (`README.zh_Hant.md`). Multi-language UI including Traditional Chinese is roadmap-only. — [README](https://github.com/ValueCell-ai/valuecell/blob/main/README.md)
- **FinGPT.** Its sentiment models are trained on English news and tweets. The README suggests "FinGPT v1.x models which were designed for Chinese markets" for China. — [README](https://github.com/AI4Finance-Foundation/FinGPT/blob/master/README.md)

### Inferences
- **Good 繁中 reports from upstream TradingAgents:** set `TRADINGAGENTS_OUTPUT_LANGUAGE="Traditional Chinese (Taiwan, 繁體中文)"`. Strong models (Claude, GPT-5.x, Gemini) follow this reliably. Weaker local models may drift into Simplified Chinese. This was not tested.
- **Taiwanese news and PTT sentiment** need a custom news vendor, for example:
  - cnyes or MoneyDJ RSS
  - Google News `TW:zh-Hant` as in Mai0313
  - PTT Stock board scraping
  - FinMind's news dataset (if available, via FinMind-MCP)

### Gaps
- No project with a built-in cnyes/經濟日報/MoneyDJ/PTT sentiment pipeline was found.
- Output quality of Traditional Chinese reports was not measured.

---

## Q4. LLM providers supported and approximate cost per analysis run

### Takeaway
- **Broadest provider support: TradingAgents.** It covers OpenAI, Anthropic, Google, xAI, DeepSeek, Qwen, GLM, MiniMax, Kimi, Mistral, Groq, NVIDIA, OpenRouter, Ollama, Azure, Bedrock, any OpenAI-compatible endpoint, and a ChatGPT Plus/Pro subscription.
- **Ollama/local models:** Dexter, Fincept, the Mai0313 fork and TradingAgents support them.
- **No Ollama yet:** ai-hedge-fund v2 ("Ollama next").
- **Per-run cost:** not documented officially by any project. Third-party estimates for one TradingAgents analysis range from about $0.20 to several dollars, depending on models and debate rounds.

### Cited Findings
- **TradingAgents providers.** OpenAI, Google, Anthropic, xAI, DeepSeek, Qwen (DashScope intl + CN), GLM (Zhipu intl + CN), MiniMax, OpenRouter, Mistral, Kimi, Groq, NVIDIA NIM, Ollama (local or remote), Azure OpenAI, AWS Bedrock and OpenAI-compatible endpoints (vLLM, LM Studio). — [README](https://github.com/TauricResearch/TradingAgents/blob/main/README.md)
- **TradingAgents model tiers.** A "quick" model serves analysts, researchers, debaters and the trader. A "deep" model serves the research and portfolio managers. Each tier can use a different provider. — [README](https://github.com/TauricResearch/TradingAgents/blob/main/README.md)
- **ChatGPT plan login.** v0.7.0 (2026-10-16) added a `chatgpt` provider that runs on a ChatGPT Plus/Pro plan instead of an API key. — [CHANGELOG](https://github.com/TauricResearch/TradingAgents/blob/main/CHANGELOG.md)
- **Mai0313 fork.**
  - Providers come from `langchain.chat_models.init_chat_model`: openai, anthropic, google_genai, xai, openrouter, ollama, huggingface, litellm.
  - One `reasoning_effort` knob is mapped to Anthropic `effort`, OpenAI `reasoning_effort` and Google `thinking_level`.
  - `tradingagents backtest` enforces `--budget-cap-usd` with token-aware cost tracking.
  - Source: [README](https://github.com/Mai0313/TradingAgents/blob/main/README.md)
- **TradingAgents-CN.** The README names OpenAI / DeepSeek / 通义千问 "等". Adapters exist for DashScope, DeepSeek, Google and OpenAI-compatible endpoints. — [README](https://github.com/hsliuping/TradingAgents-CN/blob/v3.0/README.md); [llm_adapters](https://github.com/hsliuping/TradingAgents-CN/tree/v3.0/tradingagents/llm_adapters)
- **ai-hedge-fund.** Anthropic, OpenAI, DeepSeek, Google, xAI, Kimi and TypeSafe (Jev). Ollama is "next — the free local path". — [README](https://github.com/virattt/ai-hedge-fund/blob/main/README.md); [ROADMAP](https://github.com/virattt/ai-hedge-fund/blob/main/ROADMAP.md)
- **Dexter.** Provider registry: openai, anthropic, google, xai, moonshot, deepseek, openrouter, ollama and ollama-cloud. A recent commit added Claude 5 thinking support. — [src/providers.ts](https://github.com/virattt/dexter/blob/main/src/providers.ts); [commits](https://github.com/virattt/dexter/commits/main)
- **FinRobot Desktop.** Bring your own key for DeepSeek, OpenAI or Anthropic (`--model anthropic:claude-sonnet-4-6`). — [finrobot_desktop/README](https://github.com/AI4Finance-Foundation/FinRobot/blob/master/finrobot_desktop/README.md)
- **ValueCell.** OpenRouter, SiliconFlow, Azure, OpenAI-compatible, Google, OpenAI and DeepSeek. — [README](https://github.com/ValueCell-ai/valuecell/blob/main/README.md)
- **Fincept.** OpenAI, Anthropic, Gemini, Groq, DeepSeek, OpenRouter and Ollama. — [README](https://github.com/Fincept-Corporation/FinceptTerminal/blob/main/README.md)
- **RD-Agent.** LiteLLM by default, plus OpenAI and Azure. DeepSeek is "experimental" and uses SiliconFlow for embeddings. It needs chat, JSON mode and embeddings. — [GitHub page](https://github.com/microsoft/RD-Agent)
- **FinMem.** OpenAI GPT-4, TGI-served Hugging Face models, and Gemini scripts. It always needs OpenAI `text-embedding-ada-002`. — [GitHub page](https://github.com/pipiku915/FinMem-LLM-StockTrading)
- **TradingAgents cost estimates (all third-party):**

  | Source | Estimate | Notes |
  |---|---|---|
  | [Railway deploy page](https://railway.com/deploy/trading-agents.md) | about $0.20–$0.80 per ticker | gpt-4o deep / gpt-4o-mini quick, one debate round; cost roughly doubles when debate rounds double |
  | [ToolBrain review 2026](https://toolbrain-astro.pages.dev/blog/tauric-tradingagents-review-2026/) | "$0.50–2.00 … per decision cycle" | on GPT-5.5 pricing |
  | DEV Community post ([link 1](https://dev.to/hassann/tradingagentsopen-source-llm-trading-framework-394e), [link 2](https://dev.to/_cbd692d476c5faf3b61bcf/tradingagentss-5-hidden-uses-that-90-of-quant-devs-miss-in-2026-2cn4)) | about $4 | 22-node deep run, GPT-5.5, 2 debate rounds; from a search snippet only, and which of the two posts said it was not verified |
  | [Apidog](https://apidog.com/blog/tradingagents-multi-agent-llm-trading/) | — | the bull/bear debate is "3-5x more expensive than the analysts" |
- **OpenBB Copilot.** The free Workspace Community plan includes 20 OpenBB Copilot queries per day. — [OpenBB pricing (search snippet)](https://openbb.co/pricing/)
- **RD-Agent cost claim.** "Cost under $10" for its reported factor results. — [GitHub page](https://github.com/microsoft/RD-Agent)
- **FinGPT fine-tuning cost.** Fine-tuning FinGPT v3.3 cost about $17.25 (17.25 hours on one RTX 3090). — [README](https://github.com/AI4Finance-Foundation/FinGPT/blob/master/README.md)

### Inferences
- **Cheap Taiwan-focused setup:** TradingAgents with DeepSeek or Qwen as the quick model and Claude or GPT as the deep model, with 1 debate round, probably costs well under US$1 per ticker per day.
- **Daily runs over a 20-stock Taiwan portfolio** at those estimates would cost roughly US$5–20 per day on frontier models. Most of the cost is in the debate rounds.

### Gaps
- No project publishes official per-run token counts.
- The figures above were not reproduced.

---

## Q5. Portfolio/holdings input and performance tracking: can the tool take a user's current positions and give portfolio-level advice?

### Takeaway
- **TradingAgents** is the only mainstream framework that formally accepts the user's book (cash, currency, positions with average price) and conditions the Trader, Risk team and Portfolio Manager on it. It still analyses one ticker per run.
- **TradingAgents-CN v3** adds portfolio risk analytics (VaR, stress tests, Brinson attribution), but only for A-shares.
- **ai-hedge-fund** tracks its own simulated fund's NAV and ledger, not the user's real holdings.
- **Fincept** offers portfolio optimisation and VaR analytics.
- **ValueCell** lists portfolio management as roadmap only.

### Cited Findings
- **TradingAgents "Current holdings."**
  - "Pass a portfolio to have the trader, the risk analysts and the portfolio manager work against your actual book."
  - Python: `PortfolioContext.model_validate({... "positions": [{"ticker": "NVDA", "quantity": 120, "average_price": 150.0}]})` then `ta.propagate("NVDA", "2026-09-01", portfolio=portfolio)`.
  - CLI: `tradingagents --portfolio my_book.json`.
  - "An empty positions list means a flat book, which is different from passing nothing."
  - Source: [README](https://github.com/TauricResearch/TradingAgents/blob/main/README.md)
- **TradingAgents data model.** `PortfolioContext` has `cash`, `currency` (a free label) and `positions[]` of `{ticker, quantity (signed), average_price}`. It is "broker-neutral by construction". — [tradingagents/portfolio.py](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/portfolio.py)
- **When it was added and fixed.** Portfolio-aware runs arrived in v0.5.0 (2026-09-18). v0.7.1 (2026-10-27) made holdings listed under a broker's spelling match the analysed instrument (#1556) and rejects non-finite numbers (#1509). — [README news](https://github.com/TauricResearch/TradingAgents/blob/main/README.md); [CHANGELOG](https://github.com/TauricResearch/TradingAgents/blob/main/CHANGELOG.md)
- **TradingAgents decision tracking.** The decision log settles realised return and alpha against the regional benchmark (TAIEX for `.TW`). This is a track record for the agent's calls, not a portfolio P&L tracker. — [README](https://github.com/TauricResearch/TradingAgents/blob/main/README.md)
- **TradingAgents-CN v3.0.** "组合分析：持仓组合的风险收益分析（VaR、压力测试、Brinson 归因等 20+ 工具）" and "模拟交易与操作复盘". v2.0 had added 持仓分析 (holdings analysis). — [CHANGELOG](https://github.com/hsliuping/TradingAgents-CN/blob/v3.0/CHANGELOG.md); [README](https://github.com/hsliuping/TradingAgents-CN/blob/v3.0/README.md)
- **ai-hedge-fund.** A paper fund keeps positions, decisions, orders, fills and NAV history in an append-only hash-chained ledger. Mandates "carry no tickers". — [ROADMAP](https://github.com/virattt/ai-hedge-fund/blob/main/ROADMAP.md); [README](https://github.com/virattt/ai-hedge-fund/blob/main/README.md)
- **Fincept.** The open build has "portfolio optimisation, VaR/Sharpe". "Portfolio Management" is an Enterprise module. — [README](https://github.com/Fincept-Corporation/FinceptTerminal/blob/main/README.md)
- **ValueCell.** Portfolio management (custom benchmarks, performance metrics, allocation targets) and scheduled portfolio summaries are roadmap items. — [README](https://github.com/ValueCell-ai/valuecell/blob/main/README.md)

### Inferences
- **Holdings-aware TradingAgents for Taiwan.** A tracker can export `{"cash": ..., "currency": "TWD", "positions": [{"ticker": "2330.TW", "quantity": 1000, "average_price": 1050}]}` and call TradingAgents once per holding. Each holding then gets a 加碼/減碼/續抱 recommendation with the rest of the book as context.
- **Whole-portfolio optimisation is not covered.** Rebalancing across 20 names would need an extra aggregation step, for example an LLM summariser over per-ticker reports, or a quant optimiser.

### Gaps
- It is unverified whether TradingAgents' Portfolio Manager prompt uses the other positions (sector concentration) or only the analysed ticker's position. `render()` leads with the analysed instrument; the rest was not read.

---

## Q6. UI and deployment (CLI, web UI, API, Docker)

### Takeaway
- **TradingAgents:** CLI + Python API + HTML reports + Docker, with no web UI.
- **TradingAgents-CN v3:** a full web app (FastAPI + Vue 3 + MongoDB + Redis). The app/frontend code is source-available, not open source.
- **FinRobot:** a Tauri desktop app (macOS) or a local web UI.
- **ai-hedge-fund and Dexter:** terminal apps.
- **Fincept:** a native desktop binary.
- **OpenBB:** a Python library, CLI, REST API (`openbb-api`) and MCP server, while the Workspace web UI is closed and hosted.

### Cited Findings
- **TradingAgents.**
  - Interactive CLI (`tradingagents`); flags such as `--ticker` and `--date` for unattended runs (v0.5.2).
  - Python `TradingAgentsGraph`.
  - Dockerfile + docker-compose with an Ollama profile.
  - A wheel attached to each GitHub release (v0.7.0).
  - Sources: [README](https://github.com/TauricResearch/TradingAgents/blob/main/README.md); [CHANGELOG](https://github.com/TauricResearch/TradingAgents/blob/main/CHANGELOG.md)
- **TradingAgents-CN v3.**
  - Needs Python 3.11, Node 18+, MongoDB 7.0+ and Redis 6+ installed separately.
  - FastAPI + Vue 3.
  - v1.0.x had migrated from Streamlit to FastAPI + Vue 3 and offered multi-arch Docker (amd64/arm64).
  - Sources: [README](https://github.com/hsliuping/TradingAgents-CN/blob/v3.0/README.md); [v1.0.1 README](https://github.com/hsliuping/TradingAgents-CN/blob/v1.0.1/README.md)
- **ai-hedge-fund.** `pipx install aihf` → `aihf` interactive TUI. — [README](https://github.com/virattt/ai-hedge-fund/blob/main/README.md)
- **Dexter.** Bun/TypeScript CLI; WhatsApp gateway. — [README](https://github.com/virattt/dexter/blob/main/README.md)
- **FinRobot.**
  - Desktop v0.1.0 for macOS Apple Silicon, not notarized.
  - `dev.sh` runs FastAPI on :8321 and Vite on :5173.
  - A CLI; V1 is a FastAPI web app producing HTML/PDF reports.
  - Hosted at finrobot.ai/v2.
  - Source: [README](https://github.com/AI4Finance-Foundation/FinRobot/blob/master/README.md)
- **OpenBB.** `pip install openbb`; ODP CLI; `openbb-api` serves FastAPI at 127.0.0.1:6900 for Workspace; `openbb-mcp-server` (`openbb-mcp`), with tool discovery to avoid token bloat. — [README](https://github.com/OpenBB-finance/OpenBB/blob/develop/README.md); [MCP README](https://github.com/OpenBB-finance/OpenBB/blob/develop/openbb_platform/extensions/mcp_server/README.md)
- **Fincept.** "Native C++20 · Qt6 · embedded Python 3.11 · single binary". — [README](https://github.com/Fincept-Corporation/FinceptTerminal/blob/main/README.md)
- **RD-Agent.** Needs Docker (without sudo); Linux only. — [GitHub page](https://github.com/microsoft/RD-Agent)
- **ValueCell.** One command launches frontend, backend and agents. A hosted A-share version runs at valuecell.ai. — [README](https://github.com/ValueCell-ai/valuecell/blob/main/README.md)

### Inferences
- **Self-hosted, automatable Taiwan pipeline (cron → reports):** TradingAgents (Docker + CLI flags + `--portfolio`) is the easiest base.
- **Chat UX:** the lowest-effort route is Claude Desktop/Code plus FinMind-MCP, twsemcp, yfinance-mcp and the OpenBB MCP server.

### Gaps
- None material.

---

## Q7. Project health as of November 2026: license, stars, last release/commit, activity, disclaimers

### Takeaway
- **Very active:** TradingAgents (weekly releases; 0.7.1 on 2026-10-27), ai-hedge-fund (2.7.2, commit 2026-11-09), OpenBB (commit 2026-11-11), Fincept (v4.5.2, 2026-11-09).
- **Stale or abandoned:** FinMem (last commit Aug 2024), financial-datasets MCP (Jun 2025), twsemcp (Aug 2025), ValueCell (Feb 2026), the Mai0313 fork (archived).
- **Two licence assumptions in the brief are out of date.** OpenBB's repo and core package are now Apache-2.0 (provider plugins such as `openbb-yfinance` remain AGPL), and FinRobot is Apache-2.0, not MIT.

### Cited Findings

Status table. Stars and forks are rounded GitHub page values; last commit is from `git log` on the default branch; all fetched 2026-11-11.

| Project | License | Stars / forks | Latest version / tag | Last commit | Status |
|---|---|---|---|---|---|
| [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) | Apache-2.0 | 122.0k / 23.4k | v0.7.1 (2026-10-27) | 2026-11-04 | Very active: v0.5.0→0.7.1 in 6 weeks |
| [Mai0313/TradingAgents](https://github.com/Mai0313/TradingAgents) | LICENSE file Apache-2.0; README says MIT | 4 / 1 | tag v0.7.0 | 2026-09-19 | **Archived** (read-only) |
| [hsliuping/TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN) | Hybrid: Apache-2.0 core (`tradingagents/`, `cli/`, `docs/`, `tests/`) + proprietary source-available `app/`, `frontend/`, `core/` (personal/education only, no commercial use or redistribution); Pro is commercial | 32.9k / 6.9k | v3.0.0 (2026-09-22) | 2026-09-22 | Active; narrowed to A-shares |
| [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) | MIT | 64,631 / 11,371 | aihf 2.7.2 (PyPI) | 2026-11-09 | Very active; v2 rewrite |
| [virattt/dexter](https://github.com/virattt/dexter) | MIT (README) | 27,815 / 3,430 | package 1.0.6; latest tag v2026.6.9 | 2026-09-23 | Active, slowing |
| [OpenBB-finance/OpenBB](https://github.com/OpenBB-finance/OpenBB) | Apache-2.0 repo; openbb 5.0.0 on PyPI Apache-2.0 (2026-09-29); `openbb-yfinance`/`openbb-fmp` AGPL-3.0-only | 75.3k / 7.9k | openbb 5.0.0; GitHub tags to v4.7.0 | 2026-11-11 | Very active |
| [AI4Finance-Foundation/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) | MIT | 22k / 3.1k | tag v1.0.0 | 2026-10-25 (lookahead fix, PR #281) | Maintenance only; last model news Nov 2023 |
| [AI4Finance-Foundation/FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) | **Apache-2.0** | 8.4k / 1.4k | desktop-v0.1.0, v1.0.0 | 2026-10-24 | Active |
| [pipiku915/FinMem-LLM-StockTrading](https://github.com/pipiku915/FinMem-LLM-StockTrading) | MIT | 972 / 194 | none | 2024-08-17 | **Abandoned** (~27 months) |
| [AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL) | MIT | 17k / 3.6k | tag v0.3.8 | 2026-10-25 | Maintained (RL, not LLM) |
| [microsoft/qlib](https://github.com/microsoft/qlib) | MIT | 50.2k / 7.9k | tag v0.9.8 | 2026-10-08 (security fix #2340) | Maintained |
| [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent) | MIT | 15.3k / 2.0k | v1.0.0 (release commit 2026-09-23) | 2026-09-23 | Active |
| [ValueCell-ai/valuecell](https://github.com/ValueCell-ai/valuecell) | Apache-2.0 (own code only) | 11.1k / 1.8k | tag v0.1.20 | 2026-02-11 | **Stale ~9 months**; pivot to hosted valuecell.ai |
| [HKUDS/AI-Trader](https://github.com/HKUDS/AI-Trader) | MIT per badge (no root LICENSE file seen in tree) | 23.2k / 3.5k | none | 2026-06-11 | Slowing; now a hosted platform (ai4trade.ai) |
| [Fincept-Corporation/FinceptTerminal](https://github.com/Fincept-Corporation/FinceptTerminal) | AGPL-3.0-or-later; closed Enterprise edition $15–$45/user/mo | 33.7k / 4.8k | v4.5.2 | 2026-11-09 | Very active |
| [financial-datasets/mcp-server](https://github.com/financial-datasets/mcp-server) | MIT | n/a | none | 2025-06-05 | **Stale** |
| [narumiruna/yfinance-mcp](https://github.com/narumiruna/yfinance-mcp) | MIT | ~135–149 (third-party) | — | 2026-11-08 | Active |
| [pyang2045/twsemcp](https://github.com/pyang2045/twsemcp) | MIT | n/a | v1.1.0 (LobeHub) | 2025-08-16 | **Stale** |

Sources for the table:
- Star counts: GitHub pages ([TradingAgents](https://github.com/TauricResearch/TradingAgents), [TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN), [virattt repos](https://github.com/virattt?tab=repositories&sort=stargazers), [AI4Finance repos](https://github.com/orgs/AI4Finance-Foundation/repositories?type=all&sort=stargazers), [OpenBB](https://github.com/OpenBB-finance/OpenBB), [qlib](https://github.com/microsoft/qlib), [RD-Agent](https://github.com/microsoft/RD-Agent), [ValueCell](https://github.com/ValueCell-ai/valuecell), [AI-Trader](https://github.com/HKUDS/AI-Trader), [Fincept](https://github.com/Fincept-Corporation/FinceptTerminal), [FinMem](https://github.com/pipiku915/FinMem-LLM-StockTrading), [Mai0313](https://github.com/Mai0313/TradingAgents)).
- Versions: [PyPI openbb](https://pypi.org/project/openbb/) and [PyPI aihf](https://pypi.org/project/aihf/).

Licence details:
- **OpenBB licence change.** OpenBB previously moved the Platform to AGPL ([OpenBB blog](https://openbb.co/blog/license-change-openbb-platform-goes-agpl/)). The current repo LICENSE reads "All files in this repository are licensed under the Apache License, Version 2.0" ([LICENSE](https://github.com/OpenBB-finance/OpenBB/blob/develop/LICENSE)). This contradicts the brief's assumption that "OpenBB = AGPL". OpenBB's own ODP product page reportedly still mentions AGPL ([search snippet](https://openbb.co/products/odp/)), so treat the per-package PyPI licence as authoritative.
- **OpenBB Workspace** (pro.openbb.co) is a closed, hosted product. The free Community plan includes "custom AI agent support" and 20 Copilot queries per day; paid tiers are not clearly priced. The open companion repos are `agents-for-openbb` and `backends-for-openbb`. — [README](https://github.com/OpenBB-finance/OpenBB/blob/develop/README.md); [pricing (search snippet)](https://openbb.co/pricing/)
- **FinRobot licence.** The LICENSE file is Apache-2.0 and the AI4Finance org page agrees ("Apache License 2.0"). This contradicts the brief's assumption of MIT. — [AI4Finance org page](https://github.com/orgs/AI4Finance-Foundation/repositories?type=all&sort=stargazers)

Disclaimers:
- **TradingAgents:** "designed for research purposes … not intended as financial, investment, or trading advice." — [README](https://github.com/TauricResearch/TradingAgents/blob/main/README.md)
- **ai-hedge-fund:** "educational and research purposes only … Not intended for real trading." — [README](https://github.com/virattt/ai-hedge-fund/blob/main/README.md)
- **Dexter:** "educational, entertainment, and informational purposes only." — [README](https://github.com/virattt/dexter/blob/main/README.md)
- **TradingAgents-CN:** "不构成投资建议". It also does not give target prices, stop-loss/take-profit levels or trade timing. — [README](https://github.com/hsliuping/TradingAgents-CN/blob/v3.0/README.md)
- **OpenBB:** "data … not necessarily accurate." — [README](https://github.com/OpenBB-finance/OpenBB/blob/develop/README.md)

### Inferences
- **TradingAgents' 122k stars is unusually high** for a project that had far fewer in 2025. The number is reported as displayed and could not be cross-checked via the API.
- **For a Taiwan product:** permissive licences (TradingAgents Apache-2.0, ai-hedge-fund MIT, Dexter MIT, FinRobot Apache-2.0, Qlib/RD-Agent MIT) are safe to embed.
  - Fincept (AGPL) and `openbb-yfinance` (AGPL) carry copyleft obligations if modified and served.
  - TradingAgents-CN's app layer cannot be used commercially.

### Gaps
- Exact star counts and release dates via the GitHub API were unavailable.
- Release dates for the FinRL, Qlib and FinGPT tags were not retrieved.
- OpenBB Workspace paid-tier pricing is unclear. A third-party claim of "Workspace Lite $2,400/yr launched 2026-07-20" could not be verified on openbb.co.

---

## Q8. How these could be combined with a portfolio tracker for 台股

### Takeaway
The most practical open-source architecture is:
1. A portfolio tracker that holds positions and cost basis in TWD.
2. A Taiwan data layer: FinMind or TWSE OpenAPI, via FinMind-MCP, a custom TradingAgents vendor, or an OpenBB provider extension.
3. TradingAgents (Apache-2.0), with `--portfolio` JSON and output language set to Traditional Chinese, to produce per-holding multi-agent reports.

For conversational analysis, an MCP stack (FinMind-MCP + yfinance-mcp, plus a tracker-exposed MCP) in Claude Desktop/Code or another MCP host avoids building agents at all. Qlib + RD-Agent fit only if quant factor research on Taiwan data is wanted.

### Cited Findings
- **TradingAgents takes holdings as a broker-neutral JSON book.** The currency is a free label, so TWD works, and per-instrument holdings matching tolerates broker spellings. — [tradingagents/portfolio.py](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/portfolio.py); [CHANGELOG #1556](https://github.com/TauricResearch/TradingAgents/blob/main/CHANGELOG.md)
- **It runs unattended** from flags or env vars (v0.5.2), suitable for cron or scheduled jobs. — [CHANGELOG](https://github.com/TauricResearch/TradingAgents/blob/main/CHANGELOG.md)
- **Taiwan vendor templates exist.** PR #1159's twmd vendor shows the shape of a Taiwan vendor for TradingAgents' router (prices, monthly revenue, statements). — [PR #1159](https://github.com/TauricResearch/TradingAgents/pull/1159)
- **ai-hedge-fund's `DataClient` protocol** allows a FinMind client without inheritance. — [data/protocol.py](https://github.com/virattt/ai-hedge-fund/blob/main/hedge_fund/data/protocol.py)
- **OpenBB ODP** exposes any installed extension via Python, REST (`openbb-api`), MCP (`openbb-mcp`) and Workspace. — [README](https://github.com/OpenBB-finance/OpenBB/blob/develop/README.md); [MCP README](https://github.com/OpenBB-finance/OpenBB/blob/develop/openbb_platform/extensions/mcp_server/README.md)
- **FinMind-MCP** gives MCP hosts natural-language access to Taiwan stock data such as 2330 法人買賣超 and 月營收. — [FinMind-MCP](https://github.com/FinMind/FinMind-MCP)
- **twsemcp** wraps the TWSE official API (quarterly statements, foreign holdings, P/E, dividend yield), but has had no commits since 2025-08-16. — [twsemcp](https://github.com/pyang2045/twsemcp)
- **Qlib accepts custom CSV data**, but ships no TW collector. — [qlib](https://github.com/microsoft/qlib); [collector.py](https://github.com/microsoft/qlib/blob/main/scripts/data_collector/yahoo/collector.py)

### Inferences
- **Integration levels, from easiest to most work:**
  - **(a) No code.** Export holdings, then ask Claude or another MCP-capable LLM with FinMind-MCP + yfinance-mcp for a portfolio review in 繁中.
  - **(b) Light code.** Per-holding TradingAgents runs (`--ticker 2330.TW --portfolio book.json`, `TRADINGAGENTS_OUTPUT_LANGUAGE="Traditional Chinese"`), with saved HTML/Markdown reports attached to each holding in the tracker.
  - **(c) Medium code.** Add a FinMind vendor to TradingAgents (月營收, 三大法人, 財報, plus Chinese news) to fix the Yahoo gaps and enable point-in-time fundamentals for backtests. Optionally upstream it, or keep it as a fork (PR #1159/#1348 history shows upstream reluctance).
  - **(d) Heavy.** Use OpenBB ODP with a custom FinMind provider as a unified data backend for both the tracker's charts and the agents' MCP tools.
- **Avoid as the core for Taiwan:**
  - TradingAgents-CN: A-share only, and its app layer is non-commercial.
  - ai-hedge-fund and Dexter as-is: Financial Datasets is a US-centric data API (an inference, not verified from its docs).
  - FinMem: abandoned.
  - ValueCell: stale, no Taiwan support.

### Gaps
- No end-to-end open-source project combining a portfolio tracker with an LLM multi-agent analyst for 台股 was found.
- Financial Datasets' international coverage was not checked against its docs.
- Whether FinMind's free tier rate limits allow daily multi-agent runs is out of scope; other researchers cover FinMind.
