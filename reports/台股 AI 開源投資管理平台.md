# 拼裝三層開源積木，打造台股 AI 投資平台

截至 2026 年 11 月，**沒有任何一個開源專案同時做到三件事**：完整支援台股、內建 AI 分析、正確計算持倉績效。最接近一站式的 daily_stock_analysis（MIT，約 69.9k★）已支援 `.TW`／`.TWO` 與三大法人資料，但官方文件直接寫明「台股 Portfolio 當前屬於 partial valuation 市場」，介面也只有簡中與英文。因此最實際的做法是分三層拼裝。**持倉帳本用 Wealthfolio**：它內建 TWSE→`.TW`、TPEx→`.TWO`、TWD 的對應，有繁中介面，提供 TWR＋MWR，可以只輸入目前持股，並內建 AI 助理與 MCP。**台股資料層用 TWSEMCPServer 與 FinMind-MCP**，涵蓋三大法人、月營收、財報、本益比與股價淨值比。**AI 層用支援 MCP 的 LLM 用戶端**做日常的繁中對話分析，再定期把持倉 JSON 交給 TradingAgents（Apache-2.0），產生多代理人報告。整套都能自架，軟體免費，主要花費是 LLM 用量。另有兩項現成專案都做不到。第一，Yahoo 股市那種本益比、股價淨值比的估值頁，開源界沒有現成頁面，只能靠 MCP 查詢或自己畫圖，不過底層資料可以從 TWSE、TPEx 與 FinMind 免費取得。第二，手續費 0.1425%、證交稅 0.3%／0.1%、二代健保 2.11% 這類台股規則，國際追蹤工具都不會自動計算，必須手動記錄或在匯入前先處理。台灣在地的 AssetPilot 能全部自動算，但只有一位維護者、1 顆星。

## 四類候選各缺一角，沒有專案同時滿足台股、AI 與績效

候選專案可以分成四類，每一類都缺一塊：

- **國際投資組合追蹤工具**（Wealthfolio、Portfolio Performance、Ghostfolio、Sure）：績效計算最嚴謹，2026 年也都加上了 MCP 端點，但沒有台股稅費邏輯，也沒有估值頁。
- **華語圈一站式 AI 平台**（daily_stock_analysis、PanWatch、go-stock）：AI 報告、推播與持倉整合得最好，但除了 daily_stock_analysis 之外都不支援台股。
- **台灣原生專案**（AssetPilot、StackWorth、twstock-research、EquiLens）：台股會計細節處理得最正確，但幾乎都是 0 到 50 顆星的個人專案。
- **AI 分析框架**（TradingAgents 等）：會深度分析單一個股，但不是帳本。

下表比較持倉類候選。AI 框架與資料層分別在後兩節比較。

| 專案 | 台股支援 | AI 功能 | 持倉與績效 | 授權 | 活躍度（2026-11） | 部署 |
|---|---|---|---|---|---|---|
| **Wealthfolio** | 強：內建 XTAI→`.TW`、ROCO→`.TWO`、TWD；繁中介面；可自訂 JSON/HTML/CSV 報價源 | 內建 AI 助理（含本機 Ollama）、AI CSV 匯入、MCP | TWR＋MWR、任意基準、四種成本法、可只輸入現有持股 | AGPL-3.0 | v3.12.0（11/01），約 9.4k★ | 桌面三平台、iOS／Android、Docker |
| **Portfolio Performance** | 強：有 yahoo.TW／.TWO 交易所標籤，繁中翻譯約 99% | 只有實驗性 MCP（僅限本機） | TTWROR＋IRR、Sharpe、最大回撤、波動度 | EPL-1.0 | 0.90.0（11/01），約 4.2k★ | Java 桌面版 |
| **Ghostfolio** | 可用：經 Yahoo 抓價；也可用 MANUAL 加 JSONPath 自訂來源 | 複製 AI 提示詞、OpenRouter、AI 匯入交易、實驗性 MCP | ROAI（不是 TWR／IRR）、基準、FIRE、風險規則 | AGPL-3.0 | 3.99.0（11/07），約 9.7k★ | Docker（含 ARM）、NAS 套件、PWA |
| **Sure**（Maybe 分支） | 弱：Yahoo 交易所對照表缺 XTAI／ROCO | 內建聊天、MCP（OAuth） | MWR、資產配置（新功能，仍是 alpha） | AGPL-3.0 | v0.7.6（10/31）＋11/10 alpha，約 12.6k★ | Docker、Render、Helm |
| **daily_stock_analysis** | 中：支援 `.TW`／`.TWO` 與三大法人，但台股持倉估值不完整 | AI 決策報告、Agent 問股、持股旁顯示訊號、多通道推播 | FIFO／均價、交易、現金、公司行動、風險摘要 | MIT | 11/10 有推送，約 69.9k★ | GitHub Actions、Docker、FastAPI |
| **PanWatch** | 不支援（只有中、港、美） | 可從持股一鍵啟動 TradingAgents 分析 | 多券商帳戶損益 | MIT | 11/08 有推送，約 2.4k★ | Docker、PWA |
| **go-stock** | 不支援 | AI Agent、可掛 MCP；部分功能要付費 VIP | 弱 | GPL-3.0 | 11/10 有新版，約 8.1k★ | Windows 桌面版 |
| **AssetPilot** | 最完整：TWSE／TPEx 報價、除權息自動同步 | MCP（OAuth 2.1） | FIFO 逐筆損益、自動計算手續費與證交稅 | AGPL-3.0 | v4.112.3（11/06），★1 | Docker、Web、Android |
| **StackWorth** | 台股＋美股 ETF，全部以 TWD 計價 | 無 | XIRR＋TWR、扣除現金流影響的回撤 | MIT | 11/09 有推送，★1 | Next.js＋Supabase PWA |
| **Investbrain** | 未提及亞洲市場 | AI 聊天、MCP | 支援交易匯入 | CC BY-NC 4.0（不屬於 OSI 開源） | 11/11 有推送，940★ | Docker、雲端版 |

表中資料的出處：Wealthfolio 的交易所對照寫在 [exchanges.json](https://github.com/wealthfolio/wealthfolio/blob/main/crates/market-data/src/resolver/exchanges.json)，版本紀錄見 [releases](https://github.com/wealthfolio/wealthfolio/releases)。Portfolio Performance 的版本見 [release notes](https://github.com/portfolio-performance/portfolio/blob/master/portfolio-product/metainfo/info.portfolio_performance.PortfolioPerformance.metainfo.xml)，Ghostfolio 見 [CHANGELOG](https://github.com/ghostfolio/ghostfolio/blob/main/CHANGELOG.md)。daily_stock_analysis 的台股範圍寫在 [market-support.md](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/market-support.md)。AssetPilot 見 [GitHub](https://github.com/es94111/AssetPilot)，Investbrain 的授權見 [LICENSE.md](https://github.com/investbrainapp/investbrain/blob/main/LICENSE.md)。

### 對照 Google Finance 與 Yahoo 股市

如果拿你提到的兩個產品來對照，結果很明確：

- **Google Finance 的 portfolio 功能**：開源界已有成熟替代品。Ghostfolio 是 Web／PWA 形式，Wealthfolio 是桌面加手機 App。
- **Yahoo 股市的「價格估值」頁**（個股本益比、股價淨值比的歷史區間）：**沒有任何候選專案把它做成功能**。研究者翻遍各一站式專案的文件，都沒有找到本益比或股價淨值比河流圖。

估值頁的原始資料其實都是免費的官方開放資料：

- 上市股票：TWSE OpenAPI 的 `BWIBBU_ALL` 與 `BWIBBU_d`，提供個股日本益比、殖利率及股價淨值比（[TWSE swagger 摘要](https://github.com/twjackysu/TWSEMCPServer/blob/master/staticFiles/swagger_api_summary.json)）。
- 上櫃股票：TPEx 的 `tpex_mainboard_peratio_analysis`（[data.gov.tw](https://data.gov.tw/dataset/11633)）。
- 完整歷史：FinMind 免費方案就有 `TaiwanStockPER` 資料表（[FinMind Pricing](https://finmind.github.io/Pricing/)）。

要注意的是，證交所的本益比是用收盤價除以近四季 EPS，**EPS 小於等於 0 時就不計算**（[TWSE](https://www.twse.com.tw/zh/trading/historical/bwibbu.html)）。所以虧損公司的估值區間會有空白。換句話說，在開源組合裡，「估值頁」比較像是透過 MCP 發出的一個查詢，而不是一個現成的網頁。

### 可以先排除的專案

- **Sure**：Yahoo 對照表沒有 XTAI／ROCO。程式碼註解自己寫明，缺少交易所代碼的非美股會送出不帶後綴的代號，結果是 404，而且「never gets a price」（[yahoo_finance.rb](https://github.com/we-promise/sure/blob/main/app/models/provider/yahoo_finance.rb)）。
- **Maybe Finance**：2025-07-27 已封存（[repo](https://github.com/maybe-finance/maybe)）。
- **PanWatch 與 go-stock**：都完全不支援台股。go-stock 的背景買賣訊號監控還要 VIP2 以上的贊助者才能用（[go-stock README](https://github.com/ArvinLovegood/go-stock/blob/dev/README.md)）。
- **Investbrain**：CC BY-NC 授權禁止商業使用，不屬於 OSI 定義的開源。

## Wealthfolio 最懂 .TW/.TWO，但台股稅費仍得自己記

### Wealthfolio

Wealthfolio 是目前最適合台股投資人的帳本。

- **台股代號與交易時間**：交易所登錄檔把 `XTAI` 對應到 Yahoo 後綴 `.TW`，把 `ROCO`（櫃買中心）對應到 `.TWO`，幣別都是 TWD。它也知道時區是 Asia/Taipei、收盤時間是 13:30（[exchanges.json](https://github.com/wealthfolio/wealthfolio/blob/main/crates/market-data/src/resolver/exchanges.json)）。
- **繁中介面**：使用 `zh-Hant` 語系，讓同一份翻譯同時服務台灣、香港與澳門（[locales.test.ts](https://github.com/wealthfolio/wealthfolio/blob/main/apps/frontend/src/i18n/locales.test.ts)）。v3.12.0 另外加入「紅漲綠跌」配色選項（[releases](https://github.com/wealthfolio/wealthfolio/releases)）。
- **績效計算**：提供 **true time-weighted 與 money-weighted returns**，可以和任意基準比較，支援 FIFO、加權平均、LIFO、HIFO 四種成本法（[README](https://github.com/wealthfolio/wealthfolio/blob/main/README.md)）。有台灣使用者要求用 0050.TW 當基準，已在 v1.1.3 以後解決（[#259](https://github.com/wealthfolio/wealthfolio/issues/259)）。
- **可以只輸入目前持股**：帳戶有 `TRANSACTIONS` 與 `HOLDINGS` 兩種追蹤模式。選 HOLDINGS 就只需要輸入現有持股（[tracking-mode-badge.tsx](https://github.com/wealthfolio/wealthfolio/blob/main/apps/frontend/src/components/tracking-mode-badge.tsx)）。
- **交易類型**：有獨立的 `TAX`、`FEE` 類型，以及 `DIVIDEND_IN_KIND`（配股）子類型（[activities_constants.rs](https://github.com/wealthfolio/wealthfolio/blob/main/crates/core/src/activities/activities_constants.rs)）。這是幾個國際工具中最能乾淨記錄台股稅費與配股的資料模型。
- **AI 功能**：內建 AI 助理，支援 ollama、groq、google、anthropic、openai、openrouter 六種供應商（[ai_providers.json](https://github.com/wealthfolio/wealthfolio/blob/main/crates/ai/src/ai_providers.json)）。v3.11.0 加入「AI Agent Access」，提供 Claude Code、Codex、ChatGPT 桌面版與 Cursor 的現成設定。
- **自訂報價源**：可設定 JSON、HTML 或 CSV 來源，搭配 JSONPath 或 CSS selector 取值（[custom_provider/model.rs](https://github.com/wealthfolio/wealthfolio/blob/main/crates/core/src/custom_provider/model.rs)）。Yahoo 抓不到價格時，可以改接 TWSE 或 TPEx 的 JSON。

它也有風險。以 TWD 為基準幣的使用者回報過幾個績效計算錯誤：

- 現金餘額單日為負時，TWR 變成空值（[#1425](https://github.com/wealthfolio/wealthfolio/issues/1425)）。
- 各帳戶起始日不同時，整體 TWR 算錯（[#1414](https://github.com/wealthfolio/wealthfolio/issues/1414)）。
- 非基準幣帳戶的績效歸因對不起來（[#1473](https://github.com/wealthfolio/wealthfolio/issues/1473)）。

另外，研究者沒有實際確認兩件事：AI 助理在 Docker／網頁版能不能用，以及它會不會自動建立台股股利紀錄。

### Portfolio Performance

Portfolio Performance 的績效指標最嚴謹。它有 TTWROR（真實時間加權報酬）、IRR、最大回撤、最大回撤期間與 Sharpe ratio（[messages.properties](https://github.com/portfolio-performance/portfolio/blob/master/name.abuchen.portfolio.ui/src/name/abuchen/portfolio/ui/messages.properties)）。0.90.0 版加入年化波動度，並修正 Sharpe 的計算。

- **繁中化**：台灣翻譯涵蓋 1,540 個介面字串，英文版是 1,549 個（[messages_zh_TW.properties](https://github.com/portfolio-performance/portfolio/blob/master/name.abuchen.portfolio.ui/src/name/abuchen/portfolio/ui/messages_zh_TW.properties)）。交易所選單直接寫「臺灣證券交易所」與「臺灣證券櫃檯買賣中心」。
- **還原價與原始價**：可以分別選 Yahoo 的原始價或還原價報價源。
- **限制**：只有 Java 桌面版，沒有 App 內的 LLM 聊天。0.89.0 加入的 MCP 端點仍標示為實驗性，只接受本機連線，認證方式是 REST API bearer token（[ADR 0005](https://github.com/portfolio-performance/portfolio/blob/master/docs/adr/0005-authenticate-the-mcp-endpoint-with-rest-api-tokens.md)）。
- **第三方 MCP**：社群的 [Nokke32/pp-mcp](https://github.com/Nokke32/pp-mcp)（MIT）可以唯讀讀取 `.portfolio` 檔，計算已實現與未實現損益，也能模擬賣出。

### Ghostfolio

Ghostfolio 最像 Google Finance 的網頁體驗。它提供多架構 Docker 映像，也有 CasaOS、Unraid、Umbrel 等 NAS 套件，以及 PWA（[README](https://github.com/ghostfolio/ghostfolio/blob/main/README.md)）。對台股投資人來說有三個缺點：

1. **績效指標**：它主打的是 **ROAI（平均投入報酬），不是 TWR 也不是 IRR**。
2. **交易類型太少**：只有 `BUY, DIVIDEND, FEE, INTEREST, LIABILITY, SELL` 六種（[schema.prisma](https://github.com/ghostfolio/ghostfolio/blob/main/prisma/schema.prisma)）。配股只能記成 0 元買進，會扭曲報酬與投入金額圖表。
3. **語系**：只有一個 `zh` 語系。已有台灣使用者要求拆出 zh-TW（[#6202](https://github.com/ghostfolio/ghostfolio/issues/6202)），但目前程式碼裡仍只有一份 `messages.zh.xlf`。

它的 AI 功能都還是實驗性質：

- 「複製 AI 提示詞到剪貼簿」。
- 透過 OpenRouter 的 AI 服務。
- 用 AI 從 CSV、PDF 或圖片匯入交易（3.84.2）。
- 3.59.1 起提供的 MCP 伺服器，有「Restricted view」等權限分級，3.99.0 再加入 OAuth 2.1 探索端點（[CHANGELOG](https://github.com/ghostfolio/ghostfolio/blob/main/CHANGELOG.md)）。

### 台股會計細節：國際工具全部要手動處理

台股特有的稅費規則，國際工具都沒有寫進程式。下表整理各項規則與處理方式：

| 台股細節 | 規則 | 國際工具的處理 | 台灣專案的處理 |
|---|---|---|---|
| 手續費 | 0.1425% × 券商折扣，多數券商最低 NT$20 | 每筆交易手動填入 fee | AssetPilot 自動計算（可手動覆寫）；stock-ledger 可設定折扣 |
| 證交稅 | 賣出時課徵：股票 0.3%、ETF 0.1%、當沖 0.15%（減半延長至 2027-12-31） | Ghostfolio 併入 fee；Wealthfolio 可記成 `TAX` | AssetPilot、stock-ledger 自動計算 |
| 配股 | 以面額 10 元計，每 1 元股票股利配 0.1 股 | Wealthfolio 用 `DIVIDEND_IN_KIND`；Ghostfolio 只能記 0 元買進 | AssetPilot 有股票股利欄位 |
| 二代健保 | 單筆股利達 NT$20,000 時扣 2.11% | 手動記成 TAX／FEE | 只有 twstock-calc 計算機會算 |
| 股利所得稅 | 合併計稅（8.5% 抵減，上限 NT$80,000）或分離課稅 28% | 無 | 只有 twstock-calc 計算機會算 |
| 零股 | 以股數計，1 張＝1,000 股 | 直接記股數即可；匯入前要把「張」換算成股 | — |

規則來源：當沖稅率見 [Focus Taiwan](https://focustaiwan.tw/business/202412310013)，二代健保見 [TVBS](https://news.tvbs.com.tw/politics/3037184)，各專案的處理方式見 [AssetPilot](https://github.com/es94111/AssetPilot)、[stock-ledger](https://github.com/DunkLiao/stock-ledger)、[twstock-calc](https://github.com/muzsor/twstock-calc)。

還有一個容易出錯的地方：**還原價會重複計算股利**。Yahoo 的「Adj Close」會往回調整除權息，如果又另外記一筆現金股利，報酬就算了兩次（[Yahoo 歷史頁](https://ca.finance.yahoo.com/quote/715565.TWO/history/)）。正確做法是用原始價格，再加上明確的股利與配股事件。

最後，**沒有任何國際工具內建元大、富邦、國泰、永豐等台灣券商的對帳單匯入器**。實際可行的方法是先自己處理 CSV，或用 Wealthfolio 的 AI CSV 匯入。

## TradingAgents 是唯一吃得進真實持倉的多代理人框架

### TradingAgents 的基本能力

TradingAgents（Apache-2.0）的分析流程分成三段。第一段，四個分析師代理人同時處理基本面、情緒、新聞與技術面。第二段，多空研究員互相辯論。第三段，交易員、風險團隊與投資組合經理依序做出決策（[README](https://github.com/TauricResearch/TradingAgents/blob/main/README.md)）。

它和台股相關的關鍵能力有：

- **可以帶入真實持倉**：自 v0.5.0（2026-09-18）起，可以把 `PortfolioContext`（現金、幣別、持股與均價）傳進去，讓交易員、風險分析師與投資組合經理「work against your actual book」。CLI 用法是 `tradingagents --portfolio my_book.json`。資料模型是「broker-neutral」，幣別只是自由標籤，填 TWD 也可以（[portfolio.py](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/portfolio.py)）。
- **台股基準**：v0.5.2 起，`.TW` 與 `.TWO` 都以加權指數 `^TWII` 當比較基準（[default_config.py](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/default_config.py)）。
- **繁中輸出**：用環境變數 `TRADINGAGENTS_OUTPUT_LANGUAGE` 指定（[context.py](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/context.py)）。
- **LLM 選擇**：支援從 OpenAI、Anthropic 到本機 Ollama 的十多家供應商。v0.7.0 還能直接用 ChatGPT Plus／Pro 訂閱，不需要 API key（[CHANGELOG](https://github.com/TauricResearch/TradingAgents/blob/main/CHANGELOG.md)）。

### 在台股上的限制

它的台股資料完全來自 Yahoo，因此有明顯缺口：

- **資料來源沒有台灣**：內建資料供應商只有 alpha_vantage、fred、polymarket、reddit、sec_edgar、stocktwits、yahoo（[vendors](https://github.com/TauricResearch/TradingAgents/tree/main/tradingagents/dataflows/vendors)）。
- **非美股的歷史回測拿不到財報**：非美國公司的財報來自 Yahoo。若分析日期在過去，系統會刻意隱藏財報，因為 Yahoo 無法說明哪些數字當時已經公開。
- **社群情緒是空的**：社群 PR 指出，StockTwits 與 Reddit 上的台股討論「mostly empty or off-topic」（[PR #1348](https://github.com/TauricResearch/TradingAgents/pull/1348)）。
- **缺台股特有資料**：分析時拿不到月營收、三大法人、融資融券、集保與中文新聞。

有兩個社群 PR 想補上台股資料，上游都沒有合併：

- 完整的台股資料供應商 PR [#1159](https://github.com/TauricResearch/TradingAgents/pull/1159)：涵蓋 TWSE／TPEx 價格、月營收與官方財報，結果沒有合併就關閉。
- PR #1348：只有台股基準這部分被採用。

繁中支援也類似。CLI 選單只有「Chinese (中文)」，新增繁體選項的 PR #1534 被關閉。預設輸出 zh-TW、可以直接輸入數字代號的 [Mai0313 分支](https://github.com/Mai0313/TradingAgents/blob/main/README.md)則已經封存。

研究者也沒有確認投資組合經理的提示詞會不會考量其他持股（例如產業集中度），還是只看被分析的那一檔。

### 成本與定位

成本方面，官方沒有公布數字，第三方估計如下：

- 每檔個股約 **US$0.20–0.80**（gpt-4o 搭配 gpt-4o-mini，一輪辯論）（[Railway](https://railway.com/deploy/trading-agents.md)）。
- 每次決策約 **US$0.50–2.00**（[ToolBrain](https://toolbrain-astro.pages.dev/blog/tauric-tradingagents-review-2026/)）。
- 多空辯論的花費是分析師階段的 3 到 5 倍（[Apidog](https://apidog.com/blog/tradingagents-multi-agent-llm-trading/)）。

照這些估計推算，20 檔持股每天全跑一次，用頂級模型每天約 US$5–20。比較合理的頻率是每週跑一次，或在財報、月營收公布時才跑。

GitHub 頁面顯示 TradingAgents 約有 122k★。研究者認為這個數字異常偏高，但無法用 API 交叉驗證，所以不宜把星數當成品質指標。專案自己的免責聲明寫明它只供研究，「not intended as financial, investment, or trading advice」。

### daily_stock_analysis：AI 和持倉整合得最好的一站式選擇

如果你想要「一個 App」就有 AI 和持倉，daily_stock_analysis 是 AI 整合最深的選擇。

- **持倉頁可以直接問 AI**：每筆持股都能單獨送去做 AI 分析，最新的 AI 決策訊號會顯示在持股旁邊。風險 API 還會彙總持股上的賣出、減碼與警示訊號（[full-guide.md](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/full-guide.md)）。
- **台股資料**：`TwInstitutionalFetcher` 會從 TWSE T86 與 TPEx 抓三大法人買賣超，放進 LLM 提示詞。提示詞也改用台股的語境：新台幣、漲跌幅 ±10%、三大法人。
- **台股還不支援的部分**：持倉的 TWD 估值、台股大盤復盤、台股自動補完、LINE 推播（[market-support.md](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/market-support.md)）。

它也有明確的台灣使用者訊號：

- 社群提出的三大法人功能（[#1777](https://github.com/ZhuLinsen/daily_stock_analysis/issues/1777)）已經上線。
- 2026-11-10 有人用繁中提出「大盤復盤能否增加台股選項」（[#2482](https://github.com/ZhuLinsen/daily_stock_analysis/issues/2482)），已有對應的 PR。

| AI 框架 | 台股可用程度 | 能否帶入持倉 | 繁中輸出 | 授權 | 活躍度（2026-11） |
|---|---|---|---|---|---|
| TradingAgents | 可跑 `.TW`／`.TWO`（Yahoo）；以 TAIEX 為基準；缺月營收、法人、中文新聞 | 可以，JSON 持倉 | 自訂語言 | Apache-2.0 | v0.7.1（10/27） |
| daily_stock_analysis | `.TW`／`.TWO`＋三大法人 | 內建持倉帳本 | 只有簡中／英文介面 | MIT | 11/10 |
| TradingAgents-CN | 只支援 A 股 | 有持倉分析，但限 A 股 | 簡中 | 核心 Apache；App 部分為專有授權 | v3.0.0（9/22） |
| FinRobot | 資料來源含 yfinance，台股未經測試 | 否 | `--lang zh` | Apache-2.0 | 10/24 |
| ai-hedge-fund | 資料以美股為主 | 只追蹤自己的模擬基金 | 否 | MIT | 11/09 |
| OpenBB | 沒有台股供應商 | 否 | 否 | Apache-2.0（yfinance 外掛為 AGPL） | 11/11 |

表格出處：[TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN/blob/v3.0/README.md)、[FinRobot](https://github.com/AI4Finance-Foundation/FinRobot/blob/master/README.md)、[ai-hedge-fund](https://github.com/virattt/ai-hedge-fund/blob/main/README.md)、[OpenBB](https://github.com/OpenBB-finance/OpenBB/blob/develop/README.md)。

FinGPT、FinMem、FinRL 都是研究用的程式碼，不是給一般使用者的分析工具。其中 FinMem 自 2024 年 8 月起就沒有更新。ValueCell 也已停滯約 8 到 9 個月，並轉向託管服務。

## 台股資料層：一個免費 MCP 就補齊法人、月營收與本益比

台灣開源生態最強的不是投資組合追蹤工具，而是資料與 MCP 這一層。

### TWSEMCPServer：最完整的台股 MCP

[twjackysu/TWSEMCPServer](https://github.com/twjackysu/TWSEMCPServer)（MIT，★186）是目前覆蓋最完整的台股 MCP 伺服器。它彙整了：

- TWSE 與 TPEx 的 OpenAPI，以及 TAIFEX 資料。
- 公開資訊觀測站：財報、現金流量、月營收、多年股利、法說會、重大訊息、內部人持股與庫藏股。
- 集保股權分散，含 13 週趨勢。
- ETF 的折溢價、成分股與單位數變化。
- 景氣燈號、PMI 與央行匯率。

它提供免費的託管端點 `https://TW-Stock-MCP-Server.fastmcp.app/mcp`，但有用量上限。用量大時，README 建議改用 Docker 自架。

### FinMind-MCP：正規化的歷史資料

官方的 [FinMind-MCP](https://github.com/FinMind/FinMind-MCP)（Apache-2.0）用 `uvx finmind-mcp` 執行，提供 75 種以上資料集，需要 FinMind token。各方案的費用與限制如下（[FinMind Pricing](https://finmind.github.io/Pricing/)）：

| FinMind 方案 | 月費 | API 上限 | 重點資料 | 商用 |
|---|---|---|---|---|
| Free | 免費 | 300 次／小時（註冊後 600） | 股價、`TaiwanStockPER`、三大報表、月營收、股利政策、除權息結果、新聞 | 不可 |
| Backer | NT$699 | 1,600 次／小時 | 加上還原股價、股權分級 | 不可 |
| Sponsor | NT$999 | 6,000 次／小時 | 加上分點、即時快照 | 不可 |
| Sponsor Pro | NT$3,330 | 20,000 次／小時 | 全部資料 | 可以（SaaS／AI／公司內部使用） |

授權方面有兩條限制。第一，所有方案都禁止轉散布原始資料，也禁止在公開網頁顯示即時資料（[Commercial Use](https://finmind.github.io/CommercialUse/)）。第二，連續出現 4xx 錯誤會被封鎖 IP 30 分鐘（[Ban IP policy](https://finmind.github.io/BanIPPolicy/)）。個人自架、自己使用，用免費方案就夠了。

### 其他台股資料 MCP

| MCP | 授權／星數 | 最後推送 | 特色 |
|---|---|---|---|
| [TWSEMCPServer](https://github.com/twjackysu/TWSEMCPServer) | MIT／186 | 2026-10-22 | 覆蓋最廣，免金鑰，有免費託管端點 |
| [FinMind-MCP](https://github.com/FinMind/FinMind-MCP) | Apache-2.0／5 | 2026-10-31 | 官方版，75 種以上資料集，歷史資料完整 |
| [pipe-stock-analysis](https://github.com/Gratia2533/pipe-stock-analysis) | MIT／24 | 2026-08-08 | 唯讀；FinMind＋Finnhub；Docker Compose 加 OAuth |
| [taux-io/twse-mcp](https://github.com/taux-io/twse-mcp) | MIT／3 | 2026-11-09 | 本益比、股價淨值比、殖利率、除權息預告；自 9/29 起自行累積每日收盤價 |
| [fugle-mcp-server](https://github.com/fugle-dev/fugle-mcp-server) | MIT／10 | 2026-10-23 | 富果官方；可透過台新或富邦 SDK 下單，需要身分證字號與憑證 |

### 資料來源的已知陷阱

- **TWSE OpenAPI 只有最新一天的資料**。歷史資料必須另外從證交所網站的 JSON 端點抓，或自己逐日存檔（[taux-io/twse-mcp](https://github.com/taux-io/twse-mcp)）。
- **請求頻率**：社群經驗是每 5 秒最多 3 次，超過就會被封鎖（[twstock](https://github.com/mlouielu/twstock)）。
- **公開資訊觀測站改版**：新版在 2025-02-23 上線，舊站移到 `mopsov` 並將分階段關閉，依賴網頁結構的爬蟲會失效（[工商時報](https://www.ctee.com.tw/news/20250113700198-439901)）。
- **yfinance 會漏資料**：曾經漏掉 2025-02-20 這一天的 2330.TW 與 1259.TWO（[yfinance #2309](https://github.com/ranaroussi/yfinance/issues/2309)）。
- **即時報價需要授權**：正式的即時或延遲報價需要和證交所簽約付費（[TWSE FAQ](https://www.twse.com.tw/pcversion/en/page/products/info-vendor/faq.html)）。合法的即時報價管道是券商 API。

### 券商 API：自動同步庫存的可行性

如果想自動同步庫存，券商 API 在技術上已經可行：

- **永豐 Shioaji**：`list_positions` 可分別取得整股與零股部位，`list_profit_loss` 可取得已實現損益（[Shioaji 文件](https://sinotrade.github.io/zh/tutor/accounting/position/)）。API key 可以只開「行情＋帳務」權限、不開交易權限，並限制來源 IP（[token](https://sinotrade.github.io/zh/tutor/prepare/token/)）。
- **富邦 Neo**：也提供庫存查詢與已實現、未實現損益查詢。
- **多家彙整**：[goldenegg CLI](https://github.com/joehwang/goldenegg-tw-holdings-cli) 能把富邦、永豐、玉山、台新的庫存彙整給 AI 代理人用，但只支援 macOS ARM64。

它的限制有兩個。第一，這些 API 只提供部位與一段期間的損益，沒有完整的多年交易與股利歷史，所以 TWR 與 XIRR 仍需要帳本來算。第二，串接時必須保存身分證字號、密碼與憑證，只適合純本機部署。

## 推薦組合：Wealthfolio 當帳本、台股 MCP 當眼睛、TradingAgents 當研究團隊

**主推薦是三層組合**：

1. **帳本：Wealthfolio**。它是唯一同時具備台股代號對應、繁中介面、TWR＋MWR、只輸入現有持股模式、本機 LLM，以及有官方設定指南的 MCP 的開源帳本。
2. **資料：TWSEMCPServer 加 FinMind-MCP**。TWSEMCPServer 免金鑰、覆蓋最廣；FinMind-MCP 補足正規化的歷史資料與 `TaiwanStockPER`。
3. **分析：MCP 用戶端加 TradingAgents**。在 Claude Desktop、Claude Code 這類 MCP 用戶端裡同時掛上帳本與資料，讓 LLM 自己把「我的持股」和「法人、月營收、本益比位置」串起來，用繁中做持倉健檢。需要正式研究報告時，再把持倉匯出成 JSON，交給 TradingAgents 做多空辯論。

這個分工的好處是每一層都可以單獨替換。不過三層都在快速演進：Wealthfolio 一個月出了三版，TradingAgents 六週內從 0.5.0 進到 0.7.1，Ghostfolio 與 Portfolio Performance 的 MCP 也都還標示為實驗性。所以介面隨時可能有破壞性變更。

不同需求的替代方案：

| 你的情境 | 推薦組合 | 代價 |
|---|---|---|
| **個人使用、重隱私、要繁中與正確績效（主推薦）** | Wealthfolio＋TWSEMCPServer／FinMind-MCP＋MCP 用戶端＋定期跑 TradingAgents | 稅費要手動記；要自己串三個工具 |
| 想要一個 App 包辦 AI 報告與推播 | daily_stock_analysis | 台股持倉估值不完整、簡中介面、沒有 LINE（可用 webhook 自己轉接） |
| 要網頁版、多裝置、放在 NAS | Ghostfolio＋[ghostfolio-mcp](https://github.com/mhajder/ghostfolio-mcp)（唯讀模式）＋TWSEMCPServer | 指標是 ROAI 而非 TWR；配股要變通；沒有繁中介面 |
| 重視學術級績效指標 | Portfolio Performance＋內建 MCP 或 pp-mcp | 只有桌面版；MCP 只能本機連線，仍屬實驗性 |
| 要台股稅費與除權息全自動 | AssetPilot（用 MCP 接 Claude 或 ChatGPT） | 只有一位維護者、1 顆星，長期維護有風險 |
| 開發者想自建產品 | TradingAgents＋自寫 FinMind 資料供應商（參考 PR #1159）＋參考 AssetPilot／StackWorth 的帳本邏輯 | 要寫程式；FinMind 商用需要 Sponsor Pro |

主推薦組合的上手步驟：

| 步驟 | 動作 | 重點 |
|---|---|---|
| 1. 安裝帳本 | 安裝 Wealthfolio 桌面版，或用 Docker 映像 `wealthfolio/wealthfolio:latest` 自架 | 語言選繁體中文、基準幣選 TWD、開啟紅漲綠跌 |
| 2. 建帳戶 | 只想看現況：選 HOLDINGS 模式，輸入持股與均價。要算 TWR／MWR：選 TRANSACTIONS 模式，匯入券商對帳單 CSV（可用 AI CSV 匯入） | 張數乘以 1,000 換成股數；手續費記 fee；證交稅與二代健保記 `TAX`；配股記 `DIVIDEND_IN_KIND` |
| 3. 確認代號與基準 | 新增 `2330.TW`、`0050.TW`、`00878.TW`、`6488.TWO`，基準設為 `0050.TW` | 若 Yahoo 抓不到價格，用自訂報價源接 TWSE 或 TPEx 的 JSON |
| 4. 讓 AI 讀持倉 | 桌面版：複製「AI Agent Access」提供的設定。自架版：設定 `WF_MCP_ENABLED`、`WF_MCP_ALLOWED_HOSTS` | 先只給唯讀權限，並開啟 `WF_MCP_AUDIT_ENABLED` 稽核紀錄 |
| 5. 掛上台股資料 | 在同一個 MCP 用戶端加入 TWSEMCPServer 與 FinMind-MCP | 免費託管端點有用量上限，用量大時改用 Docker 自架 |
| 6. 日常對話分析 | 用繁中提問，例如「列出我持股目前的本益比在近五年的位置，以及近 20 日三大法人動向」 | LLM 自己合併帳本與市場資料 |
| 7. 定期深度報告 | 匯出持倉 JSON，跑 TradingAgents | 每週一次，或在財報、月營收、除權息前後跑 |

步驟 4 的環境變數見 [Wealthfolio README](https://github.com/wealthfolio/wealthfolio/blob/main/README.md)。

步驟 5 與步驟 7 的指令範例如下。旗標名稱以各專案的 README 為準：

```bash
# 台股資料層（以 Claude Code 為例）
claude mcp add --transport http twse https://TW-Stock-MCP-Server.fastmcp.app/mcp
claude mcp add finmind -e FINMIND_TOKEN=<你的 FinMind token> -- uvx finmind-mcp

# 深度報告（TradingAgents）
export TRADINGAGENTS_OUTPUT_LANGUAGE="Traditional Chinese (Taiwan, 繁體中文)"
tradingagents --ticker 2330.TW --portfolio book.json
```

```json
{
  "cash": 200000,
  "currency": "TWD",
  "positions": [
    {"ticker": "2330.TW",  "quantity": 1000, "average_price": 1000},
    {"ticker": "0050.TW",  "quantity": 3000, "average_price": 50},
    {"ticker": "6488.TWO", "quantity": 200,  "average_price": 400}
  ]
}
```

上面 JSON 裡的數字只是示意。格式依照 TradingAgents 的 `PortfolioContext`：要有 `cash`、`currency` 與 `positions`。注意 positions 是空清單代表「空手」，和完全不傳持倉的意義不同。

使用這個組合時有三件事要注意：

- **隱私**：優先用本機的 MCP 用戶端，並選唯讀範圍，例如 Ghostfolio 的「Restricted view」或 ghostfolio-mcp 的唯讀模式。在意隱私的話，可以讓 Wealthfolio 改用 Ollama 本機模型。
- **授權**：Wealthfolio、Ghostfolio 與 AssetPilot 都是 AGPL-3.0。自己用沒有問題，但如果修改後架成服務給別人用，就必須公開原始碼。FinMind 的非 Pro 方案也只能個人使用。
- **定位**：所有 AI 框架都在免責聲明中排除投資建議。比較適合把它們的報告當成第二意見與檢查清單，而不是下單訊號。

## 結論

這次研究最重要的發現是，「開源版 Yahoo 股市」的形態已經變了。過去大家想找一個什麼都包的 App；到了 2026 年 11 月，Ghostfolio、Wealthfolio、Sure、Portfolio Performance 與 Investbrain 都已內建 MCP 端點，其中 Ghostfolio（8 月）、Wealthfolio 與 Portfolio Performance（10 月）都是近三個月才加入的。帳本因此變成一個可以被 AI 讀取的資料來源，AI 分析則移到 Claude 這類用戶端裡進行。對台股投資人來說，這個轉變剛好放大了台灣生態的優勢。台灣開發者很少做大型追蹤工具，卻做出了 TWSEMCPServer、FinMind-MCP 這類高品質的資料 MCP。因此「國際帳本＋台灣資料 MCP」不是暫時的權宜之計，而是現階段最合理的架構。

真正還沒補上的缺口只有兩個，也很具體。第一個是「台股感知的帳本層」：能自動處理 0.1425% 手續費折扣、0.3%／0.1% 證交稅、配股、二代健保門檻，並解析台灣券商的對帳單。第二個是 TradingAgents 的 FinMind／TWSE 資料供應商：它能補上月營收、三大法人，以及歷史回測時可用的財報。上游兩度關閉相關 PR，代表這類功能會留在 fork 或外掛裡，不會進主線。接下來值得追蹤三件事：Wealthfolio 對台股股利的支援、daily_stock_analysis 補完台股 TWD 持倉估值，以及 AssetPilot 能否擺脫單人維護的風險。只要其中任何一件完成，「單一專案就能滿足」的答案就可能出現。在那之前，用三層組合是最穩健的選擇。
