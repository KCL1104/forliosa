# Open-source self-hostable portfolio trackers: Taiwan-stock (TWSE/TPEx) fit, performance, and AI features (as of 2026-11-11)

Method note: GitHub repos were read directly (shallow clones of HEAD on 2026-11-10/11 plus github.com pages). The `gh`/api.github.com route was blocked in this session, so star counts come from the github.com repo pages (rounded, e.g. "9.7k"). Official doc sites (ghostfol.io, wealthfolio.app, help.portfolio-performance.info) did not resolve from this session's network, so doc-site facts come from the repos themselves (README, CHANGELOG, source, release metadata). Code-path links point at the default branch (`main` for Ghostfolio/Wealthfolio/Sure, `master` for Portfolio Performance).

## Key Question 1: Taiwan stock support (data providers, .TW/.TWO resolution, TWD and multi-currency, Taiwan-related issues, custom data sources)

### Takeaway
All four maintained projects use Yahoo Finance as the free default source. Yahoo lists Taiwan stocks as `2330.TW` (上市) and `6488.TWO` (上櫃), so basic Taiwan pricing works in every one of them. Wealthfolio and Portfolio Performance (PP) go further: both explicitly map TWSE→`.TW` and TPEx→`.TWO` with TWD, both have Traditional Chinese UIs, and both let users plug in their own JSON/HTML/CSV quote feeds, so official TWSE/TPEx data can be wired in. Ghostfolio works through Yahoo and also has a JSON/HTML "scraper" for `MANUAL` assets. Sure's Yahoo exchange table has no Taiwan suffix mapping, so it is the weakest fit for 台股.

### Cited Findings
**Ghostfolio**
- The schema's `DataSource` enum is `ALPHA_VANTAGE, COINGECKO, EOD_HISTORICAL_DATA, FINANCIAL_MODELING_PREP, GHOSTFOLIO, GOOGLE_SHEETS, MANUAL, RAPID_API, YAHOO` — [prisma/schema.prisma](https://github.com/ghostfolio/ghostfolio/blob/main/prisma/schema.prisma). Matching service folders exist under [apps/api/src/services/data-provider](https://github.com/ghostfolio/ghostfolio/tree/main/apps/api/src/services/data-provider).
- The import API's `dataSource` field accepts `COINGECKO | GHOSTFOLIO | MANUAL | YAHOO`. `GHOSTFOLIO` is footnoted "Available with Ghostfolio Premium" (the professional data provider) — [README](https://github.com/ghostfolio/ghostfolio/blob/main/README.md).
- Search has used `yahoo-finance2` since 1.137.0 (2022-04-15). Release 3.95.0 (2026-10-31) upgraded yahoo-finance2 to 4.0.5 — [CHANGELOG](https://github.com/ghostfolio/ghostfolio/blob/main/CHANGELOG.md).
- Custom data via the `MANUAL` data source plus a "scraper configuration":
  - 2.227.0 (2026-01-02) "Fixed the import of `jsonpath` to support REST APIs (`JSON`) via the scraper configuration".
  - 2.228.0 (2026-01-03) moved the scraper to a dedicated tab in the admin asset-profile dialog.
  - 3.30.0 (2026-07-19) added converting an asset profile to `MANUAL`.
  - 2.245.0 (2026-03-01) excluded the scraper configuration from import/export.
  - Source: [CHANGELOG](https://github.com/ghostfolio/ghostfolio/blob/main/CHANGELOG.md)
- 2.217.1 (2025-11-16): "Introduced support for automatically gathering required exchange rates" (`ENABLE_FEATURE_GATHER_NEW_EXCHANGE_RATES`). There are also multiple fixes for exchange rates "calculated indirectly via the base currency" — [CHANGELOG](https://github.com/ghostfolio/ghostfolio/blob/main/CHANGELOG.md). The import API uses ISO currency codes per activity — [README](https://github.com/ghostfolio/ghostfolio/blob/main/README.md).
- A GitHub search of ghostfolio issues for "Taiwan" returns only #6202 "Ghostfolio in Chinese" — no ticker/TWSE bug reports — [search](https://github.com/search?q=repo%3Aghostfolio%2Fghostfolio+Taiwan&type=issues); [#6202](https://github.com/ghostfolio/ghostfolio/issues/6202).
- A static-analysis rule "Regional Market Cluster Risk (Asia-Pacific Markets)" exists (localized in 2.184.0, 2025-07-22) — [CHANGELOG](https://github.com/ghostfolio/ghostfolio/blob/main/CHANGELOG.md).

**Wealthfolio** (repo moved from `afadil/wealthfolio` to the `wealthfolio` org; the Docker image is mirrored to `afadil/wealthfolio` as "legacy")
- Market-data providers in source:
  - `yahoo`, `alpha_vantage`, `finnhub`, `marketdata_app`, `metal_price_api`, `boerse_frankfurt`, `amfi` (India MF), `moex` (Moscow), `openfigi` (ID mapping), `us_treasury_calc` — [crates/market-data/src/provider](https://github.com/wealthfolio/wealthfolio/tree/main/crates/market-data/src/provider)
  - A separate user-defined `custom_provider` module — [crates/core/src/custom_provider](https://github.com/wealthfolio/wealthfolio/tree/main/crates/core/src/custom_provider)
- Taiwan is mapped explicitly in the exchange registry:
  - `XTAI` "TWSE / Taiwan Stock Exchange", currency `TWD`, timezone `Asia/Taipei`, close 13:30, `YAHOO: { suffix: ".TW", codes: ["TAI","TPE"] }`
  - `ROCO` "TPEx / Taipei Exchange", `TWD`, `YAHOO: { suffix: ".TWO", codes: ["TWO"] }`
  - Currency map `"TWD": ["XTAI","ROCO"]`
  - Source: [exchanges.json](https://github.com/wealthfolio/wealthfolio/blob/main/crates/market-data/src/resolver/exchanges.json)
- The custom provider supports `json`, `html` and `csv` formats with a URL template. Template variables are `symbol`, `currency`, `isin`, `mic`, `from`, `to`. Extraction fields are `price_path` ("JSONPath expression, CSS selector, or table_idx:col_idx"), `date_path`, `date_format`, `currency_path`, `factor`, `invert`, `locale`, with GET/POST and browser-like headers — [custom_provider/model.rs](https://github.com/wealthfolio/wealthfolio/blob/main/crates/core/src/custom_provider/model.rs).
- README: "Multi-Currency – Support for multiple currencies with exchange rate management" — [README](https://github.com/wealthfolio/wealthfolio/blob/main/README.md).
- Taiwan-related issues (from [issue search](https://github.com/search?q=repo%3Awealthfolio%2Fwealthfolio+Taiwan+OR+TWSE+OR+TWD&type=issues)):
  - **Benchmark request (resolved):** [#259](https://github.com/wealthfolio/wealthfolio/issues/259) (opened 2025-05-25) asked for 0050.TW / TAIEX as a benchmark. It closed as completed 2025-06-19 after a contributor said that since v1.1.3 "any symbol can be added as a benchmark" (fixes in 1.1.4).
  - **Traditional Chinese locale:** [#1230](https://github.com/wealthfolio/wealthfolio/issues/1230) / [#1301](https://github.com/wealthfolio/wealthfolio/issues/1301) are Traditional Chinese locale requests (Jul 2026).
  - **Bugs reported by TWD-base users:**
    - [#1425](https://github.com/wealthfolio/wealthfolio/issues/1425): a one-day negative cash balance nulls TWR (TWD base, Taiwanese-broker import)
    - [#1414](https://github.com/wealthfolio/wealthfolio/issues/1414): portfolio TWR wrong with different account inception dates (includes a TWD account)
    - [#1473](https://github.com/wealthfolio/wealthfolio/issues/1473): attribution doesn't reconcile for a non-base-currency account (TWD base)
    - [#1047](https://github.com/wealthfolio/wealthfolio/issues/1047): a TWD→USD transfer booked NT$1,000 as $1,000
    - [#2215](https://github.com/wealthfolio/wealthfolio/issues/2215): decimal-comma paste bug, Taiwan listed among affected regions
  - Open/closed states were not visible in the search results.
- v3.12.0 (2026-11-01) added a "red-up/green-down" gain/loss colour option for markets such as Taiwan, plus new price sources (AMFI, MOEX) — [releases](https://github.com/wealthfolio/wealthfolio/releases).

**Portfolio Performance (PP)**
- Quote feed implementations in source:
  - `YahooFinanceQuoteFeed`, `YahooFinanceAdjustedCloseQuoteFeed`, `AlphavantageQuoteFeed`, `EODHistoricalDataQuoteFeed`, `FinnhubQuoteFeed`, `TwelveDataQuoteFeed`, `LeewayQuoteFeed`, `CoinGeckoQuoteFeed`
  - `GenericJSONQuoteFeed`, `HTMLTableQuoteFeed`, `ManualQuoteFeed`, `PortfolioReportQuoteFeed`
  - `SiftingQuoteFeed` (new in 0.88.0), `MFAPIQuoteFeed`, `AMFIIndiaQuoteFeed`, `ECBDataPortalQuoteFeed`, `EurostatHICPQuoteFeed`, `QuandlQuoteFeed`, `CSQuoteFeed`, Binance/Bitfinex/Kraken/MEXC
  - Source: [online/impl](https://github.com/portfolio-performance/portfolio/tree/master/name.abuchen.portfolio/src/name/abuchen/portfolio/online/impl)
- The exchange picker has Taiwan labels:
  - `yahoo.TW = Taiwan Stock Exchange (TWSE)`, `yahoo.TWO = Taiwan OTC Exchange`, `leeway.TW = Taiwan Exchange`, `leeway.TWO = Taiwan OTC Exchange`
  - The zh_TW label file names them 臺灣證券交易所 (TWSE) / 臺灣證券櫃檯買賣中心
  - Source: [exchange-labels.properties](https://github.com/portfolio-performance/portfolio/blob/master/name.abuchen.portfolio/src/name/abuchen/portfolio/online/impl/exchange-labels.properties); [exchange-labels_zh_TW.properties](https://github.com/portfolio-performance/portfolio/blob/master/name.abuchen.portfolio/src/name/abuchen/portfolio/online/impl/exchange-labels_zh_TW.properties)
- A GitHub issue search for Taiwan/TWSE/".TW" finds no Taiwan-market bug reports. The only relevant hit is [#3529](https://github.com/portfolio-performance/portfolio/issues/3529) "add Traditional Chinese (zh-TW) translation" (2023-08-30), noting other translators had already finished zh-TW — [search](https://github.com/search?q=repo%3Aportfolio-performance%2Fportfolio+Taiwan+OR+TWSE+OR+%22.TW%22&type=issues).

**Sure (we-promise/sure)**
- Provider registry:
  - Securities: `twelve_data, yahoo_finance, tiingo, eodhd, alpha_vantage, mfapi, binance_public, moex_public, tinkoff_invest, mansa`
  - Exchange rates: `twelve_data, yahoo_finance, moex_public, frankfurter`
  - API keys via ENV or Settings (`TWELVE_DATA_API_KEY`, `TIINGO_API_KEY`, `EODHD_API_KEY`, `ALPHA_VANTAGE_API_KEY`)
  - Source: [registry.rb](https://github.com/we-promise/sure/blob/main/app/models/provider/registry.rb)
- Yahoo `EXCHANGE_CONFIG` (MIC→suffix):
  - Mapped: India, Colombia, Indonesia and European venues only. **No `XTAI`/`ROCO` entry.**
  - `map_exchange_mic` maps Yahoo codes for US, Canada, Europe, `HKG`, `TYO`, `ASX`, `NSE/BSE`, `BVC`, `JKT` — not `TAI`/`TWO`.
  - The code comment warns: "A MIC missing here means the symbol is sent to Yahoo bare, which for any non-US listing is a 404: the security then accumulates failed fetches and never gets a price".
  - Search results do store Yahoo's full `quote["symbol"]` (e.g. `2330.TW`).
  - Source: [yahoo_finance.rb](https://github.com/we-promise/sure/blob/main/app/models/provider/yahoo_finance.rb)
- `config/exchanges.yml` lists `XTAI` (name "Taiwan", country TW) but no TPEx (`ROCO`) entry — [exchanges.yml](https://github.com/we-promise/sure/blob/main/config/exchanges.yml).
- An issue search for Taiwan/TWSE/TWD returns 0 issues — [search](https://github.com/search?q=repo%3Awe-promise%2Fsure+Taiwan+OR+TWSE+OR+TWD&type=issues).
- Recent provider work:
  - v0.7.5-hotfix.3 added a fallback to a direct Yahoo chart lookup when Yahoo search returns nothing.
  - v2026.11.3-alpha rejects Yahoo FX quotes lacking a currency.
  - v2026.11.8-alpha added Sharesight as a provider.
  - Source: [releases](https://github.com/we-promise/sure/releases)

**Other projects**
- Investbrain (investbrainapp/investbrain): Laravel/PHP, Docker. The repo page names no market data providers and does not mention international/Asian market support — [repo](https://github.com/investbrainapp/investbrain).
- Commercial reference point (not open source): Sharesight advertises support for over 1,000 TWSE listings — [Sharesight blog](https://sharesight.com/blog/track-the-taiwan-stock-exchange-twse-with-sharesight).
- Taiwan-native open-source alternatives surfaced by search. These are snippets only; license and maintenance are unverified:
  - [zihuanfeng520/biaogu](https://github.com/zihuanfeng520/biaogu): front-end only, localStorage, 上市櫃 + US
  - [a858500456-gif/investment-tracker](https://github.com/a858500456-gif/investment-tracker): GitHub Pages, auto closing prices
  - [yolin0513/stockdiary](https://github.com/yolin0513/stockdiary): offline PWA, 上市 only, 除權息日曆
  - [RX5950XT/portfolio-visualizer](https://github.com/RX5950XT/portfolio-visualizer): multi-portfolio, realized P&L in TWD, MCP interface
  - [sacahan/CasualMarket](https://github.com/sacahan/CasualMarket): a Taiwan-stock MCP server
  - [FinMind](https://github.com/FinMind/FinMind): open Taiwan market data incl. 除權息 results
  - Source: [web search](https://github.com/zihuanfeng520/biaogu)

### Inferences
- For a TWD-base investor, ticker formats are `2330.TW`, `0050.TW`, `0056.TW`, `00878.TW` (all TWSE-listed ETFs) and `6488.TWO` (TPEx). Yahoo's free feed is the common denominator for Ghostfolio, Wealthfolio, PP and Sure.
- Wealthfolio and PP natively understand TWSE/TPEx metadata: exchange→suffix→TWD→Asia/Taipei. Wealthfolio's exchange registry also knows the 13:30 close, which matters for same-day valuation timing.
- Official TWSE/TPEx data (TWSE OpenAPI JSON, TPEx JSON, FinMind) can be plugged in as follows:
  - **Wealthfolio:** `custom_provider` with JSON/HTML/CSV, JSONPath or CSS selector.
  - **PP:** `GenericJSONQuoteFeed` / `HTMLTableQuoteFeed`.
  - **Ghostfolio:** `MANUAL` + scraper with JSONPath, set per asset in the admin panel.
  - **Sure:** no equivalent user-facing feed. Code-level provider generators exist ([docs/llm-guides/adding-a-securities-provider.md](https://github.com/we-promise/sure/blob/main/docs/llm-guides/adding-a-securities-provider.md)), but that means writing Ruby.
- Sure is likely to work for TWSE tickers added via Yahoo search, because the stored symbol already carries `.TW`. However, the missing `XTAI`/`ROCO` suffix config and the missing TPEx exchange entry mean manually created or provider-mapped Taiwan securities can silently fail to price. This is an inference from code; it was not tested.
- Yahoo is an unofficial, rate-limited source. Every Yahoo-dependent tool inherits its occasional outages and its handling of Taiwan ex-dividend adjustments. PP's separate "Adjusted Close" feed lets users choose raw vs adjusted prices.

### Gaps
- None of the apps were run, so `2330.TW`/`6488.TWO`/`00878.TW` symbol search was not tested end-to-end.
- No GitHub Discussions were searched, and the PP forum (forum.portfolio-performance.info) was not reachable or indexed for Taiwan threads.
- No Taiwanese blog, PTT or Mobile01 posts about using Ghostfolio, Wealthfolio or PP for 台股 surfaced in web search. Targeted Chinese queries returned only unrelated Taiwan-stock apps.
- Ghostfolio's Premium `GHOSTFOLIO` data provider's coverage of TWSE/TPEx could not be checked (ghostfol.io unreachable).
- Whether Twelve Data, EODHD or Tiingo free tiers cover TWSE/TPEx in Sure was not verified.

## Key Question 2: Taiwan-specific quirks (除權息 / 配股, 零股, 手續費 0.1425%, 證交稅 0.3%/0.1%, 二代健保補充保費)

### Takeaway
None of the international trackers has Taiwan-specific fee or tax logic: no automatic 0.1425% 手續費 with broker discounts, no 證交稅 0.3% (stocks) / 0.1% (ETFs), and no 二代健保 2.11% supplementary premium. Users must enter fees and taxes per transaction. The data models differ in how cleanly they hold 配股 (stock dividends):
- **Wealthfolio:** best fit, with explicit `TAX` and `FEE` activity types and a `DIVIDEND_IN_KIND` subtype.
- **PP:** per-transaction fee and tax fields plus inbound deliveries.
- **Ghostfolio:** cash dividends work, but stock dividends need a workaround because it has only 6 activity types.

### Cited Findings
- **Ghostfolio:**
  - Activity `Type` enum is only `BUY, DIVIDEND, FEE, INTEREST, LIABILITY, SELL` — no split, transfer, tax or stock-dividend type — [schema.prisma](https://github.com/ghostfolio/ghostfolio/blob/main/prisma/schema.prisma).
  - Each activity carries `fee`, `quantity`, `unitPrice`, `currency` — [README import API](https://github.com/ghostfolio/ghostfolio/blob/main/README.md).
- **Wealthfolio:**
  - Activity types: `BUY, SELL, DIVIDEND, INTEREST, DEPOSIT, WITHDRAWAL, TRANSFER_IN, TRANSFER_OUT, FEE, TAX, SPLIT, CREDIT, ADJUSTMENT`.
  - Subtypes include `DRIP`, `DIVIDEND_IN_KIND`, `BONUS`, `RETURN_OF_CAPITAL`, `REBATE`, `REFUND`, among others.
  - Source: [activities_constants.rs](https://github.com/wealthfolio/wealthfolio/blob/main/crates/core/src/activities/activities_constants.rs)
- **Wealthfolio cost basis:** FIFO, weighted average, LIFO and HIFO methods are supported — [README](https://github.com/wealthfolio/wealthfolio/blob/main/README.md). v3.10.0 (2026-10-14) introduced "a new calculation engine, cost basis methods" — [releases](https://github.com/wealthfolio/wealthfolio/releases).
- **PP:**
  - 0.89.0 (2026-10-11): "Fees charged on dividends are now included in a security's total fees".
  - 0.86.0 (2026-07-16): added a moving-average cost-basis P/L column.
  - 0.87.0 (2026-08-16): trades can be grouped by lot.
  - 0.86.1: "FIFO capital gains now use the exchange rate recorded on the transaction".
  - Source: [metainfo release notes](https://github.com/portfolio-performance/portfolio/blob/master/portfolio-product/metainfo/info.portfolio_performance.PortfolioPerformance.metainfo.xml)
- **Sure:**
  - v0.7.6 (2026-10-31) added stock-split handling.
  - v2026.11.10-alpha replaced the cost-basis tracker with an in-memory lot book.
  - Source: [releases](https://github.com/we-promise/sure/releases)
- **Taiwan-native tools:** some small open-source projects do model Taiwan specifics (search snippets, unverified):
  - [muzsor/twstock-calc](https://github.com/muzsor/twstock-calc): 手續費折扣, 借券費, 二代健保補充保費, 股利所得稅 A/B 方案 (a calculator, not a tracker)
  - [a858500456-gif/investment-tracker](https://github.com/a858500456-gif/investment-tracker): auto 手續費/證交稅
  - [zihuanfeng520/biaogu](https://github.com/zihuanfeng520/biaogu): adds back received dividends so 除權息 price drops aren't counted as losses

### Inferences
- **零股 (odd lots):** not a problem in any of these tools. They count shares, not 張, so odd lots are just quantity < 1000. The catch: Taiwan broker statements often show 張, so users must convert (1 張 = 1,000 shares) before CSV import.
- **配股 (stock dividends), per tool:**
  - Wealthfolio: `DIVIDEND` with subtype `DIVIDEND_IN_KIND`, or `TRANSFER_IN`/`BONUS`.
  - PP: inbound delivery at zero/assigned cost. This is from background knowledge of PP's transaction types; PP's help site was not reachable this session.
  - Ghostfolio: `BUY` with `unitPrice` 0. Common practice in other trackers per general guidance, e.g. [StocksCafe forum](https://forum.stocks.cafe/t/how-should-i-account-for-scrip-dividends-bonus-shares-rights-issues-etc/77). This distorts ROAI and investment charts somewhat.
- **證交稅 and 二代健保:**
  - 證交稅 on sells can go in the per-trade fee field (Ghostfolio `fee`) or a separate `TAX` activity (Wealthfolio).
  - 二代健保 2.11% on single dividends ≥ NT$20,000 can be booked as a `TAX`/`FEE` on the dividend date (Wealthfolio, Ghostfolio) or as the dividend's tax amount (PP).
  - None automate the threshold logic.
- **Adjusted vs raw prices:** Yahoo's adjusted-close series retroactively adjusts for 除權息. Mixing adjusted prices with recorded cash dividends double-counts returns. PP explicitly offers raw vs adjusted Yahoo feeds; the others use whatever their Yahoo integration returns, which is not verified.
- **Best option for automatic 台股 fee/tax:** an AI importer or a custom CSV pre-processing step (e.g. Wealthfolio's AI CSV import) is the realistic path, since no tracker computes 0.1425%×折扣, 0.3%/0.1% or 2.11% automatically.

### Gaps
- No documentation (or tests) was found in any of the four projects for Taiwan-style combined 現金股利+股票股利 events on the same ex-date. Auto-import of dividend events: unverified for Taiwan. Wealthfolio has a dividend model in `crates/market-data/src/models/dividend.rs`, but whether it auto-creates Taiwan dividend activities was not checked.
- PP's exact transaction type names (inbound delivery) and fee/tax fields were not re-verified from source this session.

## Key Question 3: Performance management (metrics, benchmarks, allocation, FIRE; CSV import; entering current positions without history)

### Takeaway
PP is the most rigorous analytically: TTWROR and IRR, volatility, Sharpe, max drawdown, taxonomies and rebalancing. Wealthfolio is the most complete modern UI: TWR+MWR, benchmarks with any symbol, a holdings-only tracking mode, FIRE/retirement planning, and rebalancing. Ghostfolio reports ROAI (not TWR) with benchmarks, FIRE and risk rules. Sure is a net-worth/budget app whose investment analytics are new and alpha-grade (MWR and sector/region allocation added Oct–Nov 2026).

### Cited Findings
**Ghostfolio**
- **ROAI:** "Return on Average Investment (ROAI) including dividends (total return) for Today, WTD, MTD, YTD, 1Y, 5Y, Max". Ghostfolio switched to TWR in 1.31.0 (2021-08-01) but now advertises ROAI.
- **Other features:** multi-account; import/export of transactions; "Static analysis to identify potential risks" — e.g. Regional/Economic Market Cluster Risk rules; Progressive Web App.
- **FIRE:** a FIRE section with the 4% rule, added in 1.130.0 (2022-03-30).
- **Dividends and benchmarks:** dividend yield in the position detail since 2.71.0 (2024-04-07); a benchmark comparator on the analysis page, improved repeatedly through 3.83.0 (2026-10-10).
- Sources: [README](https://github.com/ghostfolio/ghostfolio/blob/main/README.md); [CHANGELOG](https://github.com/ghostfolio/ghostfolio/blob/main/CHANGELOG.md)
- **Import:** `POST /api/v1/import` (JSON activities) and `GET /api/v1/export`. The import resolves ISIN to the provider symbol (changelog "Extended the activities import to resolve an ISIN to the symbol of the data provider") — [README](https://github.com/ghostfolio/ghostfolio/blob/main/README.md); [CHANGELOG](https://github.com/ghostfolio/ghostfolio/blob/main/CHANGELOG.md).

**Wealthfolio**
- **Features:**
  - "True time-weighted and money-weighted returns, benchmark comparison and historical analysis"
  - FIFO/WAVG/LIFO/HIFO cost basis
  - Net worth incl. liabilities/loans/mortgages/alternative assets
  - Goals, save-up simulations, retirement/FIRE planning
  - Rebalancing toward allocation targets
  - Options and short positions
  - Spending budgets
  - Manual tracking and CSV import are free
  - Sources: [README](https://github.com/wealthfolio/wealthfolio/blob/main/README.md); [repo page](https://github.com/wealthfolio/wealthfolio)
- **Holdings-only entry:** account tracking modes `TRANSACTIONS` vs `HOLDINGS` — [tracking-mode-badge.tsx](https://github.com/wealthfolio/wealthfolio/blob/main/apps/frontend/src/components/tracking-mode-badge.tsx). Agent tools include `holdings_snapshots` — [crates/agent-tools](https://github.com/wealthfolio/wealthfolio/tree/main/crates/agent-tools/src/tools).
- **Benchmarks:** any symbol can be a benchmark since v1.1.3/1.1.4, which covers the 0050.TW/TAIEX request — [#259](https://github.com/wealthfolio/wealthfolio/issues/259).
- **Known calculation bugs from TWD users:** TWR null on negative cash ([#1425](https://github.com/wealthfolio/wealthfolio/issues/1425)), portfolio TWR with differing inception dates ([#1414](https://github.com/wealthfolio/wealthfolio/issues/1414)), attribution ([#1473](https://github.com/wealthfolio/wealthfolio/issues/1473)).

**Portfolio Performance**
- **Return metrics:** UI strings "True Time-Weighted Rate of Return (cumulative/annualized)" (TTWROR) and "Internal Rate of Return (IRR)" — [messages.properties](https://github.com/portfolio-performance/portfolio/blob/master/name.abuchen.portfolio.ui/src/name/abuchen/portfolio/ui/messages.properties).
- **Risk metrics:** "Maximum Drawdown", "Max Drawdown Duration", "Sharpe ratio" — same file. 0.90.0 (2026-11-01) added an annualized volatility widget and fixed Sharpe to use annualized volatility.
- **Rebalancing and lots:** 0.86.0 added rebalancing with a new-cash amount and CSV import/export of custom attributes; 0.87.0 added trades grouped by lot.
- **Import:** 0.85.0 added a manual-entry PDF import fallback. Many PDF/CSV importers exist, but they are almost all for European/US brokers: XTB, Schwab, E*TRADE, Robinhood, Trade Republic, IBKR Flex, etc.
- Source for the above: [metainfo release notes](https://github.com/portfolio-performance/portfolio/blob/master/portfolio-product/metainfo/info.portfolio_performance.PortfolioPerformance.metainfo.xml)

**Sure**
- **Release history:**
  - v0.7.5: portfolio-weight rollups and money-weighted returns
  - v0.7.6 (2026-10-31): stock splits, plus an "Insights → Dig in with AI" option
  - v2026.11.8-alpha: allocation by asset class, sector and region
  - Source: [releases](https://github.com/we-promise/sure/releases)
- **Holdings and import:** a holdings cost-basis editor/reconciler exists (`app/models/holding/cost_basis_reconciler.rb`, `app/views/holdings/_cost_basis_form.html.erb`), and a trade-import configuration (`app/views/import/configurations/_trade_import.html.erb`) — [repo tree](https://github.com/we-promise/sure).

**Investbrain**
- Bulk-loading transactions from a spreadsheet, backups, AI chat over holdings, MCP server — [repo](https://github.com/investbrainapp/investbrain).

### Inferences
- **"Enter current positions only" (no history):**
  - Wealthfolio: supported natively via `HOLDINGS` tracking mode.
  - Ghostfolio: requires activities. Workaround: one BUY per holding at average cost on a chosen date. Returns before that date are then meaningless.
  - PP: same workaround (one buy or inbound delivery per holding).
  - Sure: has a cost-basis editor for holdings, which suggests a holdings-first workflow is possible (not verified in UI).
- **Metric definitions:** Ghostfolio's ROAI is not TWR or IRR. Investors comparing against 0050 total return should prefer Wealthfolio (TWR+MWR+benchmarks) or PP (TTWROR+IRR, benchmark via any security).
- **Taiwan broker CSV:** none ships an importer for Taiwan brokers (元大, 富邦, 國泰, 永豐 etc.). Every tool's generic CSV mapping (or Wealthfolio's AI CSV import) would be needed.

### Gaps
- Ghostfolio's current exact performance definitions (whether TWR is still computed internally), its allocation views (sector/region/asset class), and its XIRR support could not be confirmed from the docs site (unreachable). The README only advertises ROAI.
- Ghostfolio UI CSV import column format was not verified (only the JSON API).

## Key Question 4: AI features (built-in LLM analysis, providers, MCP servers / add-ons)

### Takeaway
As of Nov 2026, all four maintained projects ship an MCP endpoint, and three have in-app AI:
- **Wealthfolio:** the richest. A built-in AI assistant with 6 provider types including local Ollama, AI CSV import, and an MCP server for Claude/ChatGPT/Cursor.
- **Sure:** an in-app AI chat assistant (OpenAI-compatible or native Anthropic), auto-categorization, and an OAuth MCP server.
- **Ghostfolio:** "Copy AI prompt to clipboard" (paste into any chatbot), an OpenRouter-backed AI service, and an experimental MCP server.
- **PP:** added an experimental MCP endpoint in Oct 2026, with no in-app chat.

### Cited Findings
**Ghostfolio**
- "Copy AI prompt to clipboard" action on the analysis page, introduced 2.133.1 (2025-01-09), experimental:
  - 2.138.0 (2025-02-08) added a Duck.ai link.
  - 2.145.1 (2025-03-10) added "Copy portfolio data to clipboard for AI prompt".
  - 2.147.0 added filtering.
  - 3.59.1 (2026-08-23) added the activities count and first-activity date.
  - 3.87.0 (2026-10-17) added ISIN to the holdings table.
  - Source: [CHANGELOG](https://github.com/ghostfolio/ghostfolio/blob/main/CHANGELOG.md)
- "Extended the AI service by an access to OpenRouter (experimental)", 2.175.0 (2025-06-28). The `@openrouter/ai-sdk-provider` dependency is at 3.1.0. An admin-only AI health endpoint `GET api/v1/health/ai` (3.94.0, 2026-10-28). OpenRouter is also used for a `web_fetch` tool (3.7.0/3.9.0/3.62.0) — [CHANGELOG](https://github.com/ghostfolio/ghostfolio/blob/main/CHANGELOG.md).
- **MCP server** (experimental, introduced 3.59.1, 2026-08-23):
  - Endpoint `/mcp`, enabled with `ENABLE_FEATURE_MCP`, built on `@rekog/mcp-nest`.
  - Tools: holdings, accounts, activities, performance, watchlist, asset-profile search, import activities, update cash balance.
  - Access permissions: Restricted view / View / Restricted view and manage / View and manage.
  - OAuth 2.1 discovery endpoints added in 3.99.0 (2026-11-07).
  - Source: [README](https://github.com/ghostfolio/ghostfolio/blob/main/README.md); [CHANGELOG](https://github.com/ghostfolio/ghostfolio/blob/main/CHANGELOG.md)

**Wealthfolio**
- **AI assistant:** "Ask questions and import CSV files with a local model or your own API key, and connect AI agents such as Claude, ChatGPT or Cursor through MCP" — [README](https://github.com/wealthfolio/wealthfolio/blob/main/README.md).
- **Provider catalog:** `ollama, groq, google, anthropic, openai, openrouter` — [ai_providers.json](https://github.com/wealthfolio/wealthfolio/blob/main/crates/ai/src/ai_providers.json).
- **AI crate CHANGELOG:**
  - Spending-categorization tools
  - A live-model eval framework defaulting to Ollama `gemma4:e4b`
  - Tool-schema snapshot tests
  - Source: [crates/ai/CHANGELOG.md](https://github.com/wealthfolio/wealthfolio/blob/main/crates/ai/CHANGELOG.md)
- **Release history:**
  - v3.10.0 (2026-10-14): MCP tools for linking transfers, importing quotes, updating activities, categorizing.
  - v3.11.0 (2026-10-23): current Claude/GPT/Gemini models, plus "AI Agent Access" setup guides for Claude Code, Codex, ChatGPT desktop, Cursor.
  - v3.12.0 (2026-11-01): a Spending permission set for AI agents.
  - Source: [releases](https://github.com/wealthfolio/wealthfolio/releases)
- **Self-host MCP config:** `WF_MCP_ENABLED`, `WF_MCP_AUDIT_ENABLED`, `WF_MCP_ALLOWED_HOSTS` — [README](https://github.com/wealthfolio/wealthfolio/blob/main/README.md).
- **Addon system:** a TypeScript SDK, permission system, Secrets API, plus official and community addon repos — [README](https://github.com/wealthfolio/wealthfolio/blob/main/README.md); [wealthfolio-addons](https://github.com/wealthfolio/wealthfolio-addons).

**Sure**
- **Built-in chat:**
  - Uses `LLM_PROVIDER`: either the OpenAI-compatible provider (`OPENAI_ACCESS_TOKEN`/`OPENAI_URI_BASE`/`OPENAI_MODEL`, default) or native Anthropic (`ANTHROPIC_API_KEY`).
  - Background auto-categorization and merchant detection.
  - Local models via Ollama, LM Studio or LocalAI through the OpenAI-compatible endpoint, with VRAM guidance (8 GB → 7B models, etc.).
  - An "External" assistant mode for agents.
  - Source: [docs/hosting/ai.md](https://github.com/we-promise/sure/blob/main/docs/hosting/ai.md)
- **MCP server:** OAuth 2.0 + dynamic client registration (for Claude.ai), or a static `MCP_API_TOKEN` + `MCP_USER_EMAIL` — [docs/hosting/mcp.md](https://github.com/we-promise/sure/blob/main/docs/hosting/mcp.md).
- **Recent AI releases:**
  - v0.7.6: "Dig in with AI" from Insights, Gemini 3 support
  - v0.7.5-hotfix.3: OpenAI extra headers; assistant/MCP tools for bills
  - v2026.11.3-alpha: model pricing for current Claude/OpenAI models
  - Source: [releases](https://github.com/we-promise/sure/releases)
- **Render deploy templates:** "Simple AI" (OpenAI) and "External AI" (OpenClaw gateway via AlphaClaw) — [repo README](https://github.com/we-promise/sure).

**Portfolio Performance**
- 0.89.0 (2026-10-11), Experimental: "An MCP endpoint lets AI assistants read and update parts of your portfolio data. This first version does not cover everything yet" — [metainfo](https://github.com/portfolio-performance/portfolio/blob/master/portfolio-product/metainfo/info.portfolio_performance.PortfolioPerformance.metainfo.xml).
- The endpoint is loopback-only `POST /mcp`, authenticated with REST API bearer tokens; there is no OAuth — [ADR 0005](https://github.com/portfolio-performance/portfolio/blob/master/docs/adr/0005-authenticate-the-mcp-endpoint-with-rest-api-tokens.md).
- Tools:
  - `pp_list_files`, `pp_list_instruments`, `pp_get_instrument`, `pp_update_instrument`, `pp_delete_instrument`
  - `pp_list_holdings`, `pp_get_overall_performance`, `pp_list_instrument_performance`, `pp_get_instrument_performance`, `pp_list_trades`
  - plus cash/investment-account getters
  - Source: [mcp-tools.json](https://github.com/portfolio-performance/portfolio/blob/master/name.abuchen.portfolio.rest/mcp-tools.json)
- No in-app LLM chat was found in source or release notes.

**Others**
- **Investbrain:** "LLM-enabled" — AI chat over holdings and an MCP server for Claude, ChatGPT, Cursor, VS Code. Providers are not named on the repo page — [repo](https://github.com/investbrainapp/investbrain).
- **Taiwan market-data MCP servers** (snippets only, unverified):
  - [sacahan/CasualMarket](https://github.com/sacahan/CasualMarket): Taiwan-stock MCP server with quotes and financials
  - [RX5950XT/portfolio-visualizer](https://github.com/RX5950XT/portfolio-visualizer): a 台股 portfolio tool with an MCP interface

### Inferences
- **Privacy-preserving AI on 台股 data:** Wealthfolio (Ollama in-app) and Sure (OpenAI-compatible → Ollama) can run fully local LLMs. Ghostfolio's in-app AI is OpenRouter-based (cloud), though its MCP server can be used with any client. PP's MCP is loopback-only, so it pairs with a local desktop AI client (e.g. Claude Desktop).
- **Taiwan-aware AI setup:** pair one tracker's MCP server (holdings/performance) with a Taiwan market-data MCP (TWSE/FinMind-based) in the same AI client. This gives Taiwan-aware analysis (除權息, 法人, 財報) that none of the trackers provide natively.
- **Status:** all MCP features are labeled experimental in Ghostfolio and PP as of Nov 2026, so expect breaking changes.

### Gaps
- Ghostfolio's in-app AI service details (which OpenRouter model, whether it is self-host configurable via admin settings or Premium-only) could not be confirmed (ghostfol.io docs unreachable; README does not document it).
- Whether Wealthfolio's AI assistant is available in the Docker/web build vs desktop only was not verified.
- Investbrain's LLM providers and license type were not determinable from the repo page.

## Key Question 5: Project health, license, stack, deployment, pricing, zh-TW UI (as of 2026-11-11)

### Takeaway
All four main candidates were actively developed in the week before 2026-11-11 (commits dated 2026-11-10/11). Maybe Finance has been archived since 2025-07-27, and Sure is its active AGPL fork. On language, zh-TW is a full UI locale in Wealthfolio (`zh-Hant`), PP (`zh_TW`, near-complete) and Sure (`zh-TW`). Ghostfolio has only a single `zh` locale, believed to be Simplified, and a user has asked for a separate zh-TW.

### Cited Findings
**Ghostfolio** (Ghostfolio, Switzerland; main maintainer GitHub user dtslvr)
- **License and size:** AGPL-3.0; ~9.7k stars, ~1.4k forks, 6,045 commits on main — [repo](https://github.com/ghostfolio/ghostfolio).
- **Latest release:** 3.99.0 (2026-11-07). The release cadence is several per week: 3.94.0 2026-10-28 → 3.99.0 2026-11-07 — [CHANGELOG](https://github.com/ghostfolio/ghostfolio/blob/main/CHANGELOG.md); [releases](https://github.com/ghostfolio/ghostfolio/releases).
- **Stack:** NestJS + PostgreSQL/Prisma + Redis backend; Angular/Angular Material frontend; Nx/TypeScript.
- **Deployment:**
  - Docker images for amd64, arm/v7 and arm64, and Docker Compose
  - Community packages for CasaOS, Easypanel, Home Assistant, Runtipi, TrueCharts, Umbrel, Unraid
  - PWA (no native mobile app)
  - Source: [repo](https://github.com/ghostfolio/ghostfolio); [README](https://github.com/ghostfolio/ghostfolio/blob/main/README.md)
- **Hosted "Ghostfolio Premium" price:** not confirmed from the official page (unreachable). Third-party listings conflict: ~$40/yr ([gappsy](https://gappsy.com/tools/ghostfolio/)), $48/yr ([findmymoat, checked 2026-08](https://www.findmymoat.com/vs/ghostfolio-vs-wealthfolio)), $15/yr (likely outdated, [SourceForge](https://sourceforge.net/software/product/Ghostfolio/)).
- **UI locales:** `ca, de, es, fr, it, ja, ko, nl, pl, pt, tr, uk, zh` plus English (`messages.xlf`) — [locales](https://github.com/ghostfolio/ghostfolio/tree/main/apps/client/src/locales). Chinese (`zh`) was set up in 2.70.0 (2024-04-02), Korean in 2.230.0 (2026-01-14), Japanese in 3.18.0 (2026-06-28) — [CHANGELOG](https://github.com/ghostfolio/ghostfolio/blob/main/CHANGELOG.md).
- **zh-TW request:** in [#6202](https://github.com/ghostfolio/ghostfolio/issues/6202) (opened 2026-01-17, closed 2026-07-09 via PR #6835), commenter poterkao asked for separate zh-TW/zh-CN files because Ghostfolio uses a single "zh". The thread does not show that a split was adopted, and the current tree has only `messages.zh.xlf`.

**Wealthfolio** (creator Aziz Fadil, GitHub `afadil`; now the `wealthfolio` org)
- **License and size:** AGPL-3.0; ~9.4k stars, 811 forks, 5,830 commits, 448 open issues — [repo](https://github.com/wealthfolio/wealthfolio).
- **Latest release:** v3.12.0 (2026-11-01). Earlier: v3.11.0 2026-10-23, v3.10.0 2026-10-14, v3.9.x late Sep 2026 — [releases](https://github.com/wealthfolio/wealthfolio/releases).
- **Stack:** Tauri + Rust + SQLite/Diesel backend; React/Tailwind/shadcn frontend — [repo](https://github.com/wealthfolio/wealthfolio).
- **Deployment:**
  - Desktop for Windows, macOS 12+, Linux
  - iOS/iPadOS 16+ (App Store) and Android 7+ (Google Play)
  - Self-hosted Docker/web mode with a REST API (`wealthfolio/wealthfolio:latest`)
  - OIDC SSO option
  - Source: [README](https://github.com/wealthfolio/wealthfolio/blob/main/README.md)
- **Wealthfolio Connect** (optional paid subscription for broker sync, E2E device sync, household sharing): the official price was not confirmed. Third-party listings conflict: Essentials $7.99/mo, Duo $12.99/mo, Plus $24.99/mo ([toolradar, updated 2026-02](https://toolradar.com/tools/wealthfolio/pricing)), vs. "custom pricing / not publicly listed" in later reviews ([findmymoat](https://www.findmymoat.com/tools/wealthfolio)). The README says Connect is optional and that "manual tracking and CSV import are free" — [README](https://github.com/wealthfolio/wealthfolio/blob/main/README.md).
- **UI languages ("11 Languages"):** `ar, de, en, es, fr, it, ja, ko, pt, zh, zh-Hant` — [i18n/locales](https://github.com/wealthfolio/wealthfolio/tree/main/apps/frontend/src/i18n/locales).
  - The code deliberately uses `zh-Hant` so "one catalog serves Taiwan, Hong Kong and Macau" — [locales.test.ts](https://github.com/wealthfolio/wealthfolio/blob/main/apps/frontend/src/i18n/locales.test.ts).
  - The zh-Hant catalog is ~580 KB vs 596 KB for English (near parity), with Taiwan terms such as 帳戶 and 新增帳戶.

**Portfolio Performance** (lead maintainer Andreas Buchen, GitHub `buchen`)
- **License and size:** EPL-1.0 (Eclipse Public License); ~4.2k stars, 841 forks, 8,609 commits — [repo](https://github.com/portfolio-performance/portfolio).
- **Latest release:** 0.90.0 (2026-11-01); 0.89.0 2026-10-11; 0.88.0 2026-10-04; 0.87.0 2026-08-16 — [metainfo](https://github.com/portfolio-performance/portfolio/blob/master/portfolio-product/metainfo/info.portfolio_performance.PortfolioPerformance.metainfo.xml).
- **Stack:** Java / Eclipse RCP desktop app, with a REST module that hosts the MCP endpoint — [repo](https://github.com/portfolio-performance/portfolio).
- **Translations:** `ca cs da de es fi fr it nl pl pt pt_BR ru sk tr vi zh zh_TW`. The zh_TW UI bundle has 1,540 keys vs 1,549 in English (≈99%), e.g. LabelTTWROR = 真實時間加權回報率（累積）, LabelIRR = 內部回報率（IRR） — [messages_zh_TW.properties](https://github.com/portfolio-performance/portfolio/blob/master/name.abuchen.portfolio.ui/src/name/abuchen/portfolio/ui/messages_zh_TW.properties).

**Maybe Finance** (maybe-finance/maybe)
- **Status:** "archived by the owner on Jul 27, 2025. It is now read-only"; "no longer actively maintained". Final release v0.6.0.
- **License and size:** AGPL-3.0; ~54.2k stars, 5.7k forks.
- **Fork rules:** forks may not use the "Maybe" name or logo.
- Source: [repo](https://github.com/maybe-finance/maybe)

**Sure** (we-promise/sure; community fork of Maybe)
- **License and size:** AGPL-3.0; ~12.6k stars, 934 forks, 4,101 commits, 478 open issues — [repo](https://github.com/we-promise/sure).
- **Latest release:** stable v0.7.6 (2026-10-31). Newer alphas: v2026.11.3-alpha, v2026.11.8-alpha, v2026.11.10-alpha (2026-11-10), with CalVer tags plus compatibility aliases (v0.7.7-alpha.x) — [releases](https://github.com/we-promise/sure/releases).
- **Stack:** Ruby on Rails app with PostgreSQL, Redis and Sidekiq.
- **Deployment:**
  - Docker self-host
  - Render one-click (No AI / Simple AI / External AI)
  - PikaPods, Hostim, Helm chart
  - Clients: browser, macOS desktop app, mobile app, API, LLM agents
  - Source: [repo README](https://github.com/we-promise/sure)
- **UI language:** `SUPPORTED_LOCALES` includes `zh-CN` (简体中文) and `zh-TW` (繁體中文) — [languages_helper.rb](https://github.com/we-promise/sure/blob/main/app/helpers/languages_helper.rb). The repo has 142 `zh-TW` locale files vs 175 `en` files under `config/locales`, so coverage is high but incomplete — [config/locales](https://github.com/we-promise/sure/tree/main/config/locales).

**Investbrain**
- ~940 stars, 76 forks, 848 commits. Laravel/PHP + Docker; hosted "Investbrain Cloud" at investbra.in. The license file exists but its type was not shown — [repo](https://github.com/investbrainapp/investbrain).

**Excluded**
- **Rotki** (crypto-focused, privacy-preserving accounting) and **Firefly III** (budgeting/double-entry, not a stock tracker) were not evaluated further. Firefly III does not price securities. These exclusions are background knowledge; neither repo was fetched in this session.

### Inferences
- **Overall fit for a Taiwan-primary investor who wants AI** (an inference from the findings above; ranking not tested hands-on):

| Project | 台股 data fit | Custom TWSE/TPEx feed | zh-TW UI | Perf metrics | Holdings-only entry | In-app AI / local LLM | MCP | Form factor | License |
|---|---|---|---|---|---|---|---|---|---|
| Wealthfolio | Strong: explicit XTAI→.TW, ROCO→.TWO, TWD | Yes (JSON/HTML/CSV) | Yes (zh-Hant) | TWR+MWR, benchmarks, FIRE, rebalancing | Yes (HOLDINGS mode) | Yes; Ollama/OpenAI/Anthropic/Google/Groq/OpenRouter | Yes | Desktop + iOS/Android + Docker | AGPL-3.0 |
| Portfolio Performance | Strong: yahoo.TW/.TWO labels incl. zh_TW | Yes (JSON/HTML table) | Yes (~99%) | TTWROR, IRR, Sharpe, MDD, volatility | Workaround | No | Yes (exp., loopback) | Desktop only (Java) | EPL-1.0 |
| Ghostfolio | OK via Yahoo | Yes (MANUAL + JSONPath scraper) | No (single zh) | ROAI, benchmarks, FIRE, risk rules | Workaround | Copy-prompt + OpenRouter | Yes (exp.) | Web/PWA, Docker | AGPL-3.0 |
| Sure | Weak: no XTAI/ROCO Yahoo suffix config | No (code only) | Yes (partial) | MWR, allocation (new/alpha) | Cost-basis editor | Yes; OpenAI-compatible (Ollama) / Anthropic | Yes (OAuth) | Web, Docker, macOS/mobile clients | AGPL-3.0 |
| Maybe | Archived 2025-07-27 | — | — | — | — | — | — | — | AGPL-3.0 |

- **Open core and SaaS:** all are fully open-source rather than source-available. Ghostfolio and Wealthfolio monetize via optional hosted or paid services (Ghostfolio Premium data provider; Wealthfolio Connect sync). That makes them "open core"-like in practice: the paid parts are data and sync services, not code paywalls.

### Gaps
- Exact star counts are rounded from github.com pages; the GitHub API was blocked in this session.
- Official SaaS prices (Ghostfolio Premium, Wealthfolio Connect, Investbrain Cloud) could not be verified from the vendors' sites (domains unreachable), and third-party figures conflict.
- Commit counts per month and maintainer lists (beyond lead maintainers) were not gathered.
- Tickerlake and other named candidates were not found or verified in this session.
