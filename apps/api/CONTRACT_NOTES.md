# API 合約實作備註

後端依 [`docs/api-contract.md`](../../docs/api-contract.md) 實作，欄位名稱與單位都沒有改。
以下是合約沒寫清楚、我做了解讀，或刻意偏離的地方，前端整合時請留意。

## 與合約範例不同的數字

- **`TradePreview` 範例的手續費**：合約寫 `1,070,000 → fee 427`。依規格「元以下捨去」計算為
  `1,070,000 × 0.1425% × 0.28 = 426.93 → 426`，`net_cash` 也因此是 `-1070426`。範例數字是四捨五入的結果。

## 新增的欄位與端點（不影響既有欄位）

| 位置 | 新增 | 用途 |
|---|---|---|
| `Holding` | `is_demo` | 這一檔的報價是否含模擬資料（`PortfolioSummary.is_demo` 是整體） |
| `DividendRecord` | `is_demo` | 陣列型回應沒有地方放整體的 `is_demo`，所以逐筆標示 |
| `Valuation` | `notes: string[]` | 河流圖的說明，例如「EPS ≤ 0，本益比區間留白」、「ETF 沒有 EPS」、資料來源 |
| `PortfolioSummary.allocation` | `by_account` | 依帳戶配置（規格 4.4 有列） |
| `GET /accounts/{id}/holdings` | 新端點 | 讀回只記持股快照 |
| `PUT /accounts/{id}/holdings` 回應 | `{"account_id", "as_of", "holdings": [...]}` | 合約沒定義回應格式 |
| `GET /transactions/{id}` | 新端點 | 讀單筆交易 |
| `GET /health` | 新端點 | 部署健康檢查，含各資料源狀態 |
| `GET /stream/quotes` | `interval`（1–60 秒）、`once`（送一輪就結束，測試用） | |
| 錯誤 | `error.details`（只有 `validation_error` 有） | 逐欄錯誤：`[{"field": "quantity", "message": "..."}]` |
| `GET /portfolio/performance` | `range=1D`、`range=5D` | 短區間，以交易日計（見下方「績效計算的解讀」） |
| `benchmark`（績效參數與 `Preferences.benchmark`） | `^TAIEXTR`、`^TPEXTR` | 證交所「發行量加權股價報酬指數」、櫃買中心「櫃買報酬指數」（含息），見下方 |

## 欄位語意的解讀

- **數字型別**：`quantity` 一律是 JSON number；整數會輸出成整數（`1000`），但 schema 標成 number。
  金額四捨五入到 2 位、價格 4 位、比率 6 位（例如 `0.048140`）。
- **可能為 `null`**：`Quote.prev_close/change/change_pct/open/high/low/volume/as_of`（資料源沒有時）、
  `Holding.price/prev_close`（沒有報價時以成本計值，並標示 `is_demo`）、各種 `*_pct`（分母為 0）、
  `Performance.twr/xirr/max_drawdown/volatility`（沒有交易或無解）、`Performance.start_date/end_date`
  （沒有交易）、`Performance.benchmark.twr` 與 `series[].benchmark_index`（基準沒有資料）、`Valuation.current.*`、
  `MonthlyRevenue.ytd`（當年有缺月）、`Transaction.quantity/price`（該交易類型不使用的欄位，見下表）。
  前端一律顯示「—」，不顯示 0 或 NaN。
- **`Transaction.quantity` 與 `price` 為 `null`**：現金類（`deposit`、`withdrawal`、`fee`、`tax`、`interest`）
  兩者都是 `null`；`split` 的 `price` 是 `null`；`capital_reduction` 沒有退還股款時 `price` 是 `null`。
  （資料庫仍存 0；建立時傳 `null` 或省略都可以。）
- **`is_demo` 的範圍**：只要回應裡有任何數字來自示範資料就是 `true`。投資組合層級（`PortfolioSummary`、
  `Performance`）含美股時一定是 `true`（美股目前全部是示範資料）；前端用 `Holding.is_demo` 標出是哪幾檔
  （「含示範資料」章），台股的真實收盤價不會被標成示範資料。
- **FinMind 額度用完時**：FinMind provider 會自行暫停呼叫一段時間（額度 15 分鐘、其他錯誤 5 分鐘），
  期間只回答磁碟快取（過期的也用），沒有快取的資料才交給下一個資料源（通常是示範資料）。
  先前一個資料集的 402 會讓整個 FinMind 被斷路器停用 5 分鐘，連已快取的真實日線也變成示範資料，已修正。
- **ETF 與美股的月營收**：`GET /instruments/{symbol}/revenue` 直接回 `[]`（不去上游查，節省額度）。
- **`Quote.volume`** 是股數；MIS 回傳的是張，已乘 1,000。
- **`Quote.is_realtime`**：目前一律 `false`（MIS 已移除，沒有授權的即時來源；見「2026-11-12 第二批」）。
- **`Quote.source`**：可能是多個來源合併，例如 `shioaji-data+finmind`（價格來自前者，其他欄位來自後者）。
  只要有任何欄位來自示範資料，`is_demo` 就是 `true`。
- **交易類型的欄位用法**（合約只寫了部分）：

  | type | quantity | price | amount |
  |---|---|---|---|
  | buy／sell | 股數（台股必須是整數） | 成交價 | 成交價金（省略時 = 股數 × 價格） |
  | cash_dividend | 參與分配的股數（省略時自動帶入除息日前持股） | 每股現金股利 | 股利總額（省略時 = 股數 × 每股股利，台幣元以下捨去） |
  | stock_dividend | 配發股數（省略時自動計算） | 每股配股「元」 | 不足一股折付的現金（自動計算） |
  | split | 每 1 股變成幾股 | — | — |
  | capital_reduction | 每 1 股減少幾股（0–1） | 每股退還股款（選填） | 退還股款總額（選填，降低成本） |
  | deposit／withdrawal／interest | — | — | 金額 |
  | fee／tax（單獨記錄） | — | — | 金額（也可放在 `fee`／`tax`，會移到 `amount`） |

- **自動計算**：`fee`、`tax`、`health_insurance` 省略時自動計算；`PATCH` 改了數量、價格、日期、商品、
  類型或當沖註記時，沒有一併給的稅費會重新計算。
- **帳本一致性**：新增、修改、刪除交易後會重播該帳戶；會造成「賣超過持股」的操作回 422，
  `error.code = "ledger_inconsistent"`。商品代號找不到回 422 `unknown_symbol`。自動入帳的股利重算後造成的不一致也回
  422 `ledger_inconsistent`（見「2026-11-12 股利自動入帳」）。
- **商品代號**：路徑與參數可以用 `2330`、`2330.tw`、`2330.TW`，回應一律是標準格式 `2330.TW`。
- **美股帳戶預設手續費**：`currency = "USD"` 且沒給 `fee_rate`、`min_fee` 時預設為 0（台幣帳戶預設 0.1425%、
  最低 20 元、零股最低 1 元）。
- **已有交易的帳戶不能改幣別**（409 `conflict`）。`PUT /holdings` 只允許 `tracking_mode = "holdings"` 的帳戶（409）。

## 績效計算的解讀

- **`twr_index` 從第一天的報酬開始累乘**：第一個點是 `1 + r_第一天`，不一定剛好是 `1.0`
  （例如第一天買進後收盤價低於成本加手續費）。`twr = 最後一點 − 1`。`benchmark_index` 用同樣方式計算，
  兩條線可以直接比較。
- **基準是含息報酬**：除息日把現金股利再投入（`(P_t + D_t) / P_{t-1}`），分割（如 0050 在 2025-06-18
  一拆四）會接續，不會變成 −75%。
- **`net_invested`** = 累計買進成本（含手續費）− 累計賣出淨收入 − 減資退還股款；現金股利不扣。
- **現金股利以交易日期為準計入 `O_t`**。價格用未還原收盤價，除息日股價會下跌；如果股利記在發放日，
  除息日到發放日之間的 TWR 會短暫偏低，發放日再補回。示範資料把股利記在除息日（見待決事項）；台股自動入帳的股利
  也記在除息日（見「2026-11-12 股利自動入帳」），只有使用者自己記在發放日的紀錄仍有這個現象。
- **只記持股帳戶**：快照日以當天收盤市值作為期初投入（`I_t`），從那天開始追蹤報酬；
  損益則用使用者輸入的均價。快照日（含）之前的交易不計入。
- **區間**：`start_date` 是區間內第一個有持股的交易日（不會早於第一筆交易）；`ALL` 從第一筆交易開始。
  不支援的 `range` 回 422。
- **`1D`／`5D`（以交易日計）**：序列的第一點是**基準收盤**，`twr_index = benchmark_index = 1.0`，之後是最後
  1 個／5 個交易日（`1D` 共 2 點：前一個交易日收盤 → 最新收盤；盤中若有當天的即時報價，最後一點就是最新價）。
  `twr` = 這 1／5 個交易日的報酬連乘；基準日當天的股利與已實現損益不算在區間內；`xirr` 一律是 `null`
  （一到五天的年化沒有意義）。持股不滿 1／5 個交易日時，從第一次投入的前一個交易日（市值 0）開始。
  其他區間維持原本的定義（第一點已含第一天的報酬）。
- **`1D` 與 `PortfolioSummary.day_change_pct` 不一定相同**：前者是台北交易日的收盤序列（美股以前一個美股收盤
  補值，匯率用當日匯率），後者是每檔報價的「昨收 → 現價」（美股是最近一個美股交易日）。持有美股時兩者會有小差異。
- **基準**：可以是任何商品（`0050`、`006208.TW`、`VOO`…，含息報酬：除息日股利再投入、分割接續），或指數
  `^TAIEXTR`（發行量加權股價報酬指數，證交所編製、已含息，所以直接用每日漲跌）與 `^TPEXTR`（櫃買報酬指數，上櫃持股用）。
  **2026-11-12 起資料來自自建存檔**：證交所 OpenAPI `exchangeReport/MI_INDEX`（每天全部指數）與 `indicesReport/MFI94U`
  （當月每日，第一次存檔回補本月）、櫃買 `tpex_reward_index`（當月每日），表 `index_daily`；personal 明確開啟 FinMind 時，
  FinMind `TaiwanStockTotalReturnIndex`（`TAIEX`／`TPEx`）補存檔之前的日子。指數代號用 `^` 開頭，不會和台股代號或美股代號
  衝突，也不會出現在搜尋結果。指數沒有資料時 `benchmark.twr` 與 `benchmark_index` 為 `null`，不會用示範資料代替。
  `PATCH /me/preferences` 也接受 `^TAIEXTR`、`^TPEXTR`（大小寫不拘、可省略 `^`）。
- **XIRR** 在短區間（例如 1M）會被年化放大，這是 XIRR 定義使然。
- **日期軸**：任何持股有成交資料的日期（台股或美股）；當天沒有交易的市場以前一個收盤價補值。
- **已實現損益**也包含：單獨記錄的手續費與稅（負值）、利息（正值）、減資退還股款超過成本的部分。

## 正式環境的 cookie 與 CORS

前端（Cloudflare Pages，例如 `https://app.example.com`）與 API（Railway，例如 `https://api.example.com`）
必須在**同一個網站**（同一個可註冊網域 `example.com`）底下：session cookie 是 `SameSite=Lax`，同網站的
`fetch(..., {credentials: "include"})` 才會帶上。`*.pages.dev` 與 `*.up.railway.app` 是不同網站（兩者都在
Public Suffix List），瀏覽器不會送出 cookie，登入後也會一直 401。

| 設定 | 正式環境 | 說明 |
|---|---|---|
| cookie | `HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=30 天` | `FORLIOSA_ENV=prod` 時自動 `Secure`（`COOKIE_SECURE` 可覆寫） |
| `COOKIE_DOMAIN` | 選填，例如 `.example.com` | 不設＝只屬於 `api.example.com` 的 host-only cookie，這樣就能用；設了則子網域共用。空字串視為不設 |
| `CORS_ORIGINS` | `https://app.example.com`（逗號分隔） | 結尾的 `/` 會自動去掉；正式環境不能是 `*`（會拒絕啟動），因為帶 cookie 的請求不能對所有網站開放；也是 CSRF 檢查的允許清單（M5） |
| `FRONTEND_URL` | `https://app.example.com` | M5 起正式環境必填：Discord 登入後導回、邀請連結用它；必須是 `CORS_ORIGINS` 之一、https |
| 登出 | 刪除 cookie 時帶同樣的 `Domain`／`Secure` | 否則瀏覽器不會刪掉 |

測試：`tests/api/test_deploy_config.py`。部署步驟見 [`docs/deploy.md`](../../docs/deploy.md)。


## 2026-11-12 重新設計：個股頁、自選、本週事項（資料來源政策）

### 資料來源政策 `DATA_POLICY`

> 2026-11-12 第二批決定已改寫本節：預設 `commercial`；證交所網站與 MIS 在任何模式都不使用；`sources` 改為顯名聲明格式。
> 細節見下方「2026-11-12 第二批」。

| | `commercial`（**預設**） | `personal`（明確開啟） |
|---|---|---|
| 可用來源 | 只用可商用資料：證交所／櫃買 OpenAPI、集保開放資料、shioaji-data 官方檔，以及由它們建立的自建存檔 | 同左，另外示範資料補缺；`MARKET_DATA_PROVIDERS` 明確列出 `finmind` 才建立 FinMind（標「（非商用）」） |
| 示範資料 | **從不使用**（demo provider 只提供商品名稱清單）；資料不足時回空並在 `notes` 說明 | 補缺 |
| 證交所網站（T86、MI_QFIIS…）、MIS、櫃買網站、MOPS 網站 | **不使用**（已移除；舊存檔的 `twse-web`／`twse-mis` 資料列也不讀） | **不使用** |
| 盤中走勢 `/intraday` | `points: []`＋`notes` | 同左 |
| 新聞 `/news` | 官方公告（重大訊息、證交所新聞）＋新聞報導（GDELT＋自架 SearXNG（預設開）、兩者不足才 AI 搜尋；只有標題、媒體、時間、連結） | 同左，另加 Yahoo股市 RSS，FinMind 開啟時也加它的媒體標題（都是非商用） |
| 上市股票三大法人、外資持股 | 不提供（證交所 OpenAPI 沒有個股資料），`chips.notes` 說明 | 同左（FinMind 開啟時也不向它要這兩個資料集，只要融資融券；回補也一樣：FinMind 是轉載證交所網站） |

### 每個回應的 `sources`

- 物件型回應（`overview`、`intraday`、`chips`、`financials`、`position`、`why`、`Quote`、`History`、`Valuation`）多了
  `sources: string[]`，是給使用者看的**顯名聲明**：「提供機關〈資料集名稱〉（年份），依政府資料開放授權條款第 1 版」，例如
  「臺灣證券交易所〈上市個股日本益比、殖利率及股價淨值比〉（2026），依政府資料開放授權條款第 1 版」。授權條款規定沒有顯名就
  「視為自始未取得授權」，所以前端**必須**顯示（可以收合），不要改寫或翻譯。非商用來源一律以「（非商用）」結尾。
  完整清單與授權條款固定文字在 `GET /meta/attributions`。
- **陣列型回應**（`events`、`news`、`watchlist`、`/portfolio/upcoming`）無法加最上層欄位，所以**逐筆**帶 `sources`
  （與先前 `DividendRecord.is_demo` 的做法一致）。
- `as_of` 只在有「報價時間」意義的回應出現（`overview`、`position`、`why`、`Quote`）；籌碼、財報、事件本身就是帶日期的資料。

### 報價：參考價與漲跌停

- `Quote`（以及 `/quotes`、SSE、`Holding` 的今日損益）新增 `reference_price`、`limit_up`、`limit_down`；
  `change`／`change_pct` 一律對 `reference_price` 計算（沒有參考價時才用 `prev_close`）。除權息日 `prev_close` 仍是真正的昨收。
- 參考價的來源順序：①存檔的官方值（證交所 `TWT84U` 的 TodayOpeningRefPrice／TodayLimitUp／TodayLimitDown；
  櫃買 `tpex_mainboard_daily_close_quotes` 的 NextReferencePrice／NextLimitUp／NextLimitDown，套用到下一個交易日）
  ②報價本身帶的交易所漲跌停（MIS `u`／`w`），並用它判斷 MIS 的 `y` 在除權息日是否已經是參考價，避免重複扣股利
  ③計算：除權息參考價 =（昨收 − 現金股利）÷（1 + 無償配股率），四捨五入到升降單位；漲跌停為**未進位價格**的 ±10%，
  漲停無條件捨去、跌停無條件進位到該價位的升降單位。
- 已用真實資料驗證：2330（2395 → 2630／2160）、0050（103.20 → 113.50／92.90）、6488（635 → 698／572），以及
  2026-11-12 除息的 3680（昨收 435.50、現金 9.9147456 → 參考價 425.50、漲跌停 468.00／383.50；若從 425.50 計算跌停會錯成 383.00）。
- 美股：`reference_price = prev_close`，`limit_up`／`limit_down` 為 `null`。

### 個股端點的解讀與新增欄位

| 端點 | 與合約的差異（都是新增，不影響既有欄位） |
|---|---|
| `overview` | 多 `symbol`。`pe`／`pb`／`dividend_yield` 是證交所／櫃買公布值（存檔，personal 時 FinMind 補舊資料）；ETF 沒有公布殖利率時以近 12 個月現金股利 ÷ 現價計算。`eps_ttm` = shioaji-data 官方季報最近四季 EPS 合計（沒有季報時用 收盤價 ÷ 本益比）。`last_cash_dividend`／`ex_dividend_date` 是**最近一次（含已公告未除息）**的現金股利。`avg_volume_3m` 為近 3 個月日均量（股）。`status.attention` = 最近一個交易日或今天被列為注意股；`status.disposition` = 今天落在處置期間內。台股 ETF 多 `etf_nav`（淨值與同一天的折溢價，見「2026-11-12 ETF 淨值與折溢價」） |
| `intraday` | 多 `notes`、`is_demo`。**目前 `points` 一律是 `[]`**（沒有授權的盤中來源；MIS 已移除），`notes` 說明；`reference_price` 是當天的參考價；`is_partial` 台股為 `true`。日後接上授權來源時 `points[].volume` 是該分鐘的成交量（股） |
| `chips` | 多 `symbol`、`notes`；`range` 可用 `1M`、`3M`、`6M`、`1Y`。法人單位張（股數 ÷ 1000，保留小數）；外資持股 `pct` 是比率（0.2949）。**上櫃**股票的法人與外資持股來自櫃買 OpenAPI（`tpex_3insti_daily_trading`、`tpex_3insti_qfii`，每日存檔）；**上市**股票任何模式都是空陣列（`notes` 一律有那句說明：不在外資持股前 20 名時是 `services/stock.py` 的 `LISTED_CHIPS_NOTE`，在最新一份前 20 名名單上時是不含外資持股那句的 `LISTED_INST_NOTE`＋`TOP20_NOTE`），存檔裡已有的列（例如舊的 FinMind 回補）也不讀。`major_holders.buckets` 是集保 15 個持股分級（另有 `label`，例如「1,000 張以上」）；`pct` 是比率。集保只能下載當週，所以從開始存檔那週起才有資料 |
| `financials` | 多 `symbol`、`period`、`notes`。來源是 shioaji-data 官方季報（2023Q1 起，單季數字，千元）；若存檔中有更新一季的 OpenAPI 財報（`t187ap06` 是**年初至今累計數**），以「本季累計 − 上季累計」換成單季，現金流量為 `null`。`net_income` 是歸屬母公司業主淨利；`free_cash_flow` = 營業 + 投資活動現金流量（OpenAPI／shioaji-data 沒有資本支出科目）。`annual` 只列四季齊全的年度，EPS 用第四季的全年累計 EPS |
| `events` | 每筆多 `sources`、`estimated`、`period`；由新到舊排序（含未來）。範圍：過去 365 天到未來 120 天；`earnings`／`revenue_release`／`investor_conference` 用**實際日期**（見「2026-11-12 第二批」），只有查不到時才用法定期限（季報 5/15、8/14、11/14、3/31；營收每月 10 日；`estimated: true`，前後 60–90 天）。`mine`：未來的除權息／發放 = 目前持有；過去的 = 該日有記股利交易（`amount_estimate` 為實際入帳金額）；其他事件 = 目前持有。除息金額未公告時 `detail` 為「金額尚未公告」 |
| `news` | 每筆多 `sources`、`category`、`outlet`、`date_only`。**官方公告**：該公司的重大訊息與點名該公司的證交所新聞（最近 90 天，最多 30 筆），`source: "公告"`；之後是**新聞報導**（`category: "media"`，見「2026-11-12 新聞報導」） |
| `position` | 多 `symbol`、`currency`、`as_of`、`sources`、`is_demo`。金額為台幣，`avg_cost` 為原幣。`realized_pnl` 含交易與減資退款；`dividends_received` 已扣二代健保。`markers` 依交易日排序；`stock_dividend` 的 `quantity` 是實際配發股數。**目前股數為 0 一律回 `null`**（即使有已實現損益，見待確認 11） |
| `why` | 多 `symbol`、`sources`。規則：漲跌停 > 漲跌 ≥ 3%（對參考價）、量 ≥ 20 日均量 2 倍、除權息日、處置／注意、當天重大訊息主旨含「財務報告／財報／自結損益」或「營收」。`reasons[].kind` 為 `limit_up`、`limit_down`、`price_move`、`volume`、`ex_dividend`、`disposition`、`attention`、`earnings`、`revenue_release`。最新報價不是今天時文字用日期（「11/11 上漲 3.5%」）。`headline` = 名稱 + 前兩個理由 |
| `watchlist` | 每筆多 `sparkline_interval`（目前一律 `"1d"`：最近 20 個收盤；`"1m"` 保留給日後的授權盤中來源）、`sources`、`is_demo`；`quote` 可能為 `null`。`sparkline[].t` 在 `1m` 是 `"09:01"`，在 `1d` 是日期。`POST` 新增回 201、已在清單回 200（冪等）；找不到商品 422 `unknown_symbol`；最多 200 檔。`DELETE` 不在清單回 404 |
| `/portfolio/upcoming` | 多 `account_id` 參數，每筆多 `is_demo`、`sources`。`days` 1–90。`amount_estimate` = 目前股數 × 每股現金股利（台幣、未扣二代健保）；發放日已過除息日時，若除息日當天已記現金股利交易（自動入帳的股利就是這一筆）就用交易金額；除息金額未公告時為 `null`、標題加「（金額未公告）」。`recurring`（定期定額扣款）見「2026-11-12 第二批」 |

### 存檔（`python -m forliosa.archive`）

- 官方 OpenAPI 只給最新一天，所以 worker 每個交易日 08:10、14:40、21:40 存檔（冪等 upsert），週六 10:00 存集保。
  收盤價另外有「公布偵測」（`close_watch`，2026-11-13 加的，見文末「盤中狀態與收盤價公布偵測」）。
- 欄位名稱全部取自真實回應（`marketdata/opendata.py` 的說明，測試 fixture 是 2026-11-12 的精簡版）。幾個容易踩到的地方：
  `t187ap04_L` 的鍵是 `"主旨 "`（尾端有空白）；`MI_MARGN` 沒有日期欄位，21:00 前視為前一個交易日的資料；
  `t187ap06` 損益是累計數；櫃買法人鍵名含空白（`ForeignInvestorsInclude MainlandAreaInvestors-Difference`）；
  `announcement/notice` 沒有資料時回一筆空白列。
- **沒有官方個股歷史**：存檔只能從開始那天累積。證交所網站（T86、MI_QFIIS）回補已移除（網站條款禁止程式下載）；
  `backfill` 只剩 FinMind，且只在 personal 明確開啟時執行，回補資料不會覆蓋官方資料列。
- 證交所 OpenAPI 主機偶爾 reset 連線，存檔與 API 端的 OpenAPI provider 都會重試一次；回 3xx（防火牆 307）、403、429 時不重試、
  不跟隨重新導向，等下一次排程（2026-11-12 實跑時 `t187ap17_L` 回過一次 307，數秒後正常）。

## 2026-11-12 第二批：出清紀錄、只用可商用資料、定期定額、實際公布日、授權

產品負責人的決定：①出清的股票不在持股裡，但保留紀錄；②app **只使用可合法商用的資料**，`DATA_POLICY` 預設 `commercial`，
commercial 從不顯示示範資料；③定期定額；④財報、月營收、法說會用實際日期；⑤依授權研究
（[`docs/research/data-sources-licensing.md`](../../docs/research/data-sources-licensing.md)）移除證交所網站與 MIS、補齊顯名聲明。

### 新端點

| 方法 | 路徑 | 回傳 |
|---|---|---|
| GET | `/portfolio/closed?account_id=` | `ClosedRound[]`，最近出清的在前 |
| GET | `/instruments/{symbol}/position/history` | `{symbol, rounds: ClosedRound[], markers: [{date, type, quantity, price, amount, account_id}], sources}`；沒有持有也會回（從未交易：兩個陣列都是空的）；未知代號 404 |
| GET | `/recurring?account_id=` | `RecurringPlan[]` |
| POST | `/recurring` | body `{account_id, symbol, amount, day_of_month, start_date?, end_date?, active?, note?}` → 201 |
| GET／PATCH／DELETE | `/recurring/{id}` | PATCH 只改有給的欄位，`end_date: null` 表示清除；DELETE 204；別人的或不存在 404 |
| POST | `/recurring/{id}/draft?date=` | 下一次（或指定日）扣款的交易草稿 `RecurringDraft`，**不會建立交易** |
| GET | `/meta/attributions` | 所有資料集的顯名聲明與授權條款固定文字（**不需登入**） |

> **路徑與要求不同**：要求寫的是 `GET /instruments/{symbol}/history`，但這個路徑已經是合約的日線端點（`History`，前端
> `getHistory` 在用），所以交易歷史放在 `/instruments/{symbol}/position/history`，與 `position` 並列。

### 新增的欄位（都不影響既有欄位）

| 位置 | 新增 | 說明 |
|---|---|---|
| `History`、`Performance` | `notes: string[]` | 「資料累積中：自 2026-11-11 起存檔」、「美股目前沒有可商用的行情來源…」等 |
| `StockEvent` | `estimated: bool`、`period: string \| null`；`type` 多 `investor_conference` | `estimated` 只有法定期限的備援是 `true`；`period` 財報為 `"2026Q3"`、營收為 `"2026-10"` |
| `NewsItem` | `category: "material_info" \| "exchange_news" \| "media"` | 官方公告的 `source` 是 `"公告"` |
| `UpcomingItem`（`type: "recurring"`） | `plan_id`、`account_id`、`scheduled_date` | `date` 是順延後的扣款日，`scheduled_date` 是計畫原本的日子 |
| `TransactionIn.source` | 可為 `"ai_draft"` | 合約「AI 草稿簽名後帶 `source: "ai_draft"`」先前會被 422 拒絕，已修正 |
| `GET /health` 的 `providers[]` | `serves_data` | commercial 下 demo provider 只提供商品名稱，`serves_data: false` |

### `ClosedRound`（出清回合）

一個回合＝某帳戶某檔從 0 股 → 大於 0 → 回到 0（同一檔可以有好幾個回合；當沖從 0 開始也算一個 `holding_days: 0` 的回合）。
計算規則與帳本相同（均價／FIFO、當沖、配股、分割、減資、只記持股快照都適用），金額為台幣：

| 欄位 | 定義 |
|---|---|
| `opened_at`／`closed_at`、`holding_days` | 第一次買進日／全部賣出那天；日曆天數 |
| `total_bought_qty`／`total_sold_qty` | 買進股數（含快照）／賣出股數；中間有配股、分割、減資時兩者可以不同 |
| `cost_basis` | 買進價金＋買進手續費（快照：股數 × 均價） |
| `realized_pnl`、`realized_pnl_pct` | 回合內賣出與減資退款的已實現損益（扣手續費、證交稅）；`pct = realized_pnl ÷ cost_basis` |
| `dividends_received` | 回合內的現金股利淨額（已扣二代健保）；**出清後才入帳的股利**（除息後賣出、發放日入帳）算在最近一個回合 |
| `fees_and_taxes` | 買賣手續費＋證交稅（＋單獨記錄的手續費／稅）；股利的二代健保已從 `dividends_received` 扣除，不重複列 |

另外有 `name`、`account_id`、`currency`、`sources`。出清的股票不在 `holdings`，`position` 回 `null`（維持合約）。
`position.realized_pnl` 仍是這檔**所有回合**的已實現損益合計。

### 定期定額（`RecurringPlan`）

`{id, account_id, symbol, name, amount, day_of_month: int[], start_date, end_date, active, note, next_date, created_at, updated_at}`

- `day_of_month` 輸入可以是整數（`6`）或陣列（`[6, 16, 26]`），每個 1–28；**回應一律是排序過的陣列**。
- `amount` 是每次扣款的新台幣整數元；帳戶必須是 TWD；只支援台股與 ETF（美股 422）。`start_date` 省略為今天。
- **扣款日**：計畫的日子不是交易日就順延到下一個交易日；交易日以存檔的證交所〈有價證券集中交易市場開（休）市日期〉為準
  （「市場無交易，僅辦理結算交割作業」算休市，「開始交易日」「最後交易日」算交易日），沒有存檔的年份用內建清單。
  `next_date` 是今天（含）之後的下一次扣款日，停用或已結束為 `null`。
- `/portfolio/upcoming` 列出期間內每一次扣款（`type: "recurring"`、`amount_estimate` = 扣款金額，是**流出**），只算啟用中的計畫，
  也遵守 `account_id` 篩選。
- **草稿**：成交日 = 扣款日；股數 = floor(金額 ÷ 收盤價)（含零股），手續費依帳戶設定另計（零股最低 1 元）、買進免稅。收盤價：扣款日已經過去
  （`?date=` 補記）用扣款日當天的收盤價（`md.history(symbol, 扣款日, 扣款日)`，`price_as_of` = 扣款日）；今天或之後用最近收盤價
  （盤中是前一天收盤）；過去的扣款日沒有**真實**收盤價時用最近收盤價，`preview.rules` 第二行說明（personal 模式下示範 K 線
  不算那天的收盤價：存檔缺那天時 `md.history` 會用示範資料補，`close_on` 不收）。回應
  `{plan_id, scheduled_date, date, name, amount, price_as_of, transaction, preview: TradePreview, is_demo, sources}`，`transaction`
  可以直接 `POST /transactions`（`source: "ai_draft"`）。沒有收盤價 422 `no_price`（commercial 不會用示範價格）；金額不足一股
  422 `amount_too_small`；計畫沒有下一次扣款 409。
- 示範使用者有一個計畫：0050，每月 6、19 日，NT$5,000。

### 財報、月營收、法說會的實際日期

| 事件 | 實際日期從哪裡來 | 備援（`estimated: true`） |
|---|---|---|
| `earnings` | 重大訊息「董事會通過…財務報告」（符合條款第 31 款；期間從說明的「報導期間 115/01/01~115/09/30」或主旨「115年第三季」「一百一十五年第三季」「114年度」判斷），日期是發言日期 | 季報法定期限 |
| `revenue_release` | ①月營收彙總表（`t187ap05_L`／`mopsfin_t187ap05_O`）**第一次出現**這家公司這個月的日期（出表日期）；②重大訊息「115年10月合併營收」。取較早者 | 每月 10 日；開始存檔前就已公布的月份也用備援，`detail` 附上營收數字與「開始存檔前已公布」 |
| `investor_conference` | 重大訊息第 12 款（法人說明會），日期是**法說會當天**（事實發生日／「召開法人說明會之日期」，期間取第一天） | 無 |

「更正…」的公告不算發布日。被判讀成這三種事件的重大訊息不再重複出現成 `material_info`。

### commercial 下目前沒有的資料（請顯示誠實的空狀態）

| 資料 | 回應 |
|---|---|
| 盤中走勢 | `/intraday` 的 `points: []`＋`notes`（任何模式） |
| 上市股票個股三大法人、外資持股 | `chips` 空陣列＋`notes`（任何模式；上櫃股票有） |
| 開始存檔前的日線、本益比、籌碼 | 只回已存檔的部分＋`notes`「資料累積中：自 … 起存檔」；一點都沒有時是空陣列 |
| 股利歷史 | `/dividends` 只有存檔的除權息預告，加上證交所〈上市公司股利分派情形〉的董事會／股東會決議（2026-11-12 起，見「第三批」）；陣列型回應沒有 `notes`，可能是 `[]` |
| 績效 | 持股期間沒有每天的真實收盤價時 `series: []`＋`notes`；存檔足夠後從第一個完整存檔日（當作基準收盤，`twr_index` 1.0）開始，`notes` 說明起點 |
| 美股 | 沒有報價（`/quote` 404、`Holding.price: null` 以成本計值、`is_demo: false`）、績效空＋`notes` |
| ~~USD/TWD 匯率~~ | **已有（2026-11-12）**：中央銀行〈銀行間新臺幣對美元收盤匯率〉（OGDL），任何模式都用；完全沒有存檔時才固定 31.5，績效 `notes` 說明（見「2026-11-12 匯率改用中央銀行開放資料」） |
| 基準 `^TAIEXTR`／`^TPEXTR` | 2026-11-12 起由存檔提供（證交所 2026-11-02、櫃買 2026-11-02 起）；更早的日子沒有資料 |
| ~~媒體新聞~~ | **已有（2026-11-12）**：GDELT（可商用、需引用）＋自架 SearXNG（預設開、只對內）、兩者不足才 AI 搜尋，只有標題、媒體、時間、連結（見「2026-11-12 新聞報導」） |
| shioaji-data AI 研究（簡介、產業鏈、題材） | `summary`／`chain_stage` 為 `null`、`themes: []` |

`is_demo` 在 commercial 下永遠是 `false`。

### 移除的來源（任何模式）

| 移除 | 原因 | 影響 |
|---|---|---|
| 證交所 MIS 盤中報價與 worker 每 60 秒輪詢 | 網站條款禁止程式下載；即時／延遲行情需付費授權 | `/intraday` 沒有點、`is_realtime` 永遠 `false`、自選迷你圖只用日收盤 |
| 證交所網站 T86、MI_QFIIS（每日與回補） | 同上，且證交所表示是付費商品 | 上市股票沒有個股法人與外資持股 |
| 櫃買網站 `peQryDate` | 櫃買網站條款第五條 | 無（存檔用的是 OpenAPI 版本） |
| FinMind 預設 provider | 不可商用（付費版也不含原機關授權） | 只能在 personal 明確列出時使用 |

伺服器只連白名單內的網址（`marketdata/http.py`），User-Agent 誠實標示、不跟隨重新導向。舊資料庫裡來源為 `twse-web`、`twse-mis`
的資料列在任何模式都不會被讀出（沒有刪除）。

### 新增的官方資料

- **證交所新聞**（`/news/newsList`）每天存檔；主旨寫了公司代號（「公司代號：2314」）就歸到該股，否則以公司簡稱比對。
- **ETF 基本資料**（`t187ap47_L`）存進 `fund_profiles`（基金類型、追蹤指數、成立／上市日、發行單位數、保管機構），**尚未提供端點**；
  資料集裡的經理人、董事長、發言人姓名、電話、地址是個資，不存。
- **休市日**（`holidaySchedule`）存進 `market_holidays`，載入後所有交易日計算都用官方日期。
- 上櫃個股三大法人（`tpex_3insti_daily_trading`）與外資持股（`tpex_3insti_qfii`）原本就每日存檔，顯名聲明已補齊。

## 2026-11-12 第三批：開放資料 P0（期交所、報酬指數、股利決議、公司基本資料）

依 [`docs/research/open-data-inventory.md`](../../docs/research/open-data-inventory.md)（§11 建議清單、§12 期交所實作規格）與
[`open-data-catalog.json`](../../docs/research/open-data-catalog.json)。所有欄位名稱都在 2026-11-12 對真實回應核對過，測試 fixture
是精簡後的真實回應（`tests/archive/fixtures/taifex_*`、`twse_mi_index_*`、`twse_t187ap45_l_*` …）。

### 授權狀態與期交所「有條件」資料集（產品負責人決定）

`datapolicy.DATASETS` 每一筆多了 `license_status`：

| 狀態 | 意義 | `DATA_POLICY=commercial` 時 |
|---|---|---|
| `ogdl` | 機關以政府資料開放授權條款第 1 版釋出（證交所 swagger 連到 data.gov.tw/license；櫃買、集保與期交所三大法人／期貨大額交易人／Put/Call 比在 data.gov.tw 有對應資料集） | 照常顯示，附顯名聲明 |
| `conditional` | 推定為 OGDL（同一 OpenAPI、同一機關），但 data.gov.tw 沒找到個別資料集：期交所〈期貨每日交易行情〉〈選擇權每日交易行情〉〈每日外幣參考匯率〉〈選擇權大額交易人未沖銷部位資料〉，以及 catalog 一樣標 conditional 的〈最後結算價〉〈保證金一覽表〉×3〈股票期貨／選擇權交易標的〉 | **照常存檔，但不顯示**，直到 `TAIFEX_CONDITIONAL_CONFIRMED=true`（預設 `false`）。〈每日外幣參考匯率〉例外：2026-11-12 起只存檔，開關打開也不用（USD/TWD 改用中央銀行） |

- `personal`（非商用、明確開啟）一律顯示。判斷集中在 `datapolicy.dataset_served(key, policy)`；API、AI 工具、匯率都經過它。
- 詢問信草稿（寄 swagger 上的窗口 s0160116@taifex.com.tw）與收到回覆後要做的事：[`docs/outreach/taifex-licence-inquiry.md`](../../docs/outreach/taifex-licence-inquiry.md)
  （產品負責人 2026-11-12 決定先不寄，所以開關維持 `false`）。
- 期交所 swagger 的 `info.description` 只連到網站使用條款，沒有連 data.gov.tw；顯名格式照舊，例如
  「臺灣期貨交易所〈臺指選擇權Put/Call比〉（2026），依政府資料開放授權條款第 1 版」。

### 新端點

| 方法 | 路徑 | 回傳 |
|---|---|---|
| GET | `/derivatives/overview` | `DerivativesOverview`（見下） |
| GET | `/derivatives/futures/{code}/history?range=3M` | `{code, name, range, series: [{t, contract_month, open, high, low, close, change, change_pct, volume, settlement_price, open_interest, after_hours: {open, high, low, close, change, change_pct, volume} \| null}], notes, sources}`；`range`：`1M`、`3M`、`6M`、`1Y`、`MAX`；代號格式不對 422、從沒出現過的契約 404 |

`DerivativesOverview`：

| 欄位 | 內容 |
|---|---|
| `as_of` | 用到的資料中最新的交易日 |
| `futures[]` | TX、MTX、TE、TF 的**近月**（當天一般交易時段最小的月契約，週契約與價差不算）：`{code, name, contract_month, regular: {open, high, low, close, change, change_pct, volume, settlement_price, open_interest}, after_hours: {…同左但沒有結算價與未平倉}}`。**有條件資料集**：未確認前是 `[]` |
| `put_call_ratio` | `{date, volume_ratio, oi_ratio, put_volume, call_volume, put_oi, call_oi, oi_ratio_prev}`；比率是分數（0.6517 = 65.17%） |
| `institutional.TX`、`.TXO` | 三大法人（`investor`：`dealers`／`trust`／`foreign`，另有 `investor_name` 中文）：`oi_net`（口，正＝淨多）、`oi_net_change`（與前一個存檔交易日相比，沒有前一天時 `null`）、`oi_long`、`oi_short`、`oi_net_value_k`（千元）、`net_volume`（當日交易口數淨額）；TXO 另有 `calls`、`puts`（買賣權分計） |
| `large_traders.TX` | 期貨大額交易人（臺股期貨＝TX＋MTX/4）：`all_months`（`SettlementMonth` 999912）與 `near_month`：`top5_buy/sell`、`top10_buy/sell`、`top5_net`、`top10_net`、`market_oi`、`specific`（特定法人：`TypeOfTraders` 1）|
| `large_traders.TXO` | 選擇權大額交易人（買權、賣權，全部月份）。**有條件資料集**：未確認前 `null` |
| `served` | `{futures, options_large_traders}`：這兩部分目前是否顯示 |
| `notes`、`sources` | 授權待確認的說明、夜盤說明；顯名聲明 |

- **夜盤**：期交所把盤後交易時段算在下一個交易日。`after_hours` 是**同一個交易日**的夜盤（前一個交易日 15:00 開盤、當天 05:00 收盤），
  漲跌以前一個交易日的結算價計算，和當天一般時段同一個基準（TX 2026-11-11：前一日結算 42,646；夜盤 42,522 −124；一般 44,091 +1,445）。
  所以不需要清晨另外存檔，21:40 那次就涵蓋。
- **AI**：新工具 `get_derivatives_overview`（沒有參數、`strict`、唯讀、不含使用者資料）回傳同樣內容的精簡版；系統提示的工具說明多一行。

### 新增的欄位（都不影響既有欄位）

| 位置 | 新增 | 說明 |
|---|---|---|
| `DividendRecord`（`/instruments/{symbol}/dividends`） | `status`（`announced`＝有除權息日、`resolved`＝只有董事會／股東會決議）、`progress`（決議進度原文）、`board_date`、`meeting_date`、`cash_sources: {earnings, legal_reserve, capital_surplus} \| null`、`sources` | 決議來自證交所〈上市公司股利分派情形〉（`t187ap45_L`）。決議與除權息預告的對應：依除權息日先後，配給董事會日期在除權息日前 200 天內、每股現金（±0.001）與配股都相同、最早決議的那一筆（台積電 2026Q1、Q2 都是 7 元，不會配錯）。沒有對上的決議 `ex_dividend_date: null`：除權息日還沒公告，**或在開始存檔前就已除權息**（存檔不知道日期）。排序：除權息日，沒有時用董事會日期，新到舊 |
| `StockEvent.type` | `dividend_resolution` | 日期是董事會（擬議）日；`detail` 例「現金股利 0.8 元（資本公積 0.8 元）；資本公積發放的現金一般不屬股利所得、不扣二代健保（依公司公告的來源為準）。進度：股東會確認，股東會 2026-05-22」 |
| `Overview`、`InstrumentDetail` | `listed_date` | 上市／上櫃日期 |
| `Overview.market_cap`、`shares_outstanding`（以及 `InstrumentDetail`） | 改用官方資料 | 證交所〈上市公司基本資料〉／櫃買〈上櫃股票基本資料〉的已發行普通股數；市值 = 股數 × 最新存檔收盤價；`sources` 列出該資料集。沒有存檔時才用 shioaji-data（不會把官方股數和別的來源的市值混用） |
| `InstrumentDetail.industry` | 主檔沒有產業時用公司基本資料的產業別 | 資料集只給代碼（"24"），對照證交所產業分類（`opendata.INDUSTRY_CODES`） |
| `Performance.notes` | 匯率說明 | 有美股時說明 USD/TWD 的來源；2026-11-12 起改為中央銀行（見「2026-11-12 匯率改用中央銀行開放資料」） |
| `/meta/attributions` | 每筆多 `license_status`、`license_basis`、`served`、`last_updated`（存檔看到的最新資料日期）、`last_fetched`；最上層多 `taifex_conditional_confirmed`、`conditional[]`（已存檔但未顯示的資料集＋原因）、`stale[]`（停更端點：`key, agency, dataset, url, last_updated, checked_at, used, note`） | `datasets` 仍只列「目前顯示」的資料集（前端可直接用）；`commercial` 欄位在有條件資料集確認前是 `false` |

參考價：櫃買〈上櫃股票除權除息計算結果表〉（`tpex_exright_daily`）有該股當天的官方值時優先使用（開始交易基準價、漲跌停），
其次才是 TWT84U／櫃買 NextReferencePrice，最後才是自算。證交所沒有對應的 OpenAPI 資料集（inventory 未列；TWT84U 本身就是官方當日參考價）。
除權息預告金額「尚未公告」時，也用這個資料集的現金股利補上。

### 存檔

| 資料表 | 來源 | 群組（`archive run --only`） | 排程 |
|---|---|---|---|
| `index_daily` | 證交所 `MI_INDEX`（267 個指數，最新一天）、`MFI94U`（本月每日報酬指數，第一次執行即回補本月）；櫃買 `tpex_index`（本月 OHLC）、`tpex_reward_index`（本月櫃買／報酬指數） | `twse`、`tpex` | 08:10、14:40、21:40 |
| `ex_rights_results` | 櫃買 `tpex_exright_daily` | `tpex` | 同上 |
| `dividend_resolutions` | 證交所 `t187ap45_L`（約 2.5 MB） | `companies` | 21:40 |
| `company_profiles` | 證交所 `t187ap03_L`、櫃買 `mopsfin_t187ap03_O`（只存公司資料；董事長、發言人、會計師姓名與電話是個資，不存） | `companies` | 21:40 |
| `taifex_futures_daily` | `DailyMarketReportFut`（全存，含夜盤、週契約、價差） | `taifex` | 21:40 |
| `taifex_options_daily` | `DailyMarketReportOpt`：TXO、TEO、TFO 全存；其他（股票／ETF 選擇權）只存最近兩個到期月份（含該月的週契約） | `taifex` | 21:40 |
| `taifex_institutional` | 三大法人 5 個依日期資料集；`scope`：`all`、`fut_opt`、`futures`、`options`、`calls_puts`；金額一律千元（總表原為百萬元，×1000） | `taifex` | 21:40 |
| `taifex_large_traders` | 期貨、選擇權大額交易人（`settlement_month` 保留原值：999912＝全部月份、666666＝週契約合計） | `taifex` | 21:40 |
| `taifex_put_call_ratio` | `PutCallRatio`（回應含近一個月：upsert，第一次就回補） | `taifex` | 21:40 |
| `fx_rates`（既有表） | `DailyForeignExchangeRates` → `USDTWD`、`CNYTWD`、`EURUSD`、`USDJPY`、`GBPUSD`、`AUDUSD`、`USDHKD`、`USDCNY`、`USDZAR`、`NZDUSD`（回應含近 6 週：upsert；同一天已有中央銀行的 `USDTWD` 時不覆蓋，見「2026-11-12 匯率改用中央銀行開放資料」） | `taifex` | 21:40 |
| `taifex_margins` | 保證金一覽表（指數、股票、ETF）：**內容變動才新增一列** | `taifex` | 21:40 |
| `taifex_contract_map` | 中文商品名稱 → 代號（臺股期貨 → TX）：內建對照＋大額交易人與股票期貨保證金資料中的名稱 | `taifex` | 21:40 |
| `taifex_final_settlement`、`taifex_underlyings` | `FinalSettlementPrice`；`SSFLists`、`SSOLists` | `weekly` | 週六 10:00（和集保一起） |
| `dataset_status` | 每個資料集最新的資料日期；`weekly` 另外檢查停更的 `twtazu_od`、`t187ap09_L`（只記日期，不存資料） | 全部 | 每次存檔 |

- 不下載：`TimeAndSalesData`、`OptionsTimeAndSalesData`（數百 MB）、`TimeAndSalesDataOnCalendarSpreadOrders`。
- 白名單加 `https://openapi.taifex.com.tw/v1/`（只有資料端點；`/v1/swagger.json` 是 302），每 2 秒最多一次；期交所網站一律不抓。
- 交易日沿用證交所 `holidaySchedule`（期貨與股票同日休市）。

### 期交所解析陷阱（`marketdata/taifex.py`）

- **同一端點可能回 JSON 也可能回 CSV**（2026-11-12 實測發現）：資料端點在 Cloudflare 後面，快取存什麼就回什麼，不看 `Accept`。
  `DailyForeignExchangeRates` 當天回的是 CSV（`content-disposition: …csv`、UTF-8 BOM，欄名是 swagger 的中文說明、「／」寫成「_」，
  例如 `美元_新台幣(匯率)`），其他端點是 JSON。所以一律用 `decode_rows` 解析，每個欄位同時接受 JSON 鍵與中文欄名。
- 數字都是字串；缺值 `"NULL"`、`"-"`、`""`；百分比有 `"1.90%"` 與 `"107.08"`（`PutCallVolumeRatio%`）兩種，都轉成分數。
- 日期是西元 `YYYYMMDD`（證交所、櫃買多為民國年；櫃買 `tpex_index` 也是西元、`tpex_reward_index` 是民國年）。
- `ContractMonth(Week)`：`202611`、`202611W2`／`202611F2`（週三／週五到期的週契約）、`202611/202612`（價差：價格是價差，結算價與未平倉是 `-`）。
  MTX 週契約到期當天一般時段的結算價是 `"0"`。
- 盤後列的 `SettlementPrice` 是 `"NULL"`、`OpenInterest` 是 `"-"`。
- 三大法人用中文商品名稱、行情用代號：`taifex_contract_map`；大額交易人的名稱又略有不同（「櫃買期貨」vs「櫃買指數期貨」、「臺股期貨(TX+MTX/4)」），
  股票期貨在大額交易人是 `CD`、在行情與保證金是 `CDF`。
- 大額交易人 `999912` 是全部月份合計（TXO 999912 買權未平倉 88,811 ＝ Put/Call 比的 `CallOI`），`666666` 推定是週契約合計；
  `TypeOfTraders` 1 的數字都不大於 0，推定是「其中特定法人」。
- **`FinalSettlementPrice` 停更**：2026-11-12 回應中最新的最後結算日是 2025-12-05（inventory 說「2025-12 起」應是誤讀）；仍每週存，`/meta/attributions.stale` 列出。

### 資料品質修正

- 櫃買財報的金融、金控、保險、異業產業別（`mopsfin_t187ap06_O_*`／`07_O_*`）只回一列空白（代號、年度都是空字串，出表日期 1100616）：
  跳過，該工作記 0 筆而不是錯誤。
- 財報 upsert 改為**合併**：新回應某個科目是空值時，不會蓋掉已存檔的值。
- 證券業（`06_O_bd`）的科目名稱不同：`收益`、`營業利益`、`淨利（損）歸屬於母公司業主`，已加入對照。
- `/meta/attributions.stale` 列出停更端點與最後資料日期：`twtazu_od`（2026-06-05）、`t187ap09_L`（2026-08-19；每週檢查一次）、
  `mopsfin_t187ap39_O`（2021-08-04）、櫃買財報空白產業別（2021-06-16）、期交所 `FinalSettlementPrice`（2025-12-05）。

### 已知缺口

- **上櫃公司的股利決議沒有開放來源**：櫃買 `mopsfin_t187ap39_O`（股利分派情形）停在 2021-08。上櫃股票的股利只能等除權息預告（`tpex_exright_prepost`）
  與除權息計算結果（`tpex_exright_daily`），`status` 一律是 `announced`。
- 報酬指數只從 2026-11-02 起（`MFI94U`／`tpex_reward_index` 只給本月）；更早的基準要 personal＋FinMind，或日後購買歷史資料。
- 股利決議早於存檔的除權息日不知道：這類決議 `ex_dividend_date: null`。
- 產業別代碼對照是證交所產業分類的標準代碼（資料集本身只給代碼），新增產業時要更新。

## 2026-11-12 股利自動入帳

產品負責人 2026-11-12 決定（[`docs/handoff.md`](../../docs/handoff.md) §3.0）；對外行為見 [`docs/api-contract.md`](../../docs/api-contract.md)「股利自動入帳」。
程式在 `services/auto_dividends.py`（`sync_auto_dividends`、`covered_by_user`、`sync_checked`、`after_user_change`、`remember_skip`、`sync_all_users`），
掛在 `services/transactions.py`（create／update／delete）、`api/routes/accounts.py`、`worker.py`；資料表 `auto_dividend_skips`（migration `0007_auto_dividend_skips`；
`transactions.source` 本來就是 `String(16)`，`auto`／`auto_edited` 不需要改欄位）；測試 `tests/api/test_auto_dividends.py`。

### 同步

`sync_auto_dividends(db, user, md, account_ids, symbols)` 重算「現在應該有的」自動股利，與現有 `source="auto"` 的列比對後新增、更新、刪除；
不 commit，由呼叫端 commit 或 rollback。`sync_checked` 包一層嚴格重播：同步前帳目一致、同步後不一致時丟 `AutoDividendConflict`。

| 觸發 | 範圍 | 會讓帳目不一致時 |
|---|---|---|
| `POST`／`PATCH`／`DELETE /transactions` | 該筆交易的帳戶＋商品（修改時新舊兩組都算）；只有證券類交易、且是台股代號才同步，現金類交易不觸發 | `validate_ledger` 驗證的是**同步後**的帳本：先在記憶體裡套用變更、依新帳本重算受影響商品的自動列（`with_recomputed`；刪除或修改的那筆自動列當作已略過），再嚴格重播。所以除權前補記賣出、刪掉唯一的買進這類會讓舊的自動配股失效的變更可以通過。重播失敗時：沒有這次重算也一致 → 422 `ledger_inconsistent`「自動入帳的股利依這筆變更重算後帳目不一致：<重播錯誤>」；否則是一般的 `ledger_inconsistent`。整個請求不寫入。AI 的 `draft_transaction` 用同一個檢查 |
| `PUT /accounts/{id}/holdings` | 整個帳戶 | 同上；但原本帳目就不一致時照樣同步、不擋 |
| `PATCH /accounts/{id}`，且 `tracking_mode` 真的改變 | 整個帳戶 | 同上 |
| worker：每次存檔的群組含 `twse` 或 `tpex` 之後（交易日 08:10、14:40、21:40） | 所有使用者的所有帳戶，每個帳戶各自 commit | 該帳戶 rollback、維持原狀並記 warning；其他錯誤記 exception；其他帳戶照常 |

- 08:10 那次在開盤前就記上當天除息的股利（除權息預告隨 `twse`／`tpex` 群組存檔）。預告金額更正、補上發放日後，下一次同步會更新同一列
  （比較 `type`、`trade_date`、`quantity`、`price`、`amount`、`fee`、`tax`、`health_insurance`、`currency`、`is_day_trade`、`note`）；沒有變化就不寫（冪等）。
- 同步只動 `source="auto"` 的列。同一個鍵（帳戶、商品、除息日、類型）多出來的列、以及 `auto` 但不是股利類型的列（不應該存在）都會刪掉。
- `DELETE /accounts/{id}` 連同交易（含自動股利）、快照與該帳戶的略過紀錄一起刪除（外鍵也是 `ON DELETE CASCADE`）。
- **併發**：交易的新增／修改／刪除與 worker 的同步都先鎖住帳戶列（PostgreSQL `SELECT … FOR UPDATE`；SQLite 本來就序列化寫入），
  worker 鎖住後重新讀取，避免覆蓋使用者剛改過的列或重複新增。
- **示範帳號**：`seed` 的合成股利只記到 archive 第一個真實除息日的 120 天前為止，之後由自動入帳記真實的股利，同一次股利不會記兩次。

### 計算

- **事件**：`ex_dividend_events` **直接讀 archive provider**（`TWT48U_ALL`／`tpex_exright_prepost` 的存檔；不經過 facade，所以不受
  provider 冷卻影響，也不會混入 FinMind 或示範資料）。只記現金或配股大於 0 的事件；金額未公告的預告（`amount_pending`）只用來對應
  使用者的紀錄。同一次同步內每檔只讀一次（worker 整次執行共用）。
- **不知道 ≠ 沒有股利**：沒有設定 archive、讀取 archive 失敗、或 `instrument()` 查不到商品時，這一檔現有的自動列**全部保留**、也不新增；
  某一筆 `compute()` 失敗時保留那一筆。只有在資料讀得到、而且依規則不該存在（持股為 0、被使用者紀錄抵掉、有略過紀錄、金額改為 0、
  預告已撤回）時才刪除。
- **撤回的預告**：每次成功取得非空的 `TWT48U_ALL`／`tpex_exright_prepost`，存檔會刪掉同市場、除息日在明天以後、但這次不在預告表裡的
  預告（除息日改期或取消）；過去與今天的預告不動，取得失敗或空表不刪。
- **股數**：該帳戶該檔**不含自動列**的帳本，加上這次同步已決定的較早自動配股，重播到除息日前一天（`trade_date < ex_date`；快照期初也只算
  `as_of < ex_date` 的）。大於 0 才記。
- **只記持股帳戶**：除息日 ≤ 最新快照日的不記（快照股數已反映之前的股利）；換了較新的快照，快照日（含）之前的自動列會被移除。
- **日期**：除息日 > 今天（台北）不記；除息日當天就記。
- **現金股利**：走 `services/transactions.compute()`（`quantity` = 股數、`price` = 每股現金、`trade_date` = 除息日），所以金額元以下捨去，
  二代健保由 `compute()` 估算；資本公積部分（待確認 21）直接用事件的 `cash_sources` 傳給 `compute(capital_surplus=…)`，不再查一次。
  捨去後金額為 0（例如 1 股 × 0.5 元）不記；`compute()` 拒絕時記 warning、保留既有的那一列。
- **使用者只填每股金額記股利時**（`compute()`）：股數用這筆紀錄所屬除息日（`match_ex_event`，規則同下面的「使用者自己的紀錄」）前一天
  收盤的持股，不含同一次除權的自動配股、也不含除息日之後才買的股數；找不到對應的預告才用紀錄日前一天的持股。
- **配股**：`stock_dividend_shares(股數, 每股配股元)`，不足一股以面額 10 元折付現金（元以下捨去）；`fee`、`tax`、`health_insurance` 都是 0
  （與手動記配股相同）。同一除權息日的現金與配股各一列；配到的股數參與之後的除息。
- **備註**：`cash_note`／`stock_note`，例如「除息前一日持有 10,000 股 × 每股現金股利 2 元；發放日 2026-07-10」、
  「除權前一日持有 1,234 股 × 每股配股 0.5 元（每股面額 10 元）= 配發 61 股，不足一股折付現金 7 元」。

### 使用者自己的紀錄（`covered_by_user`）

- 只看同帳戶、同商品、`source` 是 `manual`／`import`／`ai_draft` 的 `cash_dividend`／`stock_dividend`。`auto_edited` 不算（它靠略過紀錄擋住）。
- 日期 `d` 的紀錄（`match_ex_event`），對到該類金額大於 0（現金股利也包括**金額未公告**的預告）、且 `e ≤ d ≤ e + 120 天`
  （`USER_RECORD_WINDOW_DAYS`）的除息日 `e` 中**最近**的一個；紀錄有 `price`（每股金額）時，優先金額相同（±0.001）的除息日。
  所以季配息（3 月除息 4 月發放、6 月除息 7 月發放）各自對上，一筆不會抵兩次；記下一筆金額未公告那次的股利，也不會抵掉上一次。
  日期早於除息日的紀錄不抵任何一次。
- 被抵掉的除息日不產生自動列，已有的刪除；使用者刪掉自己的紀錄後，同一次同步就會補回自動列。

### 略過紀錄 `auto_dividend_skips`

- 欄位 `user_id`、`account_id`、`symbol`、`ex_date`、`kind`（`cash`／`stock`）、`reason`、`created_at`；`(account_id, symbol, ex_date, kind)` 唯一。
- `reason`：`deleted`（`DELETE` 一筆 `auto`）、`edited`（`PATCH` 一筆 `auto`，該列同時改成 `auto_edited`）。鍵是修改**前**的帳戶、商品、日期與類型，
  所以把自動列改到別的日期，原本那次也不會再產生；之後刪掉 `auto_edited` 不另外記（`edited` 已經擋住）。
- 目前沒有端點列出或清除略過紀錄（見待確認 23）。

### 資料涵蓋範圍

- `TWT48U_ALL`（上市）與 `tpex_exright_prepost`（上櫃）是**預告表**，只列即將除權息的；過去的除息日只留在自建存檔（`market_events`，
  `type = "ex_dividend"`）。所以 commercial 下自動入帳只涵蓋**開始存檔之後**的除息日，更早的股利仍要使用者手動記（或匯入）。
  自動入帳只讀存檔，所以 personal 開啟 FinMind 時也不會補記 FinMind 的歷史股利。
- 上櫃預告金額「尚未公告」時，用〈上櫃股票除權除息計算結果表〉的現金股利補上（見「第三批」）；仍沒有金額就等公告後的那次同步。
- **配股率的單位是假設**：`StockDividendRatio`（無償配股率）當作「每 1 股配幾股」，每股配股（元）= 比率 × 10（`marketdata/twse.py` 的
  `parse_twt48u_all` 有註記；存檔的上市、上櫃預告都這樣換算）。還沒有用真實的配股預告驗證過；若單位不同，自動配股的股數會錯，
  第一次遇到真實配股時要核對。

## 2026-11-12 第四批：SEC EDGAR 美股基本面與申報

程式：`marketdata/sec.py`（下載與解析）、`services/sec.py`（快取、即時更新、組成回應）、`archive.py` 的 `sec` 群組、
`worker.py` 的 `sec_archive`；資料表 `sec_tickers`、`sec_companies`、`sec_filings`（migration `0008_sec_edgar`）。合約見
[`docs/api-contract.md`](../../docs/api-contract.md)「美股基本面（SEC EDGAR）」。

### 來源與授權

| 資料集 key | 網址 | 用在 |
|---|---|---|
| `sec-edgar/tickers` | `https://www.sec.gov/files/company_tickers.json` | 代號 → CIK（SEC 的拼法：`BRK.B` 查 `BRK-B`） |
| `sec-edgar/companyfacts` | `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` | 財報數字 |
| `sec-edgar/submissions` | `https://data.sec.gov/submissions/CIK##########.json` | 8-K／10-Q／10-K 申報清單 |

- 授權：SEC Webmaster FAQ「All Government-created content on sec.gov and EDGAR public filing content are free to access and
  reuse」（2026-11-12 讀到原文）。`datapolicy.DATASETS` 的 `license_status: "public"`，顯名「美國證券交易委員會（SEC）〈資料集〉（年），
  美國政府公開資料」，`/meta/attributions` 每筆的 `license`／`license_url` 是 SEC 的政策頁，`notice` 多一行 SEC 的說明。
- 只下載這三個 JSON（`marketdata/http.py` 的 `ALLOWED_URL_PREFIXES`）；申報文件本身只給連結，不下載。
- **User-Agent**：`Forliosa/1.0 <SEC_CONTACT_EMAIL>`。信箱只從環境變數讀（`Settings.sec_contact_email` 是 `SecretStr`，repr／dump
  都看不到），不寫進程式碼、測試、文件或日誌；格式不符（空白、角括號、換行）視同未設定。
- **頻率**：SEC 上限每秒 10 次（以請求者計）。`DEFAULT_LIMITER` 對 `sec.gov` 每 0.25 秒一次（每個行程 ≤ 4 次／秒），而且
  `data.sec.gov` 與 `www.sec.gov` 共用同一個額度；API 伺服器加 worker 合計也在 10 次／秒以下。
- **被拒絕就停**：403、429 或轉址（`HttpStatusError`）視為封鎖：這個行程一小時內不再向 SEC 發任何請求（回應的 `notes` 說明），
  worker 的工作直接以錯誤結束，不重試、不繞過。其他錯誤（逾時、5xx）只讓那家公司 10 分鐘內不再試。

### 快取與更新

- worker 每天 07:50（台北，美股收盤後；不看台股交易日）跑 `archive` 的 `sec` 群組：更新代號表，再更新**所有使用者帳本、持股快照、
  自選裡的美股個股**（ETF 跳過）超過 12 小時沒更新的 companyfacts 與 submissions。`dataset_status` 記最新的申報日（`/meta/attributions`
  的 `last_updated`）。手動：`uv run python -m forliosa.archive run --only sec`。
- 請求當下：快取超過 `SEC_STALE_HOURS`（24）就先向 SEC 取一次（逾時 `SEC_ON_DEMAND_TIMEOUT_SECONDS`＝6 秒、不重試），失敗就用快取並在
  `notes` 寫「SEC EDGAR 暫時無法連線，稍後再試；顯示 YYYY-MM-DD HH:MM 取得的資料」。同一家公司同時只會有一個請求在抓。
- `/overview` 只讀快取（不連 SEC），所以美股的 `eps_ttm`、`shares_outstanding` 要等 worker 或財務分頁抓過一次才有。
- 沒設 `SEC_CONTACT_EMAIL`：完全不連 SEC；財務回空＋`notes: ["SEC EDGAR 尚未啟用：伺服器沒有設定 SEC 要求的聯絡信箱（SEC_CONTACT_EMAIL），
  目前沒有美股財報與申報資料"]`，事件不含申報；worker 的結果列「sec edgar（未設定 SEC_CONTACT_EMAIL，略過）」。`FORLIOSA_ENV=test`
  一律不建立真的連線（測試用假 client）。

### 財報怎麼算（`marketdata/sec.summarize`）

- 科目（us-gaap，依序取第一個有該期數字的標籤）：營收 `Revenues` → `RevenueFromContractWithCustomerExcludingAssessedTax` →
  `RevenueFromContractWithCustomerIncludingAssessedTax` → `SalesRevenueNet`；毛利 `GrossProfit`；營業利益 `OperatingIncomeLoss`；
  淨利 `NetIncomeLoss` → `NetIncomeLossAvailableToCommonStockholdersBasic` → `ProfitLoss`；EPS `EarningsPerShareDiluted` →
  `EarningsPerShareBasicAndDiluted`；資產 `Assets`；負債 `Liabilities`（沒有時 = `LiabilitiesAndStockholdersEquity` − 含非控制權益的權益）；
  權益 `StockholdersEquity`；營業／投資／籌資現金流 `NetCashProvidedByUsedIn…Activities`（→ `…ContinuingOperations`）；資本支出
  `PaymentsToAcquirePropertyPlantAndEquipment` → `PaymentsToAcquireProductiveAssets`；稀釋加權平均股數
  `WeightedAverageNumberOfDilutedSharesOutstanding`；流通股數 `dei:EntityCommonStockSharesOutstanding`（封面頁，最新一筆）。
- 只用 10-K、10-Q（含 `/A`）的數字；同一期（start, end）只留一個值：**數字取最新申報**（重編後的數字），**會計年度標籤取最早申報**
  （那一期是當期的那份報告）。存最近 12 年。
- **比較數字的年度**：companyfacts 的 `fy` 是「那份申報」的年度，所以同一份申報裡的比較數字（一年前、兩年前）標的是較晚的年度。存的時候
  依那一期結束日和申報本身當期結束日差幾年往回推：新上市公司第一份 FY2025 10-K 帶的 2023、2024 年是 `FY2023`、`FY2024`，下一份 10-Q
  的去年同季是 `FY2025Q1`（以前會變成 `FY2025`、`FY2026`、`FY2027Q1`）。
- **期間**：12 個月（350–380 天）的期間就是一個會計年度，名稱取最小的 `fy`；例：Apple 2025-09-28～2026-09-26 是 `FY2026`，NVIDIA
  2025-01-27～2026-01-25 是 `FY2026`。季度 `FY2026Q1`…`Q4` 依結束日距會計年度開始的天數判斷。`period_ends` 是各期最後一天。
- **股票分割**（`marketdata/sec.find_splits`）：分割後的報告只重編它列出的期間（10-K 三年、10-Q 去年同期），更早的期間停在舊股數，所以
  「每期取最新申報」的 EPS、平均股數會混用兩種基準（NVIDIA 年報曾是 FY2022 3.85 → FY2023 0.17）。做法：同一期在前後兩份申報的股數
  （`WeightedAverageNumberOfDilutedSharesOutstanding`、`…SharesOutstandingBasic`、`…ShareOutstandingBasicAndDiluted`）差一個分割比例
  （p/q，q ≤ 5，至少 6/5、最多 500，誤差 1%）就是分割，一期就算；把分割定位在「最後一份舊基準申報」與「第一份新基準申報」之間，
  短的區間先看，矛盾的忽略；修正申報（`/A`）不算新基準。沒有股數標籤的期間（Alphabet 2022 年前的股數只有分類別的）用 EPS（四捨五入到
  分，至少 0.10），要兩期一致，且同一區間股數沒變就不算。結果存在 `facts.splits`（`[["2024-08-28", "10"], …]`：第一份新基準申報日、
  每 1 股變幾股；反分割如 `"1/8"`），`summarize` 把那天以前申報的 EPS ÷ 比例、平均股數 × 比例，再推算第四季（全年 − 前三季累計都在同一
  基準）。顯示期間內有分割時 `notes` 加一行說明。用 2026-11-12 的 SEC 資料核對：AAPL（2014 1 拆 7、2020 1 拆 4）、NVDA（2021 1 拆 4、
  2024 1 拆 10）、TSLA、GOOGL（EPS）、AMZN、WMT、CMG（1 拆 50）、AVGO、SMCI、GE（8 合 1）都找到，MSFT 沒有誤判。
- 快取的 `facts.v` 是 2；舊版（1，沒有分割資料、比較數字的年度沒往回推）的公司資料在下次請求或 worker 時重抓。
- **單季數字**：有三個月的數字就用；否則用年初至今的累計相減（10-Q 的現金流量是累計；第四季 = 全年 − 前三季累計，因為 10-K 只報全年）。
  EPS 相減是近似值（股數會變），平均股數不推算（第四季為 `null`）。有推算時 `notes` 會說明。
- 自由現金流量 = 營業活動現金流量 − 資本支出（美國慣用定義；台股仍是營業 + 投資）。
- `overview.eps_ttm`（美股）：最近四季的稀釋 EPS 加總；剛好是一整個會計年度時用 10-K 的全年 EPS（各季加總不一定等於全年）。
- 銀行等沒有營收／毛利標籤的公司：那幾列是 `null`（例如 JPMorgan 的季營收）。外國公司（20-F、IFRS）沒有 us-gaap 數字：回空＋notes。

### 申報事件

- `/events` 對美股個股加上 `type: "sec_filing"`，`form` 為 `8-K`、`10-Q`、`10-K` 或其修正 `…/A`（其他表單如 Form 4、S-8、DEF 14A 不列）。
  `date` 是申報日；`title`：「10-K 年度報告」「10-Q 季度報告」「8-K 營運結果與財務狀況」（8-K 用第一個不是 9.01 的項目名稱，修正加「（修正）」）；
  `detail`：「會計年度截至 2026-09-26」「季度截至 2026-06-27」「申報項目：2.02 營運結果與財務狀況、9.01 財務報表與附件；事件日期 2026-11-02」；
  `url`：`https://www.sec.gov/Archives/edgar/data/{CIK}/{accession 去掉 -}/{主文件}`。
- `mine`：持有時 10-K／10-Q 都是 true，8-K 只有最近 7 天的是 true。存最近 400 天，顯示範圍與其他事件相同（過去 365 天）。

### 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `SEC_CONTACT_EMAIL` | 空 | SEC 要求的聯絡信箱，只放進 User-Agent。沒設就不連 SEC |
| `SEC_ENABLED` | `true` | `false` 可整個關掉 SEC |
| `SEC_STALE_HOURS` | 24 | 請求當下超過幾小時就重抓 |
| `SEC_ON_DEMAND_TIMEOUT_SECONDS` | 6 | 請求當下抓 SEC 的逾時（worker 用 30 秒、重試一次） |

### 已知限制

- 商品清單（`master`）的美股仍只有內建的 AAPL、NVDA、VOO、QQQ：SEC 代號表只拿來查 CIK，沒有把一萬多檔美股加進搜尋（見「待確認」24）。
- 美股報價、股利仍沒有可商用來源（前端的股利分頁對美股寫「美股目前沒有可商用的配息資料來源」，不說成沒有配過息）。
- 在 10-Q 裡也報近 12 個月（TTM）數字的公司（例如 Amazon 的現金流量）：TTM 期間也是 12 個月，現在會被當成會計年度，年報與季度標籤會錯（AAPL、NVDA 沒有這個情形）。把 SEC 代號表加進商品清單（待確認 24）之前要先改成只認 10-K 的 12 個月期間。
- NVIDIA 2014-01-26 結束的會計年度在 SEC 資料裡標成 `fy` 2013，所以那一年叫 `FY2013`、下一年接 `FY2015`（在 10 年的顯示範圍之外）。

## 2026-11-12 匯率改用中央銀行開放資料

產品負責人決定不寄信給期交所，USD/TWD 改用中央銀行〈銀行間新臺幣對美元收盤匯率〉（[`docs/handoff.md`](../../docs/handoff.md) §3.3）；
對外行為見 [`docs/api-contract.md`](../../docs/api-contract.md)「匯率」。沒有新端點、沒有新遷移（沿用 `fx_rates`）。

### 來源（2026-11-12 實測）

| 項目 | 內容 |
|---|---|
| 資料集 | data.gov.tw 7232〈銀行間新臺幣對美元收盤匯率〉，提供機關中央銀行（資料來自台北外匯經紀公司），政府資料開放授權條款第 1 版 |
| 端點 | `GET https://cpx.cbc.gov.tw/api/OpenData/FTDOpenData_Day`（`application/json`，約 190 KB）。另有 `FTDOpenData_Month`（月平均，鍵 `西元年月`）與 `FTDOpenData_Year`（文件說年平均，實測回的是同樣的月資料、鍵 `西元年`）：都不用 |
| 格式 | 一個陣列、舊到新：`[{"日期": "20080102", "NTD_USD": "32.443"}, …]`；`日期` 西元 `YYYYMMDD`，`NTD_USD` = 1 美元兌新臺幣，字串、1–3 位小數；沒有查詢參數，每次都是**完整歷史** |
| 涵蓋 | 4,686 個營業日，2008-01-02 到 2026-11-12（當天 17:12 已有 2026-11-12 的 32.889）；沒有缺值、沒有重複日期 |
| 與期交所比對 | 期交所〈每日外幣參考匯率〉的 USD/NTD 與這個序列**完全相同**（fixture 的 27 個交易日 2026-10-01 … 11-11 全部一致） |
| 白名單 | `marketdata/http.py` 加 `https://cpx.cbc.gov.tw/api/OpenData/`（只有開放資料 API；央行網站與統計資料庫頁面不在內），每 2 秒最多一次 |
| 顯名 | `datapolicy.DATASETS["cbc-opendata/fx"]`：「中央銀行〈銀行間新臺幣對美元收盤匯率〉（2026），依政府資料開放授權條款第 1 版」，`license_status: ogdl`、`basis: data.gov.tw 7232`；來源鍵 `cbc-opendata` |

### 存檔（`archive.py`：`Archiver.cbc_fx`，群組 `cbc`）

- worker 的晚間存檔（交易日 21:40，`EVENING_GROUPS`）跑一次；手動：`uv run python -m forliosa.archive run --only cbc`。
- 第一次執行就回補 2008 年起的全部歷史（實測 4,686 筆）；之後只寫**新的或數字改過的**日子（第二次執行 0 筆），`dataset_status["cbc-opendata/fx"]` 記最新的匯率日期。
- 解析在 `marketdata/cbc.py`（`parse_fx_day`）：沒有日期或匯率不是正數的列略過；回應不是陣列、是空陣列（正常回應一定是 2008 年起的完整歷史）、
  或一列都解析不了（欄位改名）時記錯誤，不寫 0 筆了事，`dataset_status` 也不動（`/meta/attributions` 的 `last_updated` 保留上一次的日期）。
- **與期交所共用 `fx_rates`**：主鍵是 `(pair, date)`，同一天只能有一列 `USDTWD`。央行那一列優先：`cbc_fx` 會把同一天期交所的列改成央行的（數字相同，只換 `source`）；
  `taifex_fx` 用條件 upsert（`WHERE fx_rates.source != 'cbc-opendata'`），不會覆蓋央行的列。期交所其他 9 個匯率照舊存。
  結果是：期交所的 `USDTWD` 只會留在央行還沒公布的那幾個小時（同一天 21:40 兩個工作都跑，所以通常不會留下）。

### 使用（`FxBook`）

- `ArchiveProvider.fx_history` 只讀 `source = 'cbc-opendata'` 的 `USDTWD`（也只回 `USDTWD`）；不再看 `TAIFEX_CONDITIONAL_CONFIRMED`。
  回傳區間 [start, end] 的列，**加上 start 之前最新的一列**（不是固定往前看幾天）：存檔停更（worker 沒跑、端點改欄位名）時，
  不論使用者第一筆交易在哪天，都沿用最後一筆匯率並加停更說明，不會因為區間裡沒有列就退回固定 31.5 並誤稱「還沒有存檔」。
  archive 是第一個 provider，所以任何 `DATA_POLICY` 都先用央行；只有存檔完全是空的時候，personal 才會輪到 FinMind／示範資料，commercial 則用固定 31.5
  （停更的存檔也算有存檔：personal 不會因此改用 FinMind）。
- 某天的匯率 = 該日或之前最近一個營業日的收盤匯率；2008-01-02 以前的交易用序列的第一筆（2008-01-02 的 32.443）。
- 成本、賣出、股利用各自交易日的匯率；市值用最新匯率（`FxBook.latest`；當天下午公布前是前一個營業日）。

### 說明文字

| 位置 | 內容 |
|---|---|
| `Performance.notes`（有美股時） | 「USD/TWD 匯率：中央銀行〈銀行間新臺幣對美元收盤匯率〉（2026），依政府資料開放授權條款第 1 版」；personal 用到 FinMind／示範資料時列它們的標籤（例「USD/TWD 匯率：示範資料（模擬）」）；完全沒有存檔時 `FX_MISSING_NOTE`「USD/TWD 以固定 31.5 換算：還沒有中央銀行〈銀行間新臺幣對美元收盤匯率〉的存檔」；最新匯率比今天早 14 天以上（含 14 天；`FX_STALE_DAYS`，比農曆年休市長）再加「USD/TWD 匯率只到 YYYY-MM-DD（匯率），之後的日子沿用這個匯率」。commercial 下持有美股的期間沒有可商用的美股價格、績效算不出來，所以這段 `notes` 多半出現在 personal，或美股已經賣出、績效區間只剩台股的時候 |
| `/instruments/{symbol}/position` | 美股的 `sources` 多上面的顯名聲明 |
| `/meta/attributions` | `datasets` 多 `cbc-opendata/fx`（`last_updated` 是最新匯率日期）；`taifex-openapi/fx` 留在 `conditional[]`，`used_for`「只存檔（USD/TWD 換算改用中央銀行〈銀行間新臺幣對美元收盤匯率〉）」 |
| AI 工具 | `get_portfolio_summary`（新 `notes`）、`get_holdings`、`get_position`（美股）的 `notes` 多匯率來源與「美股市值以 YYYY-MM-DD 的 USD/TWD X 換算成新台幣；成本、已實現損益與股利用各交易日的匯率」（`portfolio.fx_tool_notes`）。三個工具都用算出金額的同一個 `PortfolioState.fx`（`get_position` 把 state 傳給 `stock.position`），說明不會跟金額對不上 |

- 移除 `portfolio.FX_PENDING_NOTE`（期交所授權待確認的說明）；`fx_notes(fx, today=None)` 不再需要 `MarketData`。
- 測試：`tests/archive/test_cbc_parser.py`（解析、與期交所一致、壞資料、白名單）、`tests/archive/test_open_data_jobs.py`（回補、冪等、與期交所互不覆蓋、更正）、
  `tests/api/test_open_data_api.py`（`FxBook`、31.5 備援、停更說明與 14 天門檻、停更很久（查詢區間裡一列都沒有）的存檔仍沿用最後匯率、美股持股估值、AI 工具、`/meta/attributions`）；
  空陣列記錯誤：`test_cbc_parser.py`、`test_open_data_jobs.py`。fixture `cbc_ftd_day_live_20261112.json` 是真實回應
  裁成 36 天（2008 開頭 3 天、跨年 5 天、2026-10-01 起 28 天）；測試不連網。

### 已知缺口

- 只有 USD/TWD。其他幣別（港股、日股）沒有可商用的開放來源，目前也沒有這類商品。
- 交易日當天的市值在央行下午公布前用前一個營業日的匯率（約 16:00–17:00 之後的 21:40 存檔才更新）。

## 2026-11-12 新聞報導（個股頁補強第 1、2 項）

產品負責人決定（`PRODUCT.md`「相關新聞」「個股頁補強」1–2）：像 Google 財經／Goodinfo 的新聞列表——媒體**原標題＋媒體名稱＋時間＋原文連結**，
不轉載內文、不放媒體照片，有下架處理。研究與法律基準：[`docs/research/news-and-external-sources.md`](../../docs/research/news-and-external-sources.md)。
程式在 `src/forliosa/news/`；`/news` 的形狀見 [`docs/api-contract.md`](../../docs/api-contract.md)「新聞報導（2026-11-12）」。

### 來源（可替換：`news/sources.py` 的 `NewsSource`）

| 來源 | 什麼時候用 | 怎麼查 | 停止條件 |
|---|---|---|---|
| **GDELT DOC 2.0**（`api.gdeltproject.org/api/v2/doc/doc`，預設） | 每檔每次 worker 批次 | **英文**關鍵字：英文簡稱（`t187ap03_L`「英文簡稱」／`mopsfin_t187ap03_O` 的 `Symbol`，存在 `company_profiles`；沒有時用商品主檔的英文別名）＋代號，台股 `sourcecountry:taiwan`、美股 `sourcelang:english`（例：`(TSMC OR 2330) sourcecountry:taiwan`）。台股的英文簡稱是一般英文單字時（穩懋「WIN」、台達電「DELTA」；`news/normalize.py` 的 `COMMON_WORDS`）不放進查詢、只用代號（`3105 sourcecountry:taiwan`）：GDELT 比對機器翻譯後的全文、不分大小寫，這種字會讓 75 筆全被無關新聞佔滿；`mode=artlist`、`format=json`、`maxrecords=75`、`startdatetime` = 上次成功前 1 小時（最多 7 天） | 429／403、或 200 回「Please limit requests…」→ 這次批次不再問，整個來源暫停 15 分鐘起、每次加倍、最多 4 小時（`news_fetch_state` 的 `symbol="*"`）；連線錯誤連 3 次 → 這次批次略過 |
| **AI 網路搜尋**（`news/ai_search.py`） | 只在 GDELT 與 SearXNG 這 24 小時內都對這檔有回應（關掉或暫停中的不算）、且兩者（加 personal 的 Yahoo RSS）最近 7 天合計少於 `NEWS_AI_MIN_ITEMS`（3）則時；同一檔 `NEWS_AI_INTERVAL_HOURS`（24）內最多一次；每批最多 10 次 | `web_search`（最多 2 次，封鎖行情／論壇／交易所網站；**沒有** `web_fetch`）＋ strict 工具 `report_news`（只回網址清單）。**模型只負責挑選**：標題、網址、日期都取自 `web_search_result`（網址不在搜尋結果、行情頁、沒有日期的都丟掉） | 本月（UTC）`ai_usage.feature = "news"` 的估計費用 + US$0.05 超過 `NEWS_AI_BUDGET_USD`（30）就整月不跑；沒有金鑰、`AI_WEB_SEARCH=false`、`NEWS_AI_ENABLED=false` 也不跑 |
| **SearXNG**（`news/searxng.py`；自架、只對內，`deploy/searxng`） | **預設開啟**（2026-11-12 第三輪）。網址：`NEWS_SEARXNG_URL`，不設時 prod 是 `http://searxng.railway.internal:8080`、dev／test 是 `http://localhost:8080`；`NEWS_SEARXNG_ENABLED=false` 或 `NEWS_SEARXNG_URL=`（空字串）關掉。每檔在 GDELT 之後問；這檔 `NEWS_SEARXNG_CACHE_MINUTES`（60）內回應過、或 GDELT 已有 ≥ `NEWS_SEARXNG_SKIP_GDELT_ITEMS`（8）則 24 小時內的標題就不問 | 中文查詢：台股 `q=台積電 2330&language=zh-TW`，美股 `q=NVIDIA NVDA&language=en`（英文簡稱＋代號）；都加 `categories=news&time_range=week&format=json&safesearch=0`。有引擎暫停時改用 `engines=<其他引擎>`（同時送 `categories` 會把全部新聞引擎加回來）。只讀 `title`、`url`、時間（`publishedDate`；沒有時用 `pubdate`／`metadata` 裡的「3 小時前」「3 hours ago」「昨天」，以天計的只標日期）與 `engines`；`content`、縮圖不讀；沒有時間的不收；**以週、月、年計的相對時間（「3 weeks ago」「2 週前」）也當作沒有時間、不收**：Brave News 與 DuckDuckGo News 不理 `time_range=week`，這種結果一定超過一週、而且日期可能差到 6 天（2026-11-12 審查後）；搜尋引擎轉址丟掉 | 一次只查一個、上一次查完到下一次開始 ≥ `NEWS_SEARXNG_INTERVAL_SECONDS`（10，最少 10）。**連不上**（拒絕連線、DNS、逾時、5xx、不是 JSON）→ 整個來源暫停 15 分鐘起、加倍到 4 小時（`last_status: "unreachable"`，不算錯誤）；我們自己的 SearXNG 回 403／429 → 暫停 `NEWS_SEARXNG_BACKOFF_MINUTES`（120）起。**上游引擎**（`unresponsive_engines`）：CAPTCHA／too many requests／access denied（含 `Suspended: …`）→ 那個引擎暫停 120 分鐘起、加倍到 24 小時；逾時等其他錯誤連 3 次 → 暫停 15 分鐘起；問的引擎全部失敗 → 整個 SearXNG 暫停；引擎全部暫停中 → SearXNG 暫停到最早恢復的那個。不換 IP、不用代理 |
| **Yahoo股市 RSS** | 只有 `DATA_POLICY=personal`（條款限非商用；`NEWS_YAHOO_RSS=false` 可關） | `tw.stock.yahoo.com/rss?s=<代號>`。2026-11-12 實測這個參數回的是「最新新聞」頻道，所以靠下面的相關性篩選只留這檔的標題；原始媒體從描述開頭判斷（「MoneyDJ新聞」「【財訊快報／」「（中央社記者」），**描述本身不存** | 同上 |

HTTP：`news.service.news_fetcher` 用誠實的 User-Agent（`forliosa/0.1 (portfolio tracker; news headline index)`），GDELT 每次間隔 ≥ `NEWS_GDELT_INTERVAL_SECONDS`（6，最少 5），
連線中斷只重試一次，遇到拒絕不重試。白名單（`marketdata/http.py`）多了 GDELT 與 Yahoo股市 RSS 兩個網址；SearXNG 有自己的 client（`searxng.searxng_fetcher`：
同樣的 User-Agent、只開放設定那台的 `/search` 與 `/healthz`、不重試、連線逾時 5 秒、整體 `NEWS_SEARXNG_TIMEOUT_SECONDS`（20）秒、不跟轉址）。
SearXNG 對上游搜尋引擎送出的請求由 SearXNG 自己決定（瀏覽器樣式的 User-Agent 與連線特徵，這是 SearXNG 能運作的方式）；`deploy/searxng/settings.yml` 不設代理、`source_ips` 或 Tor。
**新聞網站本身從不抓取**（只連結）。

### 正規化（`news/normalize.py`、`news/outlets.py`，對 2026-11-12 的真實回應核對過）

- **空白**：GDELT 會在標點兩邊加空白（「台積電 ： AI需求」「 【 台股盤中 】 」「4 . 6萬」「8 ％！」「exit , says」「( NVDA )」），都去掉；
  整個標題逐字加空白時才去掉漢字之間的空白——台灣標題常用一個空白分隔兩句（「…說明會 攜手培育…」），所以平常保留。
- **尾巴**：由右往左去掉重複媒體名稱或泛用版名的部分（「| 財經 | 三立新聞網 SETN.COM」「- 自由財經」「| ETtoday財經雲」「- Reuters」）；
  專欄名稱保留（「| 台股雜談」，和 Google 財經一樣）；剩下的標題少於 4 個字就不去。
- **媒體名稱**：依網域的最長後綴（`money.udn.com` 經濟日報 先於 `udn.com` 聯合新聞網；`ltn.com.tw`／`ec.ltn.com.tw` 自由時報；`setn.com` 三立…），不認得的顯示網域。
- **相關性**：標題要有公司簡稱（台積電）、代號（2330，不算「23301」「2330點」「2330元」「2026年」）或英文簡稱（TSMC，整個字；少於 3 個字母的不用）。
  英文名稱照寫法比對（2026-11-12 審查後）：5 個字母以內的全大寫單字是縮寫，標題裡也要全大寫（「WIN Semiconductors」算，「WBC win」「Mekong delta」
  「Delta Air Lines」不算）；其他單字是專有名詞，第一個字母要大寫、其餘不拘（「Nvidia」「NVIDIA」算，「apple harvest」不算）；多個字的名稱不分大小寫
  （「Hon Hai」「apple inc.」）。仍會漏掉的：標題大寫的一般字（「Big Apple」），以及只寫「Delta Electronics」這種與官方英文簡稱寫法不同的英文標題。
  2026-11-12 的台積電樣本 17 則留 13 則（「南華大學邀請台積公司…」「台股暴跌1165點…」等順帶提到的被濾掉）；NVIDIA 英文樣本 16 則留 10 則、去重後 6 則（同一則被 4 家電台轉載）。
- **網址**（2026-11-12 SearXNG 預設開啟時加強，`normalize.normalize_url`／`clean_url`）：存的連結去掉追蹤參數（`utm_*`、`fbclid`、`gclid`、`msclkid`、`mc_cid`…）與預設埠，
  AMP 快取（`*.cdn.ampproject.org/c/s/…`、`google.com/amp/s/…`）換成媒體自己的網址；比對用的鍵另外不分 http／https、`www.`／`m.`／`mobile.`／`amp.`、
  `from`／`ref`／`cid`／`share` 這類來源參數、參數順序、結尾斜線、`/amp/` 路徑段、`.amp.html`、`?outputType=amp`——只做網址本身就能確定的改寫，
  路徑不同的 AMP 版（`ettoday.net/amp/amp_news.php7?news_id=…`）靠標題去重。同一則同時有一般網頁與 AMP／手機版時留一般網頁——
  同一批之內如此，跨批次也一樣（2026-11-12 審查後，`service._prefer_canonical`）：先存的是手機版／AMP 版（例如 SearXNG 先找到 `m.udn.com/…`，GDELT 晚 15–30 分鐘才收錄），
  之後找到一般網頁時把那一列的 `url`、`outlet`、`domain` 換成一般網頁；`source`、標題、時間維持先存的。反過來（已存一般網頁、之後才找到手機版）不會改。
  **搜尋引擎轉址**（`news.google.com`、`google.*`、`bing.com`、`search.yahoo.com`、`duckduckgo.com`、`search.brave.com`、`qwant.com`、`startpage.com`、短網址 `t.co`、`bit.ly`…）
  一律丟掉，**不解析**（解析等於去抓搜尋引擎或媒體網站）。
- **去重**：同一網址（上面的比對鍵）或幾乎相同的標題（相似度 ≥ 0.88）只留一則；原始媒體優先於轉載站（Yahoo、LINE TODAY、MSN、iHeart…），一般網頁優先於 AMP／手機版，再來是先刊出的。
  GDELT 與 SearXNG 找到同一則時，資料庫只有一列（先存的那個來源；每檔每個比對鍵一列；連結是一般網頁的版本，見上）。
- **時間**：GDELT 是 `seendate`（GDELT 看到的時間，通常晚刊出 15–30 分鐘）；AI 搜尋的 `page_age` 只有日期時 `date_only: true`；SearXNG 以天計的相對時間（「1 天前」）也是 `date_only`。
  查詢窗（7 天）對 `date_only` 的標題放寬一天（存的是那天台北時間 0 點，那天有任何一段在窗內就收），整天都在窗外的丟掉（「10 天前」；2026-11-12 審查前 `date_only` 完全不檢查查詢窗，`service.to_headlines` 與 `ai_search.select_items` 現在同一條規則）。

### 儲存（migration `0011`，接在 `0009` 後，整合時再接上 `0010`）

| 資料表 | 內容 |
|---|---|
| `news_articles` | 每檔每個網址一列：`title`、`outlet`、`domain`、`url`、`published_at`、`date_only`、`source`。**只有中繼資料**：沒有任何欄位能放內文、描述或圖片。刊出後 `NEWS_RETENTION_DAYS`（30）天刪除（每次批次開始時清） |
| `news_blocked_domains` | 下架封鎖清單（網域，含子網域）＋原因 |
| `news_tracked_views` | 「最近看過」：只有代號與時間，**沒有使用者**；`/news` 每 10 分鐘最多寫一次 |
| `news_fetch_state` | 每個來源×代號的最後嘗試／成功、結果與筆數；`symbol="*"` 是整個來源的暫停時間；SearXNG 另有 `symbol="@<引擎>"`（例如 `@bing news`）記每個上游引擎的結果、連續失敗與暫停時間（不用新 migration） |

### Worker 與 CLI

- `news_refresh`：每 `NEWS_REFRESH_MINUTES`（45）分鐘，追蹤的股票＝任何人帳本／持股快照／自選裡的（`archive.tracked_symbols`）＋最近 `NEWS_VIEW_DAYS`（3）天看過的，
  最久沒更新的先跑，每批最多 `NEWS_MAX_SYMBOLS_PER_RUN`（150）檔，批次最長是間隔的 80%（不會卡住其他排程）。全體共用。
- `uv run python -m forliosa.news refresh [--symbol 2330.TW] [--no-ai]`：立即更新。
- `uv run python -m forliosa.news searxng-check "台積電" [--language en] [--url http://localhost:8080]`：SearXNG 健康檢查（`/healthz`）＋查一次新聞，
  印出結果數、各引擎的結果數、沒有回應的引擎與原因（拒絕或暫時錯誤）。只印網址的 scheme、主機與埠（帳密會被去掉），不寫資料庫；回應正常時結束碼 0。
- **下架**：`uv run python -m forliosa.news block udn.com --reason "2026-11-20 來函要求下架"` 立刻刪除該網域（含子網域）已存的標題，之後不再存也不顯示；
  `unblock`、`blocked` 列出清單；環境變數 `NEWS_BLOCKED_DOMAINS=a.com,b.tw` 也會隱藏（但不刪資料列）。

### 環境變數

`NEWS_ENABLED`（true）、`NEWS_REFRESH_MINUTES`（45）、`NEWS_RETENTION_DAYS`（30）、`NEWS_VIEW_DAYS`（3）、`NEWS_MAX_SYMBOLS_PER_RUN`（150）、
`NEWS_GDELT_ENABLED`（true）、`NEWS_GDELT_INTERVAL_SECONDS`（6）、`NEWS_AI_ENABLED`（true）、`NEWS_AI_BUDGET_USD`（30）、`NEWS_AI_MIN_ITEMS`（3）、
`NEWS_AI_INTERVAL_HOURS`（24）、`AI_MODEL_NEWS`（預設 `AI_MODEL`）、`NEWS_SEARXNG_ENABLED`（true）、`NEWS_SEARXNG_URL`（不設＝依 `FORLIOSA_ENV` 的預設；設成空字串＝關）、
`NEWS_SEARXNG_ENGINES`（`bing news,duckduckgo news,brave.news`，要和 `deploy/searxng/settings.yml` 一致，有測試檢查）、`NEWS_SEARXNG_INTERVAL_SECONDS`（10，最少 10）、
`NEWS_SEARXNG_CACHE_MINUTES`（60，最少 30）、`NEWS_SEARXNG_SKIP_GDELT_ITEMS`（8）、`NEWS_SEARXNG_BACKOFF_MINUTES`（120）、`NEWS_SEARXNG_TIMEOUT_SECONDS`（20）、
`NEWS_YAHOO_RSS`（true，只在 personal 有效）、`NEWS_BLOCKED_DOMAINS`。`SEARXNG_SECRET` 只設在 searxng 服務上（api／worker 不用）。

### 授權與顯名

- `datapolicy.DATASETS` 多 `gdelt/doc`（`license_status: "open"`：可商用、需引用 GDELT 並連到 gdeltproject.org）與 `yahoo-rss/stock`（新的 `non_commercial`：
  commercial 下不顯示、也不列在 `/meta/attributions`，改在 `not_used` 說明）。每則新聞的 `sources` 是它的顯名聲明；前端在頁尾的「資料來源與授權」引用 The GDELT Project（連到 gdeltproject.org）。
- AI 工具 `get_news` 與 `/news` 相同：先官方公告、再新聞報導（每則有 `category`、`outlet`、`source`、網址），另回所有項目去重後的 `sources`
  （GDELT 的引用、公告的 OGDL 顯名），`note` 請模型提到標題時寫出媒體與連結、細節再用 `web_search`；工具說明不再寫「不含媒體」。
- `_item()` 的 `commercial` 改成只有 `conditional` 資料集會因 `TAIFEX_CONDITIONAL_CONFIRMED` 變成可商用（以前非商用資料集也會被開關影響）。

### 測試（不連網）

`tests/news/`：`test_parsers.py`（GDELT ArtList、429 文字、空結果 `{}`、查詢字串；Yahoo RSS；白名單）、
`test_normalize.py`（空白、尾巴、媒體名稱、網址與比對鍵（追蹤參數、http／https、www／m.／amp.、AMP 路徑與 AMP 快取）、搜尋引擎轉址丟掉、相關性、去重、封鎖清單、整條管線）、
`test_searxng.py`（預設開啟與各環境的網址、關掉的方法、中文／英文查詢與暫停引擎時的 `engines=`、解析（時間、相對時間、轉址、沒有時間）、
連不上／5xx／不是 JSON → `SourceDown`、403／429 → `SourceBlocked`、全部引擎失敗或拒絕、`/healthz`、間隔 10 秒與一次一個、`searxng-check` 輸出與不印帳密、
`deploy/searxng` 的 settings.yml（引擎清單＝設定、只對內、JSON、不用代理；每個 `network:` 參照在釘住版本的預設引擎定義下都解析得到——
`fixtures/searxng_default_engines_2026.10.28-c360868e5.yml` 是該版 `searx/settings.yml` 的原文摘錄，換版時測試會要求換檔）、Dockerfile 釘版本與 digest、
compose 只綁 127.0.0.1 並把 `settings.yml` 唯讀掛進容器、`railway.toml` 寫明 `PORT=8080` 必填；週／月／年的相對時間不收）、
`test_searxng_service.py`（連不上時暫停、GDELT 照常、`/news` 照常；全部引擎失敗；拒絕的引擎暫停並從下一次查詢拿掉、連 3 次逾時暫停；全部暫停時整個暫停到最早恢復；
間隔與每檔 60 分鐘快取；GDELT 已有 8 則就略過；和 GDELT 合併：同一則只存一列、追蹤參數去掉、AMP 與手機版合併成一般網頁、轉址與無關的丟掉；一週以前的（「3 weeks ago」「2 週前」「10 天前」、三週前的時間戳）不存；美股英文查詢；
AI 補缺依 GDELT＋SearXNG 合計、SearXNG 暫停時不擋 AI）、`test_service.py`（預設開 GDELT 與 SearXNG、批次與增量查詢、429 暫停與加倍、
連續錯誤略過、追蹤清單、封鎖清單與 CLI、保存期限、先存的手機版／AMP 連結之後換成一般網頁、AI 補缺只取搜尋結果、預算上限、沒有金鑰、`/news` 形狀、Yahoo 只在 personal、美股、顯名、
AI 工具 `get_news` 帶媒體與來源、worker）；相關性另測一般英文單字的英文簡稱（WIN、DELTA、Apple）。
fixture 是 2026-11-12 的真實回應裁短：`gdelt_tsmc_taiwan_live_20261112.json`（17 則）、`gdelt_nvda_english_live_20261112.json`（16 則）、
`gdelt_gudeng_empty_live_20261112.json`（`{}`）、`gdelt_rate_limited_live_20261112.txt`、`yahoo_rss_2330_live_20261112.xml`（8 則，描述只留前 12 個字）。
SearXNG 的 fixture 是**合成的**（沙盒連不到上游搜尋引擎）：照 SearXNG 2026.10.28 的 JSON 輸出格式（`searx/webutils.py` `get_json_response`、`MainResult.as_dict`）手寫，
每個檔案的 `_comment` 都標 `SYNTHETIC`：`searxng_tsmc_zh_tw_synthetic.json`（12 則：重複 GDELT 的一則、Bing 只有相對時間、AMP 與一般網頁、手機版、兩個轉址、無關、沒時間、太舊）、
`searxng_partial_synthetic.json`（Bing CAPTCHA、Brave 逾時）、`searxng_all_down_synthetic.json`、`searxng_all_refused_synthetic.json`、`searxng_nvda_en_synthetic.json`。
所有 SearXNG 請求都走 `httpx.MockTransport`；`tests/conftest.py` 的 autouse fixture 讓其他請求一律連線失敗。

### 實測（2026-11-12）

- 沙盒共用出口對 GDELT 常回 429（「Please limit requests to one every 5 seconds」）或中途斷線：退避 20 秒起、每次加長，約 20 分鐘內成功 2 次（NVIDIA 75 則、家登 0 則）。
  正式環境是自己的出口 IP，每 6 秒一次應該沒問題；遇到 429 會自動暫停。
- `(Gudeng OR 3680) sourcecountry:taiwan` 三天內 0 則：中小型股常常要靠 AI 補缺。
- **SearXNG 沒有實測**：沙盒連不到上游搜尋引擎、也沒有 Docker。只從 Docker Hub 確認了釘的 tag（`2026.10.28-c360868e5`，2026-10-28 發布）、
  digest 與 image 設定（設定檔 `/etc/searxng/settings.yml`、聽 `[::]:8080`、`SEARXNG_SECRET` 會覆蓋 `server.secret_key`），並對照該版原始碼：
  Bing News 的結果**沒有** `publishedDate`（只有 `metadata` 裡的相對時間）、DuckDuckGo News 用時間戳、Brave News 常常只有「N hours ago」；
  DuckDuckGo News 與 Brave News 沒有宣告支援 `time_range`，SearXNG 會在有 `time_range` 時跳過它們，所以 `settings.yml` 對這兩個設 `time_range_support: true`（它們忽略時間範圍，worker 自己丟掉一週以前的：
  以週以上計的相對時間不收、只有日期的超過查詢窗一天就丟）。
  **啟動失敗（2026-11-12 審查找到，已修）**：該版預設的 `brave.news` 寫 `network: brave`（共用名為 `brave` 的引擎的連線設定），而 `keep_only` 把 `brave` 引擎移除了，
  `searx/network/network.py` `initialize()` 會 `KeyError: 'brave'`——`webapp.py` 在匯入時就執行 `init()`，所以 granian 起不來、`/healthz` 永遠不通，worker 只會看到 `SourceDown` 而默默暫停。
  修法：`settings.yml` 的 `outgoing.networks` 加 `brave: {}`（用預設連線設定，仍不用代理）；在 `engines:` 底下對 `brave.news` 寫 `network: {}` 沒用（SearXNG 把 dict 合併進字串，字串不變）。
  這是對照原始碼的結論，沙盒不能執行 SearXNG；`test_searxng.py` 用該版預設引擎定義的摘錄模擬 SearXNG 的合併與網路參照。
  另外本機 compose：官方 image 對 `/etc/searxng` 宣告了 `VOLUME`，`up -d --build` 會沿用舊容器的匿名 volume（裡面是第一次建置時的 `settings.yml`），
  所以 compose 改成把 `deploy/searxng/settings.yml` 唯讀掛到 `/etc/searxng/settings.yml`；Railway 每次部署都是新容器、不掛 volume，不受影響。
  第一次部署後要跑 `searxng-check` 確認（`docs/deploy.md` 2.6 節）。

### 待產品負責人確認

1. **AI 補缺的頻率**：目前同一檔 24 小時最多一次、每批最多 10 次、每月 US$30 封頂（約 600–1,000 次搜尋）。追蹤的小型股多時，月中可能就用完；要不要改成只補「有人持有」的股票？
2. **美股來源**：`sourcelang:english` 會收到很多地方報與轉載（印度、澳洲地方報）。要不要改成只收美國／英國主要媒體（例如加 `sourcecountry:us`），或只用 AI 補？
3. **專欄名稱**：「| 台股雜談」這類專欄名稱目前保留（和 Google 財經一樣）。要不要也去掉？
4. **Yahoo股市 RSS 的個股網址**：`?s=<代號>` 回的是全站最新新聞，只能靠標題篩選，命中率低。個股 RSS 的正確網址要在一般瀏覽器開 rss-index 產生一次確認。
5. **SearXNG 對上游的請求像瀏覽器**（SearXNG 預設開啟後新增）：SearXNG 去問 Bing／DuckDuckGo／Brave 時，用的是瀏覽器樣式的 User-Agent 與連線特徵（SearXNG 本身的做法，
   不這樣多數引擎不回答），和研究 §10 寫的「不偽裝」字面上衝突。我們自己的程式（worker → SearXNG）仍是誠實的 User-Agent、不換 IP、不用代理、被擋就停。
   建議：A（接受，視為「自動查詢上游搜尋引擎」風險的一部分，寫進 §10）；B（在 image 裡把 SearXNG 的 User-Agent 換成誠實字串，預期多數引擎會直接拒絕，SearXNG 形同無效）。
6. **引擎清單**：只開 Bing News、DuckDuckGo News、Brave News（都連到媒體原網址）。Google News 的連結是轉址（會被丟掉）、Reuters 等引擎是直接查新聞網站（不做），所以沒開。
   上線後如果 SearXNG 幾乎都被擋，要不要加 Qwant News（沒有 zh-TW、常被 DataDome 擋）？建議：先不加，看一週的 `searxng-check` 與 worker 記錄再說。
7. **每批上限**：追蹤 150 檔時，SearXNG 每檔間隔 10 秒、加上 GDELT，一批約 35 分鐘，可能碰到批次時限（間隔的 80%）而留到下一批。
   建議：維持（最久沒更新的先跑；每檔 60 分鐘快取與「GDELT 已有 8 則就略過」會讓實際查詢少很多）；若記錄常出現 `time is up`，再把 `NEWS_REFRESH_MINUTES` 調成 60。

## 2026-11-12 相關股票、公司資料、外資持股前 20 名（個股頁補強第 4–8 項）

產品負責人決定（`PRODUCT.md`「個股頁補強」4、6、7、8；第 5 項的授權詢問信稿在 `docs/outreach/`，第 9 項 ETF 淨值見下方「2026-11-12 ETF 淨值與折溢價」）。
研究：[`docs/research/news-and-external-sources.md`](../../docs/research/news-and-external-sources.md) §8（相關股票）、§9（公司資料）。
形狀見 [`docs/api-contract.md`](../../docs/api-contract.md)「相關股票、關於〈公司〉、上市股票外資持股前 20 名」。

### 新的存檔（都是政府資料開放授權；欄位名稱在 `marketdata/company_data.py`，2026-11-12 真實回應核對）

| 資料表 | 來源 | 群組／頻率 | 注意 |
|---|---|---|---|
| `board_links` | 證交所 `t187ap11_L`、櫃買 `mopsfin_t187ap11_O`〈董事、監察人持股餘額明細〉（資料年月約落後 6 週） | `monthly`（每月 10、25 日 10:20） | 只留**職稱含「本人」且姓名＝上市櫃公司全名**的列（公司擔任法人董事或大股東），比對用 `company_profiles` 的公司名稱（去空白、相容漢字正規化，其餘完全相同）。**自然人列在解析迴圈裡就跳過**：不存、不記 log、不計數；國發基金這類非上市櫃法人也不留；設質欄位不讀。一列＝(公司, 持有公司, 資料年月)＋職稱合併（「董事長、董事、大股東」）＋目前持股（公司的股數）。2026-11-12：1,653 列、560 家公司 |
| `index_constituents` | 櫃買 `tpex50_constituents`〈富櫃五十指數成分股〉 | `tpex`（每天） | 每天一份 50 檔 |
| `holder_counts_monthly` | 集保 `2-22`（上市）、`2-23`（上櫃）〈有價證券集中保管個別股票異動月分析表〉 | `monthly` | 集保股東戶數（ETF 受益人數）＋保管與發行千股數；只公布最新月份，所以每月存。同一檔可能出現兩次（006201），只留一列。讀取時上市、上櫃各用自己最新的月份（兩份公布日不同） |
| `foreign_holding_top20` | 證交所 `/fund/MI_QFIIS_sort_20`〈集中市場外資及陸資持股前 20 名彙總表〉 | `twse` | **沒有日期欄位**：21:00 後的執行算當天（交易日）、09:00 前算前一個交易日、白天（14:40）略過——證交所沒說幾點更新，避免把昨天的名單蓋成今天。同一天重跑會刪掉掉出名單的股票。2026-11-12 的名單大多是 KY 股（最高 99.53%），一般權值股不在榜 |
| `esg_product_output` | 證交所 `t187ap46_L_14`、櫃買 `t187ap46_O_14`〈ESG 資訊揭露－產品品質與安全〉的「依產品類別之產品產量」 | `monthly` | 只拿來給 AI 簡介當官方資料；N/A 不存 |
| `company_descriptions` | 中文維基百科（經 Wikidata 找條目）或 AI | worker `company_refresh`（每小時 :35） | 見下面「公司簡介」 |
| `sec_companies.profile` | SEC submissions | 跟著申報清單更新 | SIC 產業、營業地址的城市與州（外國公司給國家）、交易所、曾用名稱；街道地址、電話、EIN 不存 |

`company_profiles.values` 多了 `hq`（縣市；地址本身不存）、`registered_in`（KY 等）、`website`（一律 https、主機小寫；`http//`、全形冒號也能解析）、
`auditor`（事務所名稱，`html.unescape`：「冠恆&#32852;合」→「冠恆联合」照原字、相容漢字 U+F997 →「聯」）、`transfer_agent`（只有名稱）、
**`chairman`、`president`（董事長、總經理照原文，例如台積電「總裁: 魏哲家」）**。發言人、代理發言人、簽證會計師姓名、電話、傳真、Email、統一編號都不讀。
每天覆寫同一列，不留歷史。這兩個姓名**只**從 `GET /instruments/{symbol}/company` 出去：`forliosa.ai` 不引用 `services/company.py`，
AI 工具（`get_stock_overview` 等）與所有提示（含 AI 簡介的提示）都不含姓名（`tests/company/test_company.py` 檢查），也不和董監持股、質押合併
（`board_links` 只有公司對公司）。**商用前請律師確認**（個資法第 19 條「已合法公開」的範圍，研究 §9）。

**總部縣市**：證交所的中文地址取開頭的縣市（去掉郵遞區號、「台灣」，「巿」當「市」）；「新竹科學園區」「新竹市科學工業園區」一律顯示「新竹科學園區」，
其他科學園區照原文；「北市…」這種縮寫不猜。櫃買只有英文地址：只有出現**恰好一個**明確的縣市（New Taipei、Taipei City、Taoyuan、Hsinchu County…）
或新竹科學園區時才給。後面接 Rd.／Road／St.／Ave.／Ln.／Alley 等的是路名、不算城市（「Keelung Rd., …, Taipei City」→ 台北市；
「Ping-Tung Rd., Ping-Jen City, Taoyuan Hsien」→ 桃園市）；「Taipei」單獨出現（可能是舊台北縣）、「Hsinchu」「Chiayi」單獨出現（市或縣）時給 `null`，
即使另有一個城市名（「Keelung Rd., Xinyi Dist., Taipei 110」不會變成基隆市）。
2026-11-12：上市 1,099 家有 1,064 家有縣市；上櫃 897 家有 730 家。

### 相關股票（`services/related.py`）

- **基準卡**：上櫃且在最新一份富櫃五十成分股 → 006201「富櫃五十成分股（櫃買中心公布）」；其他 → 使用者偏好的比較基準（`preferences.benchmark`）
  「你的比較基準」；基準是 `^TAIEXTR`／`^TPEXTR` 時是指數卡（`is_index`，存檔指數收盤），沒有存檔就不放。**從不寫「某 ETF 持有本股」**。
- **關係企業**：`board_links` 的**每個資料集各自**最新資料年月（證交所 `t187ap11_L` 與櫃買 `mopsfin_t187ap11_O` 公布日不同，取全體最新會讓另一個市場的連結整批消失），
  兩個方向都算（「台積電是其法人董事及大股東」「世界的大股東」），市值大的先；存託憑證（91）不放。`notes` 列出用到的資料年月（兩個月時「2026 年 9 月、2026 年 10 月」）。
- **同業**：同產業別、市值（已發行股數 × 最新存檔收盤）對數距離最近；產業市值最大的不是本股時先放它（「半導體業市值最大」）。31 其他電子業改用電子類（24–31）
  「電子類、市值相近」，20 其他業改用使用者自己的台股持股「你的持股、市值相近」；這兩類關係企業最多 2 張。
- **組合**：基準 1 張 → 關係企業 1 張（雜項 2 張）→ 同業補滿 → 還不滿 4 張再補關係企業。組不出卡的候選（指數沒有存檔收盤、公司沒有任何收盤）跳過，
  由同一類的下一個候選補上。卡片：名稱用官方簡稱（公司基本資料、基金簡稱），收盤與漲跌用報價
  （除權息日用參考價算），`sparkline` 是最近約 35 天的存檔收盤。
- **ETF 頁**：t187ap47_L 的追蹤指數＋基金類型相同（槓桿／反向型是另一類型，所以 0050 的同指數只有 006208），再補同類型、集保股東戶數最多的
  （戶數用該市場資料集最新的月份）。
  櫃買 ETF 沒有基金基本資料，目前只會拿到空的列（前端不顯示）。
- 2026-11-12 模擬（測試用收盤）：2330 → 0050、創意、聯發科、日月光投控；5347 → 006201、台積電、環球晶…；2317 → 0050、鴻華先進、廣宇、電子類同業。

### 公司簡介（`services/company.py`、`marketdata/wikimedia.py`）

1. **找條目**：Wikidata `wbsearchentities`（zh-tw，簡稱與全名各一次）→ `wbgetentities`（claims、zhwiki sitelink、中文標籤與別名）→
   先找 P414（交易所）＝證交所 Q548621／櫃買 Q5598539（美股：NYSE Q13677、Nasdaq Q82059）且 P249（代號）限定詞＝代號的項目；
   沒有就找中文標籤或別名**完全等於**公司全名的項目（環球晶的項目沒有 P414，靠別名「環球晶圓股份有限公司」找到）。只認有 zh.wikipedia 條目的項目。
2. **節錄**：`zh.wikipedia.org/api/rest_v1/page/summary/{title}`，`Accept-Language: zh-tw`（台灣字形）；在句號（。！？）處截斷，累積到 260 字為止（至少第一句）；
   **文字不改寫**、不送進任何 AI；存條目標題、`revision_id`、Wikidata 編號。前端標「節錄」並連到條目（`zh.wikipedia.org/zh-tw/<標題>`）與 CC BY-SA 4.0。
3. **AI 簡介**（沒有條目時）：一次非串流呼叫（`AI_MODEL_COMPANY`，預設 Haiku 等級），提示只有官方資料：簡稱、全名、產業別、成立年、掛牌年與市場、總部或註冊地、
   實收資本額（「約 2,593 億元」）、最近月營收規模、ESG 產品類別文字；**不含董事長、總經理**。回覆超過 160 字、含網址或含公司負責人姓名就丟掉
   （姓名先拆解：去掉「總裁: 」這類職稱前綴、依頓號／逗號拆成多人，有空白的名字連起來與分開都比對；少於 2 個字（拉丁字母 3 個）的部分不用）。
   `facts_key`＝這些資料的 SHA-256：資料沒變不重寫。`company_descriptions.sources` 記下這些資料來自哪些資料集（公司基本資料、月營收、ESG），
   `/company` 的 `sources` 會一併列出。回覆被丟掉或 API 錯誤時記下 `ai_failed_key`、`ai_failures`、`ai_attempted_at`：同一份資料 24 小時後才再試，
   之後每次加倍（最多 30 天）；資料變了就立刻再試。系統付費（`ai_usage.feature = "company"`、`user_id` 空），每批最多 `COMPANY_AI_PER_RUN`（10）次
   **呼叫**（被丟掉的回覆、錯誤都算）。
4. **排程**：worker `company_refresh` 每小時，處理追蹤中的股票（帳本、持股、自選、`NEWS_VIEW_DAYS` 內看過的；`/company` 也會記錄「看過」），
   沒查過的先、每批最多 `COMPANY_MAX_SYMBOLS_PER_RUN`（15）次維基查詢；維基每 `COMPANY_WIKI_REFRESH_DAYS`（30）天重查一次（條目消失就改回沒有）。
   CLI：`uv run python -m forliosa.services.company refresh [2330.TW …]`。
5. **禮貌**：User-Agent `Forliosa/1.0`，有 `WIKIMEDIA_CONTACT` 時加「(聯絡方式)」；**不用 `SEC_CONTACT_EMAIL`**。同一個程序一次只發一個 Wikimedia 請求
   （全域鎖、每個主機間隔 1.5 秒），429／403 → 這批停止、6 小時內不再查，不換身分、不換 IP。白名單只多兩個網址：`www.wikidata.org/w/api.php`、
   `zh.wikipedia.org/api/rest_v1/page/summary/`。

### 環境變數

`COMPANY_DESCRIPTIONS_ENABLED`（true）、`COMPANY_AI_ENABLED`（true）、`COMPANY_AI_PER_RUN`（10）、`COMPANY_MAX_SYMBOLS_PER_RUN`（15）、
`COMPANY_WIKI_REFRESH_DAYS`（30）、`AI_MODEL_COMPANY`（預設 `AI_MODEL`）、`WIKIMEDIA_CONTACT`（選填）。

### 授權與顯名

`datapolicy.DATASETS` 多：`twse-openapi/foreign_top20`、`twse-openapi/board`、`tpex-openapi/board`、`tpex-openapi/tpex50`（data.gov.tw 20220）、
`tdcc-opendata/holders_twse`（20603）、`tdcc-opendata/holders_tpex`（20605）、`twse-openapi/esg_products`、`tpex-openapi/esg_products`（以上 OGDL）、
`wikipedia/zh`（`open`，CC BY-SA 4.0：「依 CC BY-SA 4.0 節錄（不改寫）」）、`wikidata/entities`（`open`，CC0）。`/meta/attributions.notice` 多一行維基百科。
公司基本資料的 `used_for` 加上「關於」的欄位。

### 測試（不連網）

- `tests/archive/test_stock_page_jobs.py`：董監持股只留公司對公司（fixture 的自然人姓名已換成「自然人NN」，國發基金、華創車電不留，log 也沒有）、
  集保 2-22／2-23 去重、前 20 名依執行時間定日期、富櫃五十、ESG、地址與網址規則、沒有公司基本資料時的錯誤、冪等。
- `tests/company/`：`test_related.py`（台積電、世界、鴻海、指數基準、0050、美股、存託憑證、兩個資料集年月不同、組不出卡時由下一個補上）、
  `test_company.py`（條目比對、節錄、User-Agent、維基→AI、facts_key 快取、含人名（含職稱前綴）的 AI 回覆丟棄、失敗後退避與每批呼叫上限、
  AI 簡介的來源、429 暫停、`/company` 台股／KY／ETF／美股、AI 工具不含姓名、上市前 20 名（在榜時仍說明三大法人、掉出名單時沒有舊的持股比））。
- 公司基本資料存檔失敗（資料庫鎖住、逾時）時，log 與 `JobResult` 只有驅動程式的錯誤類別與第一行：engine 設 `hide_parameters=True`，
  `archive.safe_error` 也不留 Postgres 的 DETAIL（會重複整列資料，含董事長、總經理）。
- fixture 是 2026-11-12 真實回應裁短：`twse_t187ap11_l`／`tpex_t187ap11_o`（29／16 列）、`*_t187ap03_*_related`（13／5 家）、`twse_t187ap47_l_related`、
  `tpex_tpex50_constituents`、`twse_mi_qfiis_sort_20`、`*_t187ap46_*_14`、`tdcc_2-22`／`2-23`、`sec_submissions_tsm_meta`、AAPL submissions 補上地址與曾用名稱；
  `tests/company/fixtures/` 的 Wikidata 搜尋（台積電、環球晶、家登＝沒有、櫃買中心）、項目（只留 P414）、台積電條目摘要（去掉圖片欄位）。

### 實測（2026-11-12）

- 沙盒共用出口對 Wikimedia 常回 429（「You are making too many requests」）：一次一個請求、間隔 8 秒、429 後等 2 分鐘，約 20 分鐘拿到 7 個回應；
  `list=search` 的 `haswbstatement` 查詢一直 429（也不支援限定詞），所以改用 `wbsearchentities`＋`wbgetentities`。正式環境建議設定 `WIKIMEDIA_CONTACT`。
- 環球晶的條目摘要四次都 429，沒有 fixture；測試裡家登（沒有 Wikidata 項目）走 AI 簡介。

### 待產品負責人確認

1. **董事長、總經理**：照決定顯示、標來源；正式收費前請律師確認（研究 §9）。要不要先只在登入後顯示（現在就是只有登入後才看得到）？
2. **外資持股前 20 名的日期**：證交所沒說明更新時間，目前晚上 21:00 後的存檔算當天。若發現晚上還是前一天的名單，改成只在早上存（算前一個交易日）。
3. **AI 簡介的範圍**：目前只寫追蹤中的股票（持有、自選、3 天內看過），每批最多 10 則。要不要讓沒有條目的股票第一次被看時就立刻產生（多一次 AI 呼叫、頁面稍後更新）？
4. **ETF 頁的「相關股票」**：上櫃 ETF（006201 等）沒有基金基本資料，現在不顯示這一列。要不要改用「同類型、受益人數多」的上市 ETF 補？

## 2026-11-12 ETF 淨值與折溢價（個股頁補強第 9 項）

產品負責人決定（`PRODUCT.md`「個股頁補強」9：驗證 data.gov.tw 11109，有 ETF 淨值就做盤後折溢價）。驗證紀錄：
[`docs/research/news-and-external-sources.md`](../../docs/research/news-and-external-sources.md) §11；形狀見
[`docs/api-contract.md`](../../docs/api-contract.md)「ETF 淨值與折溢價（2026-11-12）」。migration `0012`（接在 `0011` 後）。

### 來源（2026-11-12 實測）

| 項目 | 內容 |
|---|---|
| 資料集 | data.gov.tw 11109〈證券投資信託基金每日淨值〉，**提供機關「金融監督管理委員會證券期貨局」**（data.gov.tw 資料集頁面的「提供機關」欄與 schema.org `creator`，2026-11-12 讀取），授權「政府資料開放授權條款-第1版」，更新頻率每 1 日；聯絡人是投信投顧公會 |
| 端點 | `GET https://www.sitca.org.tw/MemberK0000/F/03/nav.csv`（資料集唯一的資源連結）：`application/octet-stream`、UTF-8 BOM、CRLF、沒有引號，約 500 KB、3,676 列 |
| 欄位 | 日期（西元 `YYYYMMDD`）、會員代號、公司名稱、基金統編、基金代號、基金名稱、基金淨值、漲跌、漲跌幅、類型代號、幣別、**受益憑證代號** |
| 內容 | **每檔基金（級別）只有最新一筆淨值**，沒有歷史。海外標的的列是前一個營業日（當天 3,183 列是 11/11、493 列是 11/12；00679B、00720B 是 11/11）。淨值 `-` 的列 172 筆（都不是 ETF） |
| ETF | 受益憑證代號就是交易代號（`00` + 2–4 位數字 + 可選字母）：244 列、沒有重複、全是新臺幣。0050 101.04、006208 231.48、0056 52.22、00878 32.93、00919 30.94、00981A 24.12、00996A 11.25、006201 35.82、00679B 26.4989（11/11） |
| 涵蓋 | 和當晚兩個交易所的收盤檔比對：上市 246 個 `00` 代號有 214 個在檔、上櫃 118 個只有 27 個。不在檔的：期貨信託 ETF（`…U`，例如 00635U）、外幣交易線（`…K`）、**多數上櫃債券 ETF**（00687B、00694B、00695B…；00679B、00720B 在） |
| 更新時間 | 研究時看到 20:19 更新；同一晚 22:01（Last-Modified）又更新一次 |
| 白名單 | `marketdata/http.py` 只加這一個檔案的完整網址（投信投顧公會網站其他頁面不在內），`sitca.org.tw` 每 2 秒最多一次；誠實的 User-Agent，403／429／轉址不重試 |
| 顯名 | `datapolicy.DATASETS["sfb-opendata/nav"]`：「金融監督管理委員會證券期貨局〈證券投資信託基金每日淨值〉（2026），依政府資料開放授權條款第 1 版」，`license_status: ogdl`、`basis: data.gov.tw 11109`；來源鍵 `sfb-opendata` |

### 存檔（`archive.py`：`Archiver.etf_navs`，群組 `nav`）

- 解析在 `marketdata/fund_nav.py`（`parse_nav_csv`）：只留受益憑證代號符合 ETF 代號、日期與淨值（> 0）都有的列；同一代號出現兩次留日期新的。
  **欄位改名、空檔、整份沒有任何 ETF 列都記錯誤**，不寫 0 筆了事，`dataset_status["sfb-opendata/nav"]` 也不動。
- **只存我們認得的 ETF**：代號在最近 30 天有證交所／櫃買 OpenAPI 的存檔收盤（`prices_daily` 的 `twse-openapi`／`tpex-openapi`，後綴決定 `.TW`／`.TWO`），
  或在商品主檔且 `type == "etf"`。其他基金（`T0102Y` 這類）、FinMind 或示範資料的收盤都不算。
- 資料表 `etf_navs`：(symbol, date) 主鍵、`nav`、`currency`、`fund_name`（基金名稱原文）、`source`、`fetched_at`。冪等 upsert；同一天的淨值更正會覆蓋。
- 排程：交易日 21:40（`EVENING_GROUPS`，排在價格存檔之後）＋ **08:10 再讀一次**（`MORNING_GROUPS`）：檔案只有最新一筆，21:40 之後才公布的淨值若不再讀，
  隔天晚上就被新的一天蓋掉。手動：`uv run python -m forliosa.archive run --only nav`。
- 2026-11-12 當晚證交所 `STOCK_DAY_ALL` 到 22:15 仍是 11/11 的收盤（櫃買的收盤檔已是 11/12），所以上市 ETF 的當天折溢價常在隔天 08:10 收盤存檔後才算得出來。

### 折溢價（`services/etf_nav.py`，`GET /instruments/{symbol}/overview` 的 `etf_nav`）

- 折溢價 = 收盤 ÷ 淨值 − 1（比率，6 位小數），**只用同一天**：讀最新淨值往前 120 天的淨值與官方收盤，取兩者都有的日期；`premium_date` 是其中最新的一天。
  最新淨值日與最新收盤日不同時兩個都回傳（`nav_date`、`close_date`），前端寫出兩個日期與計算用的那一天。從不用示範資料或報價。
- `history`：同一天的點，最多 60 點（`HISTORY_POINTS`），由舊到新；`history_start` 是這檔第一筆淨值存檔日；不到 20 點（`MIN_POINTS`）時 `notes` 有「資料累積中：淨值自 … 起存檔」。
- `history_missing`：`history` 第一點到最後一點之間、沒有同一天配對的交易日（`services/etf_nav.missing_days`：證交所休市日存檔〔`market_calendar`〕，沒有時用內建表）。
  點數因此不一定是連續的交易日：前端標題寫「N 個有資料的交易日（M/D–M/D）」、有缺口時「中間 K 個交易日沒有資料」，圖上在缺的日子放 `null` 讓線斷開（`lib/etf-nav.ts` 的 `chartDays`）。
- `notes` 的其他固定文字：還沒有任何淨值存檔「資料累積中：ETF 淨值每個交易日晚上存檔」；有存檔但沒有這檔「〈證券投資信託基金每日淨值〉沒有這檔 ETF 的淨值」；
  有淨值但沒有同一天的收盤「還沒有同一天的收盤價與淨值，不計算折溢價」。
- `sources`：淨值的顯名＋收盤價的資料集（證交所〈上市個股日成交資訊〉或櫃買〈上櫃股票行情〉）：配對用到的，加上回傳的最新 `close` 的那一份——
  沒有同一天的配對時區塊仍顯示「收盤（M/D）」，所以它的顯名也要列；有淨值時 `overview.sources` 也加淨值的顯名。
- 只有台股 ETF（`type == "etf"`、非美股）有這個物件；股票、美股是 `null`。沒有淨值時所有數字（含 `close`／`close_date`）都是 `null`、`sources` 是 `[]`
  （和合約「沒有淨值時數字欄位為 null」一致；前端只顯示空狀態，報價在 overview 本身）。
- **追蹤誤差不做**：要用標的指數的每日報酬，指數（臺灣50 等）沒有開放授權。前端直接寫「追蹤誤差不提供：標的指數的每日資料沒有開放授權。」
- AI 工具 `get_stock_overview`：`overview` 不再重複 `etf_nav`，另給精簡的 `etf_nav`（最新數字、`history_range`〔`points` 是有資料的天數而不是交易日數、`from`／`to`、
  `missing_trading_days`、最高最低與日期〕、最近 10 點、`note` 要求只用同一天並說出日期、點數不要說成「近 N 個交易日」、說明沒有追蹤誤差）；工具說明加上 ETF 淨值與折溢價。

### 測試（不連網）

- `tests/archive/test_etf_nav_jobs.py`：真實檔的形狀（BOM、CRLF、13 個 ETF 列、`-`、前一個營業日、四位小數）、壞列與壞檔（欄位改名、空檔、沒有 ETF）、白名單只有這個檔案與顯名、
  只存認得的 ETF（主檔＋有 OpenAPI 收盤的上櫃 ETF，FinMind 收盤不算）、冪等、更正覆蓋、新的一天加一列、改名與 429 記錯誤且只請求一次、`dataset_status` 不動、全組執行時價格先於淨值。
- `tests/api/test_etf_nav_api.py`：同一天、日期不同時用最近的共同日、沒有共同日（示範收盤不算；顯示的收盤仍列顯名）、資料集沒有這檔／還沒有存檔（數字全為 `null`、沒有顯名）、
  股票與美股為 `null`、60 點上限、存檔缺口（`history_missing`，休市日不算）、AI 工具、`/meta/attributions`。
- fixture `sitca_nav_live_20261112.csv` 是 2026-11-12 真實檔裁成 18 列（13 個 ETF＋一般基金、美元級別、淨值 `-`、ETF 連結基金），保留 BOM 與 CRLF。

### 已知限制

- 檔案只有最新一筆：worker 停了的日子補不回來（沒有可商用的歷史淨值來源），走勢會有缺口（`history_missing` 列出，圖上斷線、標題寫出缺幾天）。
  臨時休市（颱風假）若不在證交所的休市日檔裡，會被算成缺口。
- 商品主檔目前只有 7 檔內建的台股 ETF（shioaji-data 的商品卡不含 ETF），00679B、00981A 等的淨值會存檔（有 OpenAPI 收盤），但搜尋不到、個股頁打不開（見待確認）。

### 待產品負責人確認

1. **商品主檔補上全部 ETF**：用證交所／櫃買收盤檔裡的名稱（政府資料開放授權）把 `00` 開頭的代號加進商品主檔，00679B、00981A 等才搜尋得到、有淨值與折溢價。建議做（另案，小改動）。
2. **不在 11109 的 ETF**（期貨信託 ETF、多數上櫃債券 ETF）：目前顯示「〈證券投資信託基金每日淨值〉沒有這檔 ETF 的淨值」。期貨信託基金的淨值可能在期貨公會或期交所，授權未查。建議先維持空狀態。

## 待產品負責人確認

1. **手續費捨去的順序**：目前是 `floor(成交金額 × 0.1425% × 折扣)`，低於最低手續費以最低計。
   有些券商是先算原始手續費 `floor(成交金額 × 0.1425%)` 再以「退佣」方式折扣，且最低 20 元是對原始手續費判斷。
   需要依各券商對帳單確認，可能要做成帳戶層級設定。
2. **二代健保的進位**：目前元以下四捨五入。另外 ETF 收益分配只有「股利所得」部分要扣，資本利得、
   收益平準金部分不用扣；目前以整筆金額判斷。
3. **美股股利預扣 30%**：目前自動帶入；若台美租稅協定生效或券商有不同處理，要再調整。
4. ~~**股利入帳日**~~：已由股利自動入帳處理（2026-11-12）：台股股利自動記在除息日（見「2026-11-12 股利自動入帳」），沒有另加
   `ex_dividend_date` 欄位。使用者自己記在發放日的紀錄，除息日到發放日之間的 TWR 仍會短暫偏低；美股股利仍手動記。
5. **FIFO 下的配股與分割**：目前按比例分攤到每一個批次（成本不變、每股成本下降）。
6. **正式登入**：`FORLIOSA_ENV=prod` 時開發登入關閉，而 Email／Google 登入不在這次範圍，
   正式環境暫時無法登入。前端在 401 時顯示說明（開發模式會自動以示範使用者開發登入）。
7. **美股資料源**：目前全部是示範資料；Yahoo 條款禁止轉發，需要決定有授權的來源。
8. **FinMind**：匿名額度很小且與同一 IP 共用；建議申請 token（非商用），商業化要升級 Sponsor Pro 或換來源。
9. ~~**MIS 非官方端點**~~：已移除（2026-11-12）。要盤中走勢需購買證交所延遲（約 NT$30,000／月）或即時行情授權。
10. **shioaji-data AI 研究資料**（簡介、產業鏈、題材）授權待定：commercial 下 `GET /instruments/{symbol}` 的 `summary`、`chain_stage`、`themes` 不回（`null`／`[]`），personal 照樣顯示並標示來源。
11. ~~**`position` 已出清的股票**~~：已決定（2026-11-12）：`position` 維持 `null`，出清的回合與買賣點改由
    `GET /portfolio/closed` 與 `GET /instruments/{symbol}/position/history` 提供。
12. ~~**commercial 模式的歷史資料**~~：已決定（2026-11-12）：commercial 從不使用示範資料，存檔不足時回空並在 `notes` 說「資料累積中」。
13. ~~**上市股票三大法人**~~：已決定（產品負責人 2026-11-12）：不寄信給證交所、不買 Data E-Shop，上市股票的逐檔三大法人與外資持股**不顯示**
    （任何模式，含 FinMind：上市股票只向 FinMind 要融資融券，不下載法人與持股資料集；上櫃照常）。個股頁的空狀態可直接問 AI「最近外資對這檔的動向？」（建議問題 `foreign_flow`），AI 用網路搜尋新聞回答並附來源與日期；
    `web_fetch` 封鎖 `www.twse.com.tw`、`mis.twse.com.tw`。之後要用時：Data E-Shop「三大法人買賣超檔」或書面同意（詢問信草稿見 `docs/research/data-sources-licensing.md` §1.9）。
14. ~~**新聞來源**~~：已實作（2026-11-12）：GDELT＋自架 SearXNG（第三輪改為預設開）、兩者不足才 AI 搜尋、Yahoo股市 RSS 只在 personal；見「2026-11-12 新聞報導」與它的待確認事項。
15. ~~**定期定額**~~：已實作（2026-11-12）。待確認：扣款金額是否含手續費（目前股數 = floor(金額 ÷ 收盤價)，手續費另計）。
16. ~~**財報公布日**~~：已實作（2026-11-12），實際日期來自重大訊息與月營收資料集；查不到才用法定期限（`estimated: true`）。
17. ~~**美股基本面（SEC EDGAR）與匯率**~~：都已實作（2026-11-12）。美股財報與 8-K／10-Q／10-K 申報見「第四批」；USD/TWD 改用中央銀行
    〈銀行間新臺幣對美元收盤匯率〉（data.gov.tw 7232，OGDL），見「2026-11-12 匯率改用中央銀行開放資料」。
18. **月營收資料集是否逐日更新**：`t187ap05_L`／`mopsfin_t187ap05_O` 的「出表日期」在 2026-11-12 是 1151111（申報期限之後）。
    若它在每月 1–10 日逐日更新，「第一次看到的日期」就是實際公布日（誤差一天內）；若只在期限後產生一次，營收公布日會晚於實際。
    12 月初要觀察一次。
19. **重大訊息的連結**：OpenAPI 的重大訊息沒有單則網址，`/news` 的 `url` 先指向公開資訊觀測站重大訊息查詢頁
    （`https://mops.twse.com.tw/mops/#/web/t05st01`）。這個環境連不到 MOPS，網址格式沒能驗證。
20. **期交所有條件資料集的授權**（2026-11-12）：期貨／選擇權每日交易行情、每日外幣參考匯率、選擇權大額交易人等已每日存檔，
    commercial 下要等期交所書面確認才顯示。產品負責人已決定**先不寄信**；詢問信草稿留在
    [`docs/outreach/taifex-licence-inquiry.md`](../../docs/outreach/taifex-licence-inquiry.md)。日後寄出並取得同意後設定
    `TAIFEX_CONDITIONAL_CONFIRMED=true`（只同意部分資料集時，改逐一把 `license_status` 設為 `ogdl`）。USD/TWD 不受這個開關影響：
    2026-11-12 起用中央銀行 7232（已驗證、已實作），期交所〈每日外幣參考匯率〉只存檔。
21. ~~資本公積配發的稅務處理~~ **已決定（產品負責人 2026-11-12）：自動排除。** 記現金股利且沒有手動輸入二代健保時，
    依官方股利決議（`cash_sources`）把資本公積發放的部分排除：付款日對上 120 天內最近的除息日（有填每股股利時只對同金額的除息日），
    有股數就用「股數 × 每股資本公積」（元以下捨去），否則依比例；排除後的股利所得未達 2 萬就不扣，達到就以股利所得 × 2.11% 計。
    試算 `rules` 會列出「其中資本公積發放 X 元一般不屬股利所得，不計入」。對不上決議（上櫃沒有決議資料、存檔前的舊股利）時照整筆計算。
    已記的交易不會自動重算（自動入帳的股利例外：每次同步都依最新的預告與決議重算，見「2026-11-12 股利自動入帳」）。
22. **股利決議沒有對上除權息預告時**：目前顯示 `status: "resolved"`、`ex_dividend_date: null`，包括「其實已在存檔前除權息」的舊決議
    （例如台積電 2025Q4）。若前端覺得混淆，可以只顯示董事會日期在最近 N 天內的決議，請決定 N。
23. **刪除或改過的自動股利沒辦法恢復**：刪除（或修改）一筆自動入帳的股利後，略過紀錄永久保留，目前沒有端點列出或清除；使用者只能自己新增一筆。
    建議：先維持現狀，等有人反映再加 `GET /auto-dividend-skips` 與 `DELETE /auto-dividend-skips/{id}`（刪掉後下一次同步就補回），前端放在帳戶設定裡。

24. **美股商品清單**（2026-11-12）：SEC〈company_tickers.json〉有一萬多檔美股代號與公司名（英文），目前只用來查 CIK；商品搜尋與記帳
    只認內建的 AAPL、NVDA、VOO、QQQ。要不要把 SEC 的代號加進商品清單（搜尋、記帳、財報與申報都能用；但沒有中文名、沒有價格）？
    建議：加，但搜尋時排在台股之後、只在輸入英文代號時出現，並標「沒有報價」。
25. **美股財報的季度標示**（2026-11-12）：目前用公司會計年度（Apple 的 `FY2026Q1` = 2025-09-28～2025-12-27），表頭另標結束日。
    另一種是用日曆季（`2025Q4`）。建議：維持會計年度（和公司新聞稿、媒體報導一致）。

## AI（M4，2026-11-12）

程式在 `src/forliosa/ai/`（`keypool`、`tools`、`prompts`、`chat`、`store`、`scope`、`grounding`、`retention`、`suggestions`、
`why`、`analyst`、`smoke`）與 `api/routes/ai.py`；資料表 `ai_threads`、`ai_messages`、`ai_drafts`、`ai_usage`、`ai_why_cache`
（migration `0004_ai_threads_usage`；金鑰槽與保存期限的欄位、索引在 `0005_ai_key_slots_retention`）、`ai_analyst_views`
（`0009_ai_analyst_views`，見下方「法人觀點」）。合約見
[`docs/api-contract.md`](../../docs/api-contract.md)「AI（M4）」。

### 設定（環境變數）

| 變數 | 預設 | 說明 |
|---|---|---|
| `CLAUDE_API_KEY_1`、`_2`、`_3`…（大小寫不拘，例如 `Claude_API_KEY_1`） | — | API 金鑰；**編號就是金鑰槽（slot）**，每把放在各自的 workspace（各有自己的速率限制與花費上限）。都沒有時用 `ANTHROPIC_API_KEY`（slot 0）。也會讀工作目錄的 `.env`（環境變數優先）。日誌與回應只出現槽號（`#1`），從不出現金鑰 |
| `AI_KEY_<n>_MONTHLY_BUDGET_USD`（大小寫不拘） | 空（不限） | 第 n 槽每月（**UTC 月**，與 Anthropic 帳單同）估計花費上限；達到後該槽不再使用，釘在它上面的對話搬到別槽。估計值來自 `ai_usage.cost_usd`（`ai/pricing.py`），建議設得比 Console 的 workspace 花費上限低一點。0／空白＝不限 |
| `AI_KEY_STICKY_WAIT_SECONDS` | 5 | 對話釘住的槽在這幾秒內會恢復（例如 `retry-after: 2`）就等它；更久就搬到別槽 |
| `AI_KEY_COOLDOWN_SECONDS`、`AI_REQUEST_TIMEOUT_SECONDS` | 60、120 | 沒有 `retry-after` 時的冷卻秒數（視為「猜測」，全部槽都在冷卻時仍可試一次） |
| `AI_DEV_DUMMY_KEY` | `false` | 沒有金鑰時送一個占位字串，給會自動注入真金鑰的 proxy 用 |
| `AI_MODEL` | `claude-haiku-5-5` | 產品負責人指定；`AI_MODEL_CHAT`／`AI_MODEL_WHY`／`AI_MODEL_IMPORT`／`AI_MODEL_REPORT`／`AI_MODEL_ANALYST` 可個別覆寫 |
| `AI_EFFORT_CHAT`、`AI_EFFORT_WHY` | `low` | `output_config.effort`（Haiku 5.5 預設 medium，這裡明確設 low） |
| `AI_EFFORT_ANALYST` | `medium` | 法人觀點的 effort（要照多條規則逐筆整理，用 Haiku 5.5 的預設 medium；實測約 22–32 秒） |
| `AI_MAX_TOKENS_CHAT`、`AI_MAX_TOOL_ROUNDS` | 8000、8 | 每次呼叫的輸出上限、每輪最多幾次模型呼叫 |
| `AI_DAILY_MESSAGE_LIMIT` | 50 | 每人每天（台北日）提問數，0＝不限（產品負責人確認） |
| `AI_MONTHLY_TOKEN_BUDGET` | 3,000,000 | 每人每月（台北月）計費 token，0＝不限（計法見下；產品負責人確認） |
| `AI_THREAD_MAX_CONTEXT_TOKENS` | 90,000 | 一段對話的提示超過這個大小就要求開新對話（Haiku 5.5 提示超過 10 萬 token 價格變 5 倍） |
| `AI_WEB_SEARCH`、`AI_WEB_SEARCH_MAX_USES` | `true`、3 | 每輪最多 3 次搜尋 |
| `AI_WEB_SEARCH_ALLOWED_DOMAINS` | 空（**不限網域**，產品負責人決定） | 逗號分隔；`recommended`＝內建的台灣財經媒體＋官方網域清單，`official`＝只有官方。預設由模型自己判斷何時搜尋、用哪些來源（只限財經資訊，見「範圍」） |
| `AI_WEB_FETCH`、`AI_WEB_FETCH_ALLOWED_DOMAINS` | `true`、（空，不限） | 產品負責人 2026-11-12 決定開放：由 AI 自行判斷要讀哪些網頁；設 `official` 可改回只讀官方網域（證交所、櫃買、集保、期交所、金管會、央行、主計總處…） |
| `AI_WEB_DYNAMIC_FILTERING` | `false` | `true` 時用網頁工具的動態過濾（code execution）；預設直接呼叫，延遲較低、可零資料保留 |
| `AI_EAGER_TOOL_STREAMING` | `false` | 工具參數很短（幾十個 token），伺服器端驗證比提早串流划算；要時可打開 |
| `AI_WHY_ENABLED`、`AI_WHY_BLOCKING` | `true`、`false` | 見下方「為什麼漲跌」（預設開啟，產品負責人決定） |
| `AI_ANALYST_ENABLED`、`AI_ANALYST_SEARCH_MAX_USES` | `true`、3 | 見下方「法人觀點」；關閉時 POST 回 `unavailable`（不呼叫模型、不計費） |
| `AI_SCOPE_PRECHECK` | `true` | 明顯離題（寫程式、作業、角色扮演、寫詩、翻譯）又沒有任何財經字詞的提問，不呼叫模型直接婉拒 |
| `AI_RETENTION_DAYS` | 30 | 對話、訊息、草稿在最後活動後保存幾天；0＝永久保存 |
| `AI_ADMIN_EMAILS` | 空 | `FORLIOSA_ENV=prod` 時可以看 `GET /ai/admin/keys` 的帳號（逗號分隔）；dev／test 時所有登入者都可看 |

### 實作上的決定

- **SDK**：`anthropic` 2.8（送 API 版本 `2026-10-21`：不能帶 `temperature`／`top_p`／`top_k`；金鑰以 `Authorization: Bearer` 送出）。
  每把金鑰一個重複使用的 client，SDK 自己的重試關掉（`max_retries=0`），重試與換槽由 `keypool` 負責。
- **金鑰槽（三把金鑰在三個 workspace，各有額度）**：
  - **黏著**：每段對話在第一次成功的呼叫時釘在一個槽（`ai_threads.key_slot`，只存槽號，從不存金鑰）；之後每一輪、每一次呼叫都走同一槽，
    所以提示快取（以 workspace 為單位）、thinking 區塊（只在產生它的帳號有效）與網路搜尋的 `encrypted_content`（必須原封不動送回同一個帳號）都有效。
  - **選槽**：新對話與背景工作（為什麼漲跌、之後的批次）選「餘裕」最多的槽：最近一次回應的 `anthropic-ratelimit-{requests,tokens,input-tokens,output-tokens}-{remaining,limit,reset}`
    標頭（名稱已對照 platform.claude.com 的 rate-limits 文件）算出 remaining÷limit 的最小值，再與 `1 − 本月估計花費 ÷ 預算` 取小，
    以 0.1 為一級比較；同級時選本月花費最少的槽，再來是這個程序分配較少的槽、槽號小的。`anthropic-workspace-id` 標頭也記下來（只顯示在管理狀態）。
  - **跳過的槽**：401／403 → 停用到重啟；429／529／5xx／`overloaded_error` → 冷卻（有 `retry-after` 照它，否則 `AI_KEY_COOLDOWN_SECONDS`）；
    速率標頭 remaining 為 0 → 冷卻到 reset；429 且 `error.details.error_code = enforced_spend_limit_reached`（組織花費上限）→ 到下個月 1 日 00:00 UTC；
    400「You have reached your specified (workspace) API usage limits」（Console 設的花費上限）→ 到訊息寫的時間（讀不到就下個月）；
    402 `billing_error` → 一小時後再試；本月估計花費 ≥ `AI_KEY_<n>_MONTHLY_BUDGET_USD` → 本月不用。
  - **對話中途換槽**：釘住的槽停用、用完額度或冷卻超過 `AI_KEY_STICKY_WAIT_SECONDS`（5 秒內恢復就等）時，這一輪**在第一次模型呼叫之前／失敗時**
    換到餘裕最多的槽，並改用**純文字摘要**接續：每一輪成功的對話變成一則 user（提問）＋一則 assistant（回答文字，引用改成「・標題：網址」純連結），
    丟掉 thinking、工具呼叫與結果、伺服器工具區塊與加密內容（依 skill 的說明：thinking 區塊在別的帳號會被丟掉、加密的搜尋內容只能原樣送回同一帳號）；
    這一輪的頁面情境多一行「先前的對話只保留文字…需要數字請重新查詢」。在新槽第一次成功後，摘要存成隱藏的 `ai_messages`（`meta.recap`），
    `ai_threads.context_from_seq` 指向它、`key_slot` 改成新槽；之後的回合原樣重播「摘要＋新回合」（只追加，新槽的快取有效）。
    已經查過工具的一輪不會中途換槽（工具結果與 thinking 屬於原槽）：在原槽重試一次，再失敗就 `error: ai_busy`，下一輪再換。
    0005 之前建立的對話（`key_slot` 是 null）第一次被使用時也用摘要接續。
  - 所有槽都停用／用完額度時 `POST /ai/chat` 回 503 `ai_unavailable`，`/ai/usage` 的 `available` 為 false；都在冷卻時送 `error: ai_busy`。
  - 槽的冷卻、速率標頭與停用狀態存在各程序的記憶體（api 與 worker 各自一份）；每月花費從 `ai_usage.key_slot` 加總，所有程序共用。
  - **`GET /ai/admin/keys`**（dev／test 或 `AI_ADMIN_EMAILS`；其他人 404）：每槽的 `configured`、`state`（`ok`、`cooling`、`disabled`、
    `exhausted`、`over_budget`、`not_configured`）、`retry_in_seconds`、`workspace_id`、本月花費與次數、預算與剩餘、`headroom`、最近的速率標頭、
    釘在該槽的對話數、最後一個錯誤（狀態碼＋類型，不含訊息內容），以及目前會送出的伺服器工具與被停用的工具。從不包含金鑰。
- **被拒絕的伺服器工具**：API 回 400 且訊息寫出某個伺服器工具的 `type`（例如「Requests sent from a sandbox with restricted network access are not
  allowed to use tool web_fetch_20260318」；或寫出名稱，例如「web search is not enabled」）並說它不被允許／不支援／未啟用時，把那個工具拿掉重送
  一次，並在這個程序裡記住（只記一次 warning；理由列在 `/ai/admin/keys.excluded_tools`）。為什麼漲跌沒有可用的 `web_search` 時不呼叫模型。
  工具清單改變會讓舊對話裡的 thinking 區塊失效：若 API 因此回 400（「Invalid `signature` in `thinking` block … bound to a different
  conversation」），同一槽改用純文字摘要接續一次（同上）。
- **手寫工具迴圈**（不用 SDK beta tool runner）：每一輪都要把文字、引用、伺服器工具進度與草稿即時轉成 SSE，失敗時在送出任何位元組前
  換槽，並把 API 回傳的內容區塊原封不動存起來。依 skill 的規則：附上完整 `response.content`；每個 `tool_use` 都在同一則 user 訊息
  回 `tool_result`（失敗用 `is_error`）；`pause_turn` 直接重送不加訊息（為什麼漲跌的續傳也留在同一槽）；`refusal` 與 `max_tokens` 的那一輪不執行工具。
  **串流已經送出文字後**才失敗的請求不重試（`error: ai_busy`），避免重複的文字。
- **對話只追加、不改寫**（Haiku 5.5 的 thinking 區塊綁定之前的所有內容，改到前文會 400；也讓提示快取有效）：系統提示固定不變（不含日期、
  頁面、使用者）；每輪變動的「頁面情境」（台北時間、市場狀態、頁面與代號、隱私模式）是接在使用者訊息後的 `role: "system"` 訊息
  （模型不支援時自動改成 user 訊息裡的 `<system-reminder>`）。thinking 簽章、`web_search_tool_result.encrypted_content`、
  `citations[].encrypted_index` 原樣存回。失敗或被拒答的一輪保留在紀錄裡顯示，但標成 `in_context = false`，之後不再送給模型。
  每段對話的模型在開始時固定（`ai_threads.model`），換 `AI_MODEL` 只影響新對話。
- **提示快取**：系統提示最後一個區塊放一個 `cache_control`（工具在它前面，一起快取），再加最上層的自動快取給對話尾端。工具依名稱排序。
- **範圍（產品負責人決定）**：只協助投資理財、台美股、使用者自己的持股與 Forliosa 的用法。系統提示要求其他要求（寫程式、一般常識、作業、
  翻譯、寫作、角色扮演、閒聊）用一句繁體中文婉拒並帶回投資，且「規則適用整段對話」（使用者堅持或說有人同意例外也一樣）。
  `ai/scope.py` 另有保守的預先檢查：只有同時符合離題樣式（程式、作業、角色扮演、寫詩、翻譯）**且**完全沒有財經字詞（股、價、投資、ETF、
  台積、四到六位數代號…，刻意放寬）時才不呼叫模型，直接回固定的一句話（`done.stop_reason: "off_topic"`；算一則提問；不進模型上下文）。
  一般常識等其他離題問題交給模型判斷。
- **網路搜尋**：預設不限網域；系統提示請模型自己判斷何時搜尋、用哪些來源，但只搜尋與問題相關的財經資訊，優先第一手來源與信譽良好的財經媒體、
  避開論壇與內容農場；並依 skill 對 Haiku 5.5 的建議提醒今天的日期在頁面情境裡、會變動的資訊要先搜尋。`max_uses` 維持 3（為什麼漲跌也是 3）。
- **有根據才寫（grounding）**：系統提示要求每個事實都來自工具結果或有引用的網路來源；找不到來源就不寫或標「未經查證」，不把沒有引用的新聞事件
  寫成事實，寧可少寫幾點。伺服器端另有檢查（`ai/grounding.py`）：一輪用到 `web_search`／`web_fetch` 時，把回答切成句子，與「有引用的文字區塊」
  都不重疊、又像新聞敘述（強動詞：宣布、批准、核准、決議、收購、簽署、入股…；或弱動詞：通過、發布、投資、降息…加上日期或主體：董事會、公司、央行、
  英文名稱、「」）的句子列在 `grounding` 事件，也存在該則回答（`ThreadMessage.grounding`），讓前端標「無來源」。工具給的數字本來就沒有引用，
  所以單純的價格、持股句子不會被標。位置是 Unicode code point（中文都在 BMP，與 JS 字串索引相同；保險起見也附上句子本身）。
- **免責聲明由畫面顯示（產品負責人決定）**：系統提示不再要求模型寫「僅供參考，非投資建議」，反而要求不要寫；固定文字
  「AI 回答僅供參考，非投資建議。」放在 `done.disclaimer` 與 `GET /ai/usage` 的 `disclaimer`。提到價格、報酬時模型仍會順帶寫資料時間。
- **工具**：16 個 client tools（2026-11-12 加 `get_derivatives_overview`，見「第三批」；2026-11-13 加 `get_technicals`，見「AI 技術分析與盤中價格」），全部 `strict: true`、
  `additionalProperties: false`、沒有使用者 id 欄位（伺服器帶入登入者）；可選參數合計 18 個（上限 24）。結果是精簡 JSON（例如 K 線只給統計與最多 30 個取樣點、籌碼只給最近 10 日與區間合計），保留 `as_of`、`is_demo`、`sources`。
  其他使用者的帳戶 id 會回錯誤，不會被當成篩選條件。伺服器工具：`web_search_20260318`（`user_location` 台北／TW、`max_uses` 3、預設不限網域）、
  `web_fetch_20260318`（預設不限網域但 `blocked_domains` 封鎖 `www.twse.com.tw`、`mis.twse.com.tw`，`max_uses` 2、`max_content_tokens` 8000、開啟引用；
  設了 `AI_WEB_FETCH_ALLOWED_DOMAINS` 時改用 `allowed_domains`，並拿掉這兩個主機、`twse.com.tw` 換成 `openapi.twse.com.tw`，因為 API 只接受兩者之一）。
  系統提示：上市股票沒有逐檔法人資料，問外資動向時用 `web_search` 找新聞、每一點附來源與日期、不寫搜尋結果沒有的張數。
- **草稿**：`draft_transaction` 跑和 `POST /transactions/preview` 相同的稅費計算，再用帳本嚴格重播檢查（例如賣超過持股 → 工具錯誤，
  不產生草稿），通過才存 `ai_drafts`（`pending`）並送 `draft` 事件。**不會寫入 `transactions`**。沒給價格時用最近收盤價估算並寫在 `notes`；
  有多個帳戶又沒指定時回帳戶清單讓 AI 追問；賣出時若只有一個帳戶持有該股就用那個帳戶。簽名後請前端 `PATCH /ai/drafts/{id}`
  （`signed` ＋ `transaction_id`），只接受自己的交易。
- **拒答**：Haiku 5.5 沒有伺服器端備援模型；`stop_reason: "refusal"` 時送 `error: refusal`（請使用者換個問法），該輪不留在上下文。
- **額度**：每天提問數＝當天的使用者訊息數；每月 token＝`input + 快取寫入 + output + ceil(快取讀取 ÷ 10)`（快取讀取約十分之一價）。
  「為什麼漲跌」的共用快取不算在觸發者頭上。`ai_usage` 每次模型呼叫一列：token、搜尋次數、金鑰槽、估計費用（`ai/pricing.py`，
  Haiku 5.5 US$0.10／0.50 每百萬 token，提示超過 10 萬 token 為 0.50／2.50；快取讀 0.1 倍、寫 1.25 倍；搜尋 US$10／千次），**不含訊息內容**。
- **保存期限 30 天（產品負責人決定）**：worker 每天 04:20（台北）執行，也可手動
  `uv run python -m forliosa.ai.retention [--days N] [--dry-run]`。刪除最後活動（`updated_at`）超過 `AI_RETENTION_DAYS` 天的 `ai_threads`
  與它全部的 `ai_messages`（含加密的搜尋內容、摘要、顯示用文字），以及 `updated_at` 超過期限的 `ai_drafts`（已簽名、已捨棄，和從沒簽名而過期的
  待確認草稿；已簽名草稿建立的交易仍在帳本）。舊對話裡較新的草稿保留（`thread_id` 改成 null）。`ai_usage` 保留做帳（沒有內容），`ai_why_cache` 是共用資料也保留。
- **為什麼漲跌**（預設開啟）：只在規則判斷 `show: true` 時才問模型（`web_search`、一句話、45 字內、必須有引用，否則
  `NONE`）。結果依「代號＋交易日」存 `ai_why_cache`，所有使用者共用；失敗 30 分鐘後才重試，找不到原因（`empty`）當天不再問。
  預設在背景執行緒產生（第一次回規則句，之後回 AI 句）；`AI_WHY_BLOCKING=1` 則同步等待。任何錯誤都回規則句。用餘裕最多的金鑰槽。
- **建議問題** `GET /ai/suggestions`：規則與前端離線版相同（`apps/web/src/ai/suggestions.ts`），不呼叫模型。上市個股多一題 `foreign_flow`「最近外資對這檔的動向？」（排在 `why_move` 之後，最多 3 題）。
- **Live smoke**：`uv run python -m forliosa.ai.smoke`（需要金鑰；沒有示範使用者會先 seed）：一題用工具的持股問題、一題需要網路搜尋的
  台積電問題，印出用量、估計費用、「無來源」標記與每個金鑰槽的狀態。`--analyst 2330.TW NVDA`（最多 2 檔）只跑法人觀點的生成
  （不寫資料庫），印出搜尋關鍵字、每個搜尋結果的 `page_age`、thinking 摘要、模型回報的原始內容、留下與刪掉的項目（附原因）、秒數與費用。

### 法人觀點（`GET/POST /instruments/{symbol}/analyst-views`，`ai/analyst.py`，2026-11-12）

規則來自 `PRODUCT.md` 與 `docs/research/analyst-ratings.md`：只引用第三方已公開的評等與目標價、每筆附來源與日期；AI 自己不給目標價；
不算平均、上漲空間，不排名，不寫買賣提示；標示為第三方觀點。

- **獨立的提示**（`prompts.ANALYST_SYSTEM`）：只允許「引用」報導裡寫明的機構評等與目標價。聊天提示的「也不給目標價」**沒有改**。
  模型唯一的輸出是 strict client tool `report_analyst_views`（網址、機構、動作、評等原文、目標價、幣別、報導日期；最多 8 筆候選），
  所以回應裡沒有任何模型自己寫的句子；畫面只顯示經過核對的欄位與固定的免責文字。**七個欄位都是必填、網址在最前面**，
  沒有的值填 `null`：strict 工具的輸入照 schema 的欄位順序產生，先前評等、目標價是選填時，模型跳過後想補在最後，
  只能寫進還沒關上的 `url` 字串（live 實測：`"url": "https://…','target_price':3800,"`），整批候選因此失效。
- **工具**：只有 `web_search`（`max_uses` 3、台北位置，評等彙整站 TipRanks、MarketBeat、StockAnalysis、TradingView、Goodinfo、
  玩股網、CMoney、Benzinga、Zacks、WallStreetZen、Fintel、Public、MarketScreener、Simply Wall St、Alpha Spread、
  ValueInvesting.io、TickerNerd、ChartMill 用 `blocked_domains` 擋掉；有設 `AI_WEB_SEARCH_ALLOWED_DOMAINS` 時改用那份允許清單，API 只能二選一）。**不用 `web_fetch`**，
  所以不會讀取 www.twse.com.tw／mis.twse.com.tw。API 拒絕某個伺服器工具時和對話一樣把它停用（這個程序內），該次回 `unavailable`。
- **核對（grounding，`analyst.verify`）**：一筆只有在下列都成立時才列出——
  1. 網址是這次生成中模型實際拿到的 `web_search_result` 之一（比對時忽略 http/https、`www.`、結尾斜線、`#…`、百分比編碼）；
     顯示的網址與標題用**搜尋結果自己的**，不用模型寫的。
  2. 是報導，不是評等彙整站、報價頁或評等／預測頁（`analyst.is_article`）：上面的網域；報價頁（Yahoo 股市／Yahoo Finance 的
     `/quote`、鉅亨 `/twstock`、`/usstock` 與整個 invest.cnyes.com、CNN Money `/quote`、WSJ `/market-data`、MarketWatch
     `/investing/`、Nasdaq `/market-activity/`、Investing.com `/equities/`，子網域一起比對）；網址沒有報導日期、路徑又有
     `/quote`、`/analyst-ratings`、`/analyst-research`、`/analyst-insights`、`/analystestimates`、`/estimates`、
     `/research-ratings`、`/forecast`、`/price-target`、`/consensus` 這類段落（或結尾是 `-consensus-estimates`、`-stock-forecast`、
     `-price-target`…）的頁面。這些頁面會持續更新，`page_age` 是更新時間，不是券商發表評等的日期。
  3. 報導日期能從該搜尋結果的網址（`/2026/11/10/`、`2026-11-10`、`20261110…`；有分隔符號時日之後不能緊接數字，
     `/2026/09/284512/` 是編號不是 9/28）或 `page_age`（ISO、`November 10, 2026`、`2026年11月10日`、`3 days ago`）讀出，網址日期優先；
     **顯示的日期是這個核對過的報導日期**，不是模型寫的日期。不晚於明天、不早於 90 天前。
  4. 有具名機構，評等原文（30 字內）或目標價（正數）至少一項。泛稱不列（`analyst.institution_key`）：「法人」「外資」「分析師」
     「Analysts」，以及「…系外資／…系券商」（美系外資、歐系券商）、「某外資」、「外資券商」「國內投顧」、「美系外資 C」這類代號、
     「Wall Street analysts」。目標價的幣別必須是這檔股票的交易幣別（例如台積電 ADR 的美元目標價不會列在 2330.TW）；另外有一個
     **只在內部使用、不顯示也不參與任何計算**的合理性過濾：有最近的真實股價（不用示範報價）時，目標價不在股價的 0.4–3 倍之間
     就當成其他幣別刪掉（模型把 ADR 的美元目標價標成 TWD 時，比值約 0.16 × 倍數；沒有真實股價就不檢查，例如目前的美股）。
  核對後依報導日期新到舊、同一家機構只留最新一筆（比對時把常見別名視為同一家：大摩／摩根士丹利／Morgan Stanley、小摩／摩根大通／
  J.P. Morgan、美銀／美林／BofA、高盛、花旗、瑞銀、野村、麥格理、匯豐、德銀、巴克萊、傑富瑞、伯恩斯坦、瑞穗、大和、里昂；
  「證券」「投顧」「analysts」等字尾與括號裡的另一種寫法不影響比對；**顯示時照報導原文**），最多 5 筆。數字照報導原文傳遞，不換算、不平均、不比較。
- **不宣稱「查無」**：`ready` 且清單是空的＝近期查無報導。核對後一筆都沒留下時，下列情況改成 `unavailable`（10 分鐘後可重查），
  不存成全體共用一整天的「查無」：搜尋結果裡有**這檔股票**的評等標題（標題同時有評等字詞——目標價、評等、評級、price target、
  upgrades／downgraded、overweight…，信評不算——和這檔的名稱、代號、ticker 或別名，例如台積電／2330／TSMC、NVIDIA／NVDA／輝達；
  彙整站與評等頁不算；網址或 `page_age` 能看出超過 90 天的不算），或有候選因為網址不在搜尋結果裡、或搜尋結果沒有可讀的日期而被刪掉。
  別檔股票的評等新聞（例如查富邦金時搜到「國泰金獲外資調升目標價」）不影響「查無」。
  `report_analyst_views` 的清單或每一筆若被送成 JSON 字串，也會用 `json.loads` 解開（不用字串比對）。
- **共用與刪除**：`ai_analyst_views` 以「代號＋台股交易日」（台北今天；非交易日用最近一個交易日）為鍵，全體使用者共用；
  `expires_at` = 建立後 24 小時，每次讀取先刪掉過期的列，worker 每小時 :05 也刪一次（`ai_analyst_purge`）。只存一份核對過的項目，
  不累積歷史、不做統計。
- **狀態**：POST 建立 `pending` 列（主鍵衝突＝別人剛建立，直接共用）後在背景執行緒生成，回應立刻回 `pending`；完成後 `ready`
  （`as_of` 是完成時間）或 `unavailable`。`pending` 超過 5 分鐘（程序中斷）讀取時改成 `unavailable`。`unavailable` 的 `notes` 寫
  「HH:MM 之後可以再查一次。」；10 分鐘內 POST 直接回它（不重查、不計費），之後 GET 回 `none`、POST 重新生成。
  模型只回文字時補一次提醒（同一金鑰槽，搜尋結果原樣送回）；`pause_turn` 續傳也留在同一槽；拒答、`max_tokens`、仍沒有回報 → `unavailable`。
- **計費**：觸發的人算一題（開始時寫一列 0 token 的 `ai_usage`，`feature = "analyst"`、`thread_id` = 這次生成的 id，`stop_reason = "started"`；
  `messages_today` = 對話提問數＋今天觸發的生成數），之後每次模型呼叫一列，token 計入他的每月額度。讀共用結果的人不計。
  POST 先檢查金鑰（503 `ai_unavailable`）與額度（429），已有的 `pending`／`ready` 不檢查也不計。
- **只有個股**：ETF（`type != "stock"`）回 422 `analyst_views_stocks_only`，不呼叫模型；前端本來就只對個股顯示。
- **模型與時間**：`AI_MODEL_ANALYST`（預設 `AI_MODEL`，Haiku 5.5）、`AI_EFFORT_ANALYST=medium`、非串流、`max_tokens` 12000（實測輸出最多 4,608，含 thinking 與 8 筆候選）。

### 實測費用（產品負責人 2026-11-12 live smoke，`claude-haiku-5-5`）

| 題目 | 輸入 | 快取寫入 | 快取讀取 | 輸出 | 估計費用 |
|---|---:|---:|---:|---:|---:|
| 1. 我目前有哪些持股？（工具） | 4 | 9,511 | 7,837 | 878 | 約 US$0.00171 |
| 2. 台積電今天的新聞（1 次網路搜尋） | 4 | 7,980 | 15,500 | 1,542 | 約 US$0.01192（其中約 US$0.01 是搜尋費） |

法人觀點（2026-11-12，`smoke --analyst`，4 次 live 生成）：

| 次 | 股票 | 設定 | 搜尋 | 呼叫 | 秒數 | 輸入 | 輸出 | 估計費用 | 結果 |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | 2330.TW | effort low、第一版提示 | 2 | 1 | 12.7 | 22,305 | 1,298 | US$0.02288 | `ready`、0 筆：模型回報空清單 |
| 2 | 2330.TW | effort medium、改過的提示、擋彙整站 | 2 | 1 | 17.3 | 25,115 | 2,875 | US$0.02395 | `ready`、0 筆：thinking 列出伯恩斯坦、小摩、Aletheia 等候選，回報卻是空的 |
| 3 | 2330.TW | 同上＋印出原始回報 | 2 | 1 | 20.4 | 27,819 | 2,438 | US$0.02400 | `unavailable`：原始回報只有 1 筆，`url` 字串裡夾著 `','target_price':3800,` |
| 3 | NVDA | 同上 | 2 | 1 | 15.8 | 25,163 | 2,453 | US$0.02374 | `unavailable`：同樣的問題（`…200042618.html','rating_text':`） |
| 4 | 2330.TW | **工具欄位全部必填、`url` 在前** | 3 | 1 | 31.5 | 34,069 | 4,608 | US$0.03571 | `ready`、5 筆：伯恩斯坦 3,828、Aletheia 5,000、花旗 4,000、瑞銀 3,650、高盛 3,300（8 筆候選全數通過核對，取最新 5 筆） |
| 4 | NVDA | 同上 | 2 | 1 | 22.0 | 25,748 | 4,263 | US$0.02471 | `ready`、5 筆：Oppenheimer、Bernstein、Baird、Citi、Wells Fargo（Yahoo Finance、Finbold 報導；8 筆候選全數通過核對；美股沒有真實股價，目標價合理性過濾沒有作用） |

**根因**（第 3 次的原始回報）：strict 工具的輸入照 schema 的欄位順序產生。評等與目標價原本是選填、排在中間，模型先寫完必填欄位
（機構、動作、幣別、日期、網址），想在最後補目標價時已經不能再開新欄位，就把 `','target_price':3800,` 寫進還沒關上的 `url` 字串，
後面的候選也跟著丟失；第 1、2 次的「空清單」很可能是同一個問題的另一種結果（當時沒有印出原始回報）。改成七個欄位全部必填（沒有的值填 `null`）、`url` 在最前面之後，
第 4 次兩檔都正常。核對看得到的部分都和搜尋結果的標題一致（伯恩斯坦 3828 元、Aletheia 5000 元）。搜尋結果裡另有大量彙整站／評等頁
（MarketScreener、Simply Wall St、Investing.com consensus、Morningstar quote…），已加進封鎖或評等頁規則。
重跑：`uv run python -m forliosa.ai.smoke --analyst 2330.TW NVDA`（約 US$0.06、55 秒）。

提示快取有效（第二次呼叫起大部分是快取讀取）。同一次 smoke 發現兩件事，已處理：預設設定下兩題都在送出前被 400 拒絕
（「…not allowed to use tool web_fetch_20260318」）→ 上面的「被拒絕的伺服器工具」；搜尋題的回答出現沒有引用的「董事會批准投資 Anthropic／OpenAI」
→ 上面的「有根據才寫」。

### AI 待產品負責人確認

1. ~~額度數字~~：已確認（2026-11-12）每天 50 題、每月 300 萬計費 token。
2. ~~網路搜尋來源~~：已決定不限網域、由模型判斷（只限財經資訊）。`web_fetch` 預設也不限網域，但封鎖證交所網站與 MIS（2026-11-12，見上方「工具」）。
3. ~~為什麼漲跌 AI 句~~：已決定預設開啟。
4. ~~對話保存期限~~：已決定 30 天。待確認：要不要在設定頁讓使用者自己刪除全部 AI 對話（目前只能一段一段刪）？
5. ~~免責聲明~~：已決定由前端固定顯示（`done.disclaimer`／`/ai/usage.disclaimer`），前端需要改為顯示這行字。
6. **金鑰槽的 workspace 驗證**：目前假設三把金鑰各在不同 workspace（換槽一律用摘要）。`/ai/admin/keys` 會顯示每槽回報的 `workspace_id`，
   請確認三個值不同；若某兩把其實在同一個 workspace，之後可以讓它們之間換槽時不用摘要（目前沒做）。
7. **每槽預算是估計值**：依 `ai/pricing.py` 的價目估算，與實際帳單可能有出入；建議 Console 的 workspace 花費上限設為真正的硬上限，
   `AI_KEY_<n>_MONTHLY_BUDGET_USD` 設低一點作為提早換槽的門檻。
8. **「無來源」標記是啟發式**：可能漏標（沒有典型動詞的敘述）或誤標（用工具資料寫的公告句子）；需要看實際對話調整字詞。
9. ~~法人觀點還沒在 live 看到項目~~：已找到根因並修正（見上方實測第 3、4 次），2330.TW 與 NVDA 各列出 5 筆核對過的項目。
   **待確認**：「美系外資」「外資券商」這類沒有寫出機構名稱的說法目前**不列**（台灣媒體很常這樣寫，所以會少很多筆）。
   建議維持不列（使用者無法查證是哪一家，同一篇裡兩家匿名外資也會被誤認成同一家）；若要列，可改成顯示「未具名外資」且不參與去重。
10. **法人觀點的報導日期與 90 天**：顯示的是報導日期（搜尋結果核對），不是券商報告日期；超過 90 天的不列（研究稿建議 90 天）。
    台股常見「媒體報導晚券商報告幾天」，要不要改成標「舊資料」而不是不列？
11. **法人觀點算一題**：和對話共用每天 50 題；失敗後 10 分鐘可重查，重查再算一題。

## 2026-11-12 分享（M5）第一批：登入、授權唯讀查看、親友群組

依 [`docs/api-contract.md`](../../docs/api-contract.md)「分享（M5）」實作。群組 AI 週報、頻道與推播在下面的「第二批」；它們用的資料表在
同一個 migration `0010`（`group_digests`、`group_channels`、`notification_outbox`、`telegram_link_codes`），第二批沒有新的 migration。

### 新增的欄位與合約沒寫的細節

| 位置 | 實作 |
|---|---|
| `User` | 多 `avatar_url`（Discord 頭像，`https://cdn.discordapp.com/avatars/<id>/<hash>.png?size=128`，沒有頭像為 `null`） |
| `GET /auth/discord/start` | Discord 沒設定時同樣 302 到 `{FRONTEND_URL}/login?error=oauth_disabled`；`next` 超過 2048 字回 422 |
| `POST /delegations` | 對象不是同群組成員、或是自己：404（先判斷，再判斷已授權過的 409）。離開群組後既有授權照常有效，但不能再新增 |
| `PATCH /delegations/{id}` | 被授權者呼叫回 403 `forbidden`；不相干的人 404 |
| `Delegation.accounts` | `scope: "all"` 時列出授權者目前所有帳戶 |
| `DelegationCandidate.delegation_id` | 沒授權過為 `null` |
| `GroupSummary` | `GET /groups` 依我加入的順序；`latest_activity_at` = 目前**看得到的**動態（含成員加入）與看得到的對象上的留言中最新的時間（被關掉的分享不會讓它變動）；`latest_digest_at` = 最新 `ready` 週報的 `created_at` |
| `InviteOut` | 多 `created_at`；`GET /groups/{id}/invites` 的項目沒有 `url` 這個鍵 |
| `InvitePreview.inviter_display_name` | 建立邀請的人已離開群組時改顯示目前 owner 的名稱 |
| `POST /invites/{token}/accept`、`PUT /groups/{id}/share` | `share` 的六個開關**全部必填**（少一個 422）：前端必須讓本人確認每一項。成功回 200 |
| `LeaderboardEntry.rank` | 沒有名次時是 `null`（鍵存在）：排行關閉，或該成員這期沒有數字 |
| `FeedItem`（`member_joined`） | 只有 `id`、`type`、`user_id`、`display_name`、`avatar_url`、`created_at`（= 加入時間）；不能留言或按表情 |
| `FeedItem`（`trade`）`created_at` | 合併的交易裡最晚建立的那一筆的建立時間 |
| `Comment` | 多 `avatar_url`（已離開、已刪除的帳號為 `null`） |
| `PUT`／`DELETE /groups/{id}/reactions` | 回 200 `{"target", "reactions": [{"emoji", "count", "mine"}]}`（該對象目前的統計） |
| 錯誤 | 群組角色不足 403 `forbidden`；owner 想離開 409 `conflict`（先轉移）；改 owner 的角色、轉移給自己 422；轉移或變更的對象不是成員 404 |

### 登入（Discord OAuth）

- `state`：32 bytes 隨機值；cookie 內容是 `base64url(JSON{s, n, e}).base64url(HMAC)`，`n` 是驗證過的 `next`、`e` 是到期時間（10 分鐘），
  HMAC 金鑰由 `SESSION_SECRET` 以 HKDF 衍生（用途 `oauth-state`，和其他用途的金鑰互不通用）。callback 先驗簽章與到期，再以固定時間比對
  `state`；不論成敗都刪除 cookie。
- `next`「解碼一次」= 框架對 query string 的那一次解碼；之後不再解碼，所以 `next=%252F%252Fevil.com` 會因為不是 `/` 開頭而變成 `/`。
- Discord 的 access token 只用來讀一次 `/users/@me`，之後立刻呼叫 Discord 撤銷（失敗也不影響登入）；token、授權碼、client secret 都不寫進
  資料庫或 log。`user_identities` 只存 Discord id 與 Discord 回報的 email。
- 帳號對應照合約。已連結的帳號每次登入：`user_identities.email` 照 Discord 回報的更新；`users.email` 只在 Discord 說已驗證、而且沒有被別的
  帳號使用時才跟著換；頭像一律更新。新帳號的 `display_name` 取 global name，否則 username，截到 30 字。
- 同一個 Discord 帳號同時第一次登入兩次（唯一鍵衝突）→ 後到的那次 `oauth_failed`。
- `GET /auth/providers` 的 `discord` 是三個 `DISCORD_*` 環境變數都有值；`dev_login` 是 `FORLIOSA_ENV` 為 `dev`／`test`。
- 正式環境啟動檢查（不印出任何值）：`SESSION_SECRET`、`CORS_ORIGINS` 不可為 `*`（原有）；`FRONTEND_URL` 必填、必須是 `CORS_ORIGINS` 之一、
  兩者都是 https；三個 `DISCORD_*` 只設一部分 → 拒絕啟動；有設 Discord 時 `DISCORD_REDIRECT_URI` 必須是 https。開發環境沒設 `FRONTEND_URL`
  時，登入後的導向與邀請連結用 `CORS_ORIGINS` 的第一個。
- **Access log 去敏**：uvicorn 的 access log 會記錄完整網址，因此 `logredact.py` 把 `code`、`state` 參數與 `/invites/<token>` 換成 `***`
  （`create_app` 時安裝）。

### CSRF

非 `GET`／`HEAD`／`OPTIONS` 的請求帶 `Origin` 時必須完全等於 `CORS_ORIGINS` 其中一個（不分大小寫、結尾 `/` 忽略），`Origin: null` 也拒絕；
沒有 `Origin` 的請求（curl、伺服器之間）照常通過。**本機開發**：Vite 以 `/api` 代理轉發時瀏覽器仍會送 `Origin: http://localhost:<port>`，
用 5173 以外的埠連真的後端時要把那個 origin 加進 `CORS_ORIGINS`，否則所有寫入（含開發登入）都是 403。

### 唯讀查看（`X-Forliosa-View-As`）

- `api/middleware.py` 的路由白名單（預設拒絕）。合約第 1 類的 `GET` 以授權者身分執行；第 2 類忽略標頭（另外也忽略 `/health`、`/meta/*`）；
  其他一律拒絕：非 `GET` → `read_only`，其他 `GET`（包括 `/instruments/{symbol}/analyst-views`、`/recurring`、`/ai/*`、`/watchlist`、
  `/groups/*`、`/delegations*`、`/invites/*`）→ `view_as_not_allowed`。被拒絕的請求不查授權是否有效；白名單內的讀取才查，失效一律
  `delegation_revoked`。
- **範圍集中在一處**（`services/scope.py`）：解析授權後把「授權者 id＋允許的帳戶」存在這個請求的資料庫 session 上；`load_ledger_input`
  （摘要、持股、`allocation.by_account`、績效、出清、本週事項、部位、部位歷史、事件的 `mine`／`amount_estimate`）、`GET /accounts`、
  `GET /accounts/{id}/holdings`、`/transactions`、定期定額（`upcoming` 的扣款）都經過它，所以授權者就像只有那些帳戶。範圍外的 `account_id`、
  帳戶或交易 id → 404。`/transactions?account_id=` 只在查看模式下對範圍外帳戶回 404（自己查看時維持原本回空清單）。
- 查看模式下同一個 session 拒絕任何寫入（`before_flush` 直接丟 403 `read_only`），所以即使某個讀取路徑想寫（例如股利同步），也寫不進去。
- 成本法、基準用授權者的偏好（計算本來就以授權者身分）；顯示偏好由前端用查看者自己的 `GET /me`。

### 分享投影（`services/sharing.py`）

- 群組與授權讀別人的資料只經過這個模組：`enter_view_as`（授權）、`shared_portfolio`、`group_holdings`、`leaderboard`、`feed_items`、
  `target_visible`。每次請求重新讀成員身分與分享設定。
- 區塊內容：`returns` = `{day, month, year, total}`（`total` 與 `PortfolioSummary.total_return_pct` 同算法，含股利、依成員自己的成本法）；
  `holdings` = `{symbol, name, weight}`（依權重由大到小）；`amounts` = `{market_value, day_change, total_pnl}`（2 位小數）。三個都沒開時
  `SharedPortfolio` 只有 `user_id`、`display_name`、`avatar_url`（連 `is_demo` 都沒有）。
- `GroupHoldings.industries`：開了持股的成員中，持有該產業任何一檔的人數（1 人也列；`common` 才限 2 人以上）。
- 測試（`tests/api/test_m5_privacy.py`）跑過五個開關的 32 種組合：沒開的區塊鍵不存在；回應中沒有股數、成本、帳戶名稱或 id、備註、手續費、
  交易 id；金額只在開了 `amounts` 的 `amounts` 區塊、價格只在開了 `trades`＋`trade_prices` 的動態裡。

### 排行

- `date`（最新收盤）：交易日 13:30 以後是今天，否則前一個交易日；若 `^TAIEXTR` 與 0050 的資料都還沒到那一天，用兩者中最新的日期。
  `as_of` 是該日 13:30（台北）。
- 期間起點：`day` = 前一個交易日、`month` = 上月最後一個交易日、`year` = 去年最後一個交易日（台股行事曆）。`DATA_POLICY=commercial` 時起點
  早於存檔第一天就改成存檔第一天，`notes` 第一行說明「資料累積中：自 … 起存檔；期間從 … 收盤開始計算」。
- 成員報酬：所有帳戶合併，從今年的起點收盤開始逐日模擬（`domain.performance.simulate`，與績效頁同一套 TWR 公式），起點之前的交易都在起點
  當天入帳（起點當天的報酬不算）；期間內完全沒有投入的成員該期為 `null`。年度區間內任何一天有持股沒有收盤價 → 三個期間都是 `null`。
  每次請求重算（目前沒有快取）。
- 基準：`^TAIEXTR` 為指數收盤比；0050 為含息報酬（除息日再投入，同績效頁的基準算法）。沒有資料時 `return_pct` 為 `null`，commercial 下
  `notes` 說明「基準 … 目前沒有可商用的資料」。
- `sources` 只列「本系統帳本」與兩個基準的資料來源：**不列**成員持股的價格來源（否則來源清單會透露有人持有某類商品）。

### 交易動態

- 範圍：開了 `trades` 的成員、`manual`／`import`／`ai_draft` 的 `buy`／`sell`、`trade_date` 在「今天（台北）往前 90 天」到今天之間
  （未來日期不列）。「只記持股」帳戶在快照日當天或之前的交易不列（帳本也不算它們）。
- 合併鍵：成員×交易日×商品×買賣。`count` = 筆數；`price` = 以股數加權的平均成交價（4 位小數，不含費用）、`currency` = 交易幣別，只有開了
  `trade_prices` 才有這兩個鍵。
- `id`：`gfi_` + 以 `SESSION_SECRET` 衍生金鑰（用途 `feed-item-id`）對合併鍵做的 HMAC（26 字）。同一則在不同群組 id 相同，但留言與表情都
  依群組分開存。
- 分頁：依 (`trade_date`（加入動態用加入日）, `created_at`, `id`) 由新到舊；`cursor` 編碼最後一則的三個值。`user_id` 不是成員時回空清單
  （和「沒有資料」一樣）。
- **刪除**：一則動態的最後一筆交易被刪除、改到別的日期／商品／方向，或整個帳戶被刪除時，所有群組裡這則的留言與表情一起刪除。

### 留言與表情

- `target` 格式 `trade:<id>`、`digest:<id>`、`leaderboard:<YYYY-MM-DD>`；`digest` 必須是這個群組 `ready` 的週報；`leaderboard` 的日期必須在
  群組建立日（台北）到今天之間。看不到、不存在、別的群組的一律 404「找不到討論對象」。刪除留言也要求對象目前看得到。
- 作者已離開：`display_name`「已離開的成員」、`user_id`／`avatar_url` 為 `null`；作者帳號已刪除（`user_id` 被設為 null）：「已刪除的帳號」。
  已離開成員按過的表情仍然計數。
- `can_delete`：作者本人，或 owner／admin。

### 群組與邀請

- 邀請 token 32 bytes（256 bits），資料庫只存 SHA-256；網址 `{FRONTEND_URL}/invite/{token}`。接受時以條件式 UPDATE 計次，單次邀請同時被兩人
  接受只有一人成功（另一人 410）。上限在接受時檢查：群組已有 50 人、或本人已在 20 個群組 → 409 `limit_reached`。
- 管理員**移除**別人時撤回群組所有還有效的多次邀請；成員自己**離開**不會撤回。離開或被移除時分享設定刪除，重新加入時由邀請的 `share` 重新選，
  並產生新的 `member_joined`。
- `push_targets` 只列 `status = active` 的頻道；Telegram 的 `label` 用 `chat_title`。
- 刪除群組時一併刪除留言、表情、邀請、週報、頻道、推播 outbox、Telegram 綁定碼、成員與分享設定。

### 資料表（migration `0010`）

`users.avatar_url`、`user_identities`、`delegations`、`delegation_accounts`、`groups`、`group_members`、`group_share_settings`（含 `trades_enabled_at`、
`push_enabled_at`：開關**最近一次打開**的時間）、`group_invites`、`group_comments`、`group_reactions`、`group_digests`、`group_channels`、
`notification_outbox`、`telegram_link_codes`。

### 金鑰與加密（`crypto.py`）

- 由 `SESSION_SECRET` 以 HKDF-SHA256 衍生：`oauth-state`（state 簽章）、`feed-item-id`（動態 id）、`channel-webhook`（Discord webhook 網址的
  Fernet 加密，第二批使用）。
- **更換 `SESSION_SECRET` 的後果**：所有人登出；已存的 webhook 網址解不開（owner 要重新設定頻道）；動態 id 全部改變，舊的交易動態留言找不到
  對象（不再顯示）。
- 邀請 token、Telegram 綁定碼只存 SHA-256（不需要金鑰）。

## 2026-11-12 分享（M5）第二批：群組 AI 週報、推播頻道

依 [`docs/api-contract.md`](../../docs/api-contract.md)「分享（M5）」→「群組 AI 週報」「推播」實作（後端；前端另做）。

### 端點與合約沒寫的細節

| 位置 | 實作 |
|---|---|
| `GET /groups/{id}/digests` | `limit` 1–52（預設 8）；依 `week_start`、`id` 新到舊；`cursor` 編碼最後一份的兩個值。`pending`／`failed` 也列出（`summary` 為空字串、`comment_count` 0、`reactions` 空）。`ready` 的 `summary` 也可能是空字串：寫進摘要的成員有人離開或關掉當時分享的項目（`notes` 多一則「寫這份 AI 摘要時用到的分享內容已有變動…，摘要不再顯示。」） |
| `Digest` | 多 `notes`（例如 commercial 下「資料累積中：自 … 起存檔；本週從 … 收盤開始計算」）與 `is_demo` |
| `Digest.facts` | `returns` 依加入順序；`common_holdings` 要兩人以上；`industries` 是持有該產業任何一檔的人數（1 人也列，同 `GroupHoldings`）；`trades_count` 是那一週 `trade_date` 在週一到週五、可出現在動態裡的買賣筆數（每筆交易算一筆，不是合併後的則數） |
| `Channels` | 非 owner 的 `webhook_hint` 為 `null`；沒設定的頻道 `notify_*` 回 `true`（預設值） |
| `PUT /groups/{id}/channels/discord` | `notify_trades`、`notify_digest` 可省略（預設 `true`）。重新設定（換網址）會取消還沒送出的推播，`configured_at` 重設。webhook id 和原本的不同（或解除後再設定、舊網址解不開）→ 其他成員的 `push` 改成關閉（設定的 owner 不變）。網址格式正確才計次：同一人或同一群組 10 分鐘內第 6 次 → 429 `rate_limited`（不送出；計數在 API 程序的記憶體裡，重啟歸零）；circuit breaker 開著時也是 429 `rate_limited` |
| `PATCH /groups/{id}/channels/{kind}` | 回整個 `Channels`；`notify_trades` 由關到開時 `configured_at` 重設（關著那段時間的交易不補送） |
| `DELETE /groups/{id}/channels/{kind}` | 204；Telegram 一併刪除還沒用的連結碼。資料列留著、`status = "removed"`（網址、chat id、`chat_title` 清掉），`Channels` 顯示為沒設定、`PATCH` 404；之後再設定算新的目的地 |
| `POST /groups/{id}/channels/telegram/link` | 只有 owner（403 優先於 409）；沒設 bot → 409 `telegram_unavailable`。連結碼 12 字（`A–Z`、`2–9`，去掉 `0 O 1 I`；60 bits），只存 SHA-256，大小寫不拘；再產生一組會刪掉群組還沒用的舊碼 |
| `kind` 不是 `discord`／`telegram` | 422 `validation_error` |

### 推播（`services/notifications.py`、`services/pushers.py`、`services/channels.py`）

- **排入 outbox**（worker `group_push` 每分鐘）：有 `active` 且 `notify_trades` 的頻道的群組，找「目前同時開著 `trades` 與 `push`」的成員、
  可出現在動態裡的買賣（`manual`／`import`／`ai_draft`，只記持股帳戶快照日當天或之前的不算）、`trade_date` 在今天與前兩天（台北）、
  `created_at` 晚於 `max(頻道 configured_at, push_enabled_at, trades_enabled_at)`。每筆交易每個頻道一列（`dedupe_key =
  trade:<group>:<kind>:<transaction>`），`not_before = created_at + 15 分鐘`。
- **送出前再檢查一次**：交易還在（刪除時 outbox 列跟著刪）、成員還在群組而且兩個開關還開著、交易建立時間仍晚於上面那個時間（關掉再打開
  會把時間往後移，期間的交易就不送）、交易日還在三天內、頻道還是 `active`。不符合 → `cancelled`。
- **合併**：同一輪到期、屬於同一則動態（成員×日期×商品×方向）的列送成一則訊息（`共 N 筆`）；之後才到期的同一則動態的交易另送一則。
  價格是這幾筆的股數加權平均（不含費用、4 位小數），只有開了 `trade_prices` 才附。
- **訊息內容**（純文字）：`小明 買進 台積電（2330）`／`11/12・共 2 筆・成交均價 605.00 TWD`／`— Forliosa 群組「家族投資」 <FRONTEND_URL>/groups`。
  不含群組 id、股數、金額、帳戶、備註。沒有設定 `FRONTEND_URL`（正式環境）時不附連結。Telegram 訊息裡使用者取的名稱把 `@` 換成全形 `＠`
  （純文字的 @名稱 在 Telegram 會提及別人）；Discord 一律帶 `allowed_mentions: {"parse": []}` 與 `flags: 4`（`SUPPRESS_EMBEDS`）。
- **名稱進訊息前**（`pushers.user_text`；顯示名稱、群組名稱、商品名稱、AI 摘要、連結成功的回覆與 Discord 測試訊息裡的群組名稱）：先變成一行
  （`textsafe.one_line`：換行、Tab 等控制字元換成空白，雙向文字控制、零寬空白等看不見的格式字元刪掉，U+200D 保留給組合 emoji）；Discord
  再以反斜線跳脫 `` \ * _ ~ ` | [ ] ( ) < : ``（`:` 讓 `https\://…` 不變成連結），值開頭的 `# > - +` 與 `1.`／`1)` 也跳脫（標題、引用、清單）；
  我們自己格式化的數字（報酬率、價格、筆數）不跳脫。輸入端：`PATCH /me`、開發登入的 `display_name`、`POST`／`PATCH /groups` 的 `name`
  有這些字元就 422；Discord 的 global name 自動清掉。舊資料（檢查前存的名稱）在送出時一樣變成一行並跳脫。
- **週報推播**：週報變成 `ready` 時排入（`dedupe_key = digest:<digest>:<kind>`）。內容只有「目前開著 `push`」的成員的數字
  （`sharing.digest_facts_view(..., pushing_only=True)`：報酬要 `returns`＋`push`、共同持股只算 `holdings`＋`push` 的成員、交易筆數只算
  `trades`＋`push`），加上兩個基準與群組頁連結。**AI 摘要**是用送給 AI 的那幾位成員的數字寫的（`facts.prompt_contributors`，見週報），
  所以只有在每一位都還在群組、還開著 `push` 與當時分享的那幾項時才附上（合約沒寫，選較保守的做法；app 內用同一套規則、不要求 `push`）。
  群組裡沒有人開 `push` 時不送。
- **Discord circuit breaker**（`pushers.discord_breaker`，每個程序各一個）：Discord 會暫時封鎖 10 分鐘內有 10,000 次無效請求（401／403／
  429）的 IP，而 Discord 登入也在同一台 API。webhook 請求在 10 分鐘內收到 500 次這類回應 → 10 分鐘內不再呼叫任何 webhook：
  `send_discord` 回 `paused`（可重試、`retry_after` = 剩下的秒數），設定 webhook 回 429 `rate_limited`，推播延到暫停結束後重試。
- **換目的地**：Discord 存的 webhook id 和新的不同（含舊網址解不開、解除後再設定）、Telegram 連到不同的 chat id（含解除後再連結）→
  `group_share_settings.push` 對設定者以外的成員全部改成 `false`（`push_enabled_at` 不動；本人重新打開時才更新，之後的交易才推播）。同一個
  webhook、同一個 chat 重新設定、超級群組遷移都不算。群組第一次設定某種頻道時不重設。
- **重試**：最多 5 次；失敗後等 1、2、4、8 分鐘（Discord／Telegram 給的 `retry_after` 較長時用它），第 5 次失敗為 `failed`。可重試：429、5xx、
  逾時、連線錯誤、Telegram 401（bot token 設錯是伺服器設定問題）。不重試：其他 4xx、3xx（不跟隨轉址）。
- **停用頻道**：Discord 401／404 → `webhook_invalid`；webhook 解不開（`SESSION_SECRET` 換過）→ `webhook_unreadable`；Telegram 403 →
  `bot_removed`、400「chat not found」→ `chat_not_found`；`my_chat_member` 顯示 bot 被移出（`left`／`kicked`）→ `bot_removed`。停用時
  這個頻道其他還沒送出的列改成 `cancelled`；`push_targets` 不再列出它。owner 重新設定就恢復。
- **Telegram 遷移**：送出時回 `parameters.migrate_to_chat_id`、或 `getUpdates` 收到含 `migrate_to_chat_id` 的訊息 → 頻道改用新的 chat id
  （送出時立刻用新 id 再送一次）。
- `last_error` 只存短標籤（`http_404`、`timeout`、`network`、`not_shared`、`channel_off` …），不存網址或對方回應的內容。

### Telegram 連結（worker `telegram_poll`，每 20 秒）

- `getUpdates`（`timeout=0`、`limit=100`、`allowed_updates=["message","my_chat_member"]`），沒有公開的 webhook 端點。`offset` 存在 worker
  記憶體：重啟後 Telegram 會重送還沒確認的更新；超過 10 分鐘的 `/link` 訊息不處理也不回覆（不會在重啟後洗版）。
- **防洗版**：任何人都能私訊 bot。每次輪詢一頁一頁讀到沒有積壓為止（最多 10 頁、8 秒；時間到就停，沒處理到的不確認、下次再讀）；`/link`
  以外的訊息不做任何事；失敗的 `/link`（私訊、無效或過期的碼）每個聊天室每分鐘最多回一次、每次輪詢最多回 10 則，成功的連結一定回覆。
  `telegram_poll` 在 worker 裡有自己的排程迴圈（`Job.background`）：慢的輪詢不會延後推播、週報與行情工作，其他工作跑很久（例如存檔）時
  也照常每 20 秒輪詢。
- `/link <碼>` 或 `/link@<bot> <碼>`（`@` 後面不是我們的 bot → 不理）；只接受 `group`／`supergroup`，私訊 bot 時回一句「請把我加進群組」、
  不消耗連結碼。連結碼必須還沒用、沒過期，而且產生它的人**現在仍是 owner**（10 分鐘內轉移了擁有者 → 無效）。成功時以條件式 UPDATE
  標記已使用（同一組碼只會成功一次），建立或改寫群組的 Telegram 頻道（`chat_title` 取群組標題），bot 回覆「已連結 Forliosa 群組「…」」；
  無效時回「連結碼無效或已過期」。群組改名（`new_chat_title`）時更新 `chat_title`。
- bot 建議保持 BotFather 的隱私模式（預設開）：群組裡只收到明確給它的指令，看不到其他聊天。這時沒加 `@bot` 的 `/link` 不一定收得到，
  所以**前端顯示的指令用 `/link@<bot_username> <code>`**。

### 群組 AI 週報（`services/digests.py`）

- **何時**：worker `group_digests` 週六 20:00（台北）建立上週一到週五的週報（`weekend_evening`：週六晚上沒跑到時週日任何時間補做，週一起
  不補）；`group_digest_poll` 每 5 分鐘送出還沒送的、收 Batches 結果、重試一般呼叫。同一群組同一週只有一份。
- **facts**（`sharing.digest_week_facts`）：只用每位成員**當時**在這個群組開放的項目：`returns` → 週報酬（和排行同一套 TWR，起點為週一前最後
  收盤、終點為那一週最後一個交易日收盤，commercial 下起點不早於存檔第一天）；`holdings` → 持有的代號清單（只存代號；名稱與產業另外存一份
  `symbols` 對照）；`trades` → 那一週的買賣筆數。以 `user_id` 存在 `group_digests.facts`（JSON，`v: 1`），讀取時再依**目前**的成員身分與
  開關過濾；當時沒開、之後才打開的人不會出現在舊週報。
- **給 AI 的內容**（`anonymous_prompt`）：週期、交易日數、匿名代號（成員 A、B…，每次隨機排序，不跟加入順序對應）＋週報酬、兩個基準、
  兩人以上共同持有的股票與人數、各產業持有人數、交易筆數。**不含**顯示名稱、user id、群組名稱、任何一個人的持股清單。重試（一般呼叫）時
  依當下的成員與開關重新組（離開或關掉的人不再送給 AI）。
- **摘要寫了誰**：每次組 prompt 都把用到的成員記在 `facts.prompt_contributors`（`{"returns": [user_id…], "holdings": […], "trades": […]}`，
  跟 batch 或回答一起存）。讀取時（`sharing.digest_summary_visible`）只要其中有人已不是成員、或關掉了他當時貢獻的那一項，`summary` 就回
  空字串並加一則 note；他重新打開時恢復。舊週報沒有這個欄位時，以 facts 裡每一列都算貢獻者（較嚴）。這樣摘要能顯示時，裡面每個數字都是
  看的人此刻本來就看得到的（`facts` 同樣依目前設定過濾）。審查另外建議只給 AI 彙總值（漲跌人數、中位數），**沒有採用**：有了上面的
  規則，摘要顯示時那些數字本來就看得到；而且兩人群組裡「中位數」加上自己的報酬就能算出對方的，彙總並不能防止反推。
- **系統提示**：只寫群組整體、不寫成員代號、不猜身分、不評論個人、不給買賣／加減碼建議、不提目標價、不預測、只用提供的數字、繁體中文 2–4 句、
  純文字。回答出現「成員 X」、「目標價」、「建議買／賣…」等字樣 → 不採用，`failed`（`error: rejected`）；`stop_reason` 不是正常結束或沒有
  文字 → `failed`。摘要最多 400 字。
- **呼叫**：一次 Message Batches（每份週報一個 request，`custom_id` = 週報 id）。batch 屬於建立它的 workspace，所以 `batch_id` 存
  `<槽號>:<batch id>`，之後只用那個槽查詢與讀結果（`KeyPool.call(only=槽)`）。建立 batch 時遇到 404／403／400／422（端點不能用）→ 改用
  一般 Messages 呼叫（這個錯誤不會讓金鑰槽被停用）；單筆 `errored`／`expired`／`canceled` → 那一份改用一般呼叫；一般呼叫遇到暫時性錯誤
  （429、5xx、連線、所有槽冷卻中）→ `batch_id = "direct"`，下一輪再試。建立 26 小時後還沒完成 → 以一般呼叫再試一次，仍失敗就 `failed`。
  沒有任何金鑰 → `failed`（`ai_unavailable`）；`AI_DIGEST_ENABLED=false` → `failed`（`ai_disabled`）。`failed` 的週報仍顯示 facts。
- **用量**：每次呼叫一列 `ai_usage`，`feature = "group_digest"`、`user_id = null`（不計入任何成員的每日／每月額度）、`thread_id` = 週報 id；
  Batches 結果的估計費用打五折。

### 環境變數（第二批新增）

| 變數 | 誰需要 | 說明 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN`、`TELEGRAM_BOT_USERNAME` | api＋worker | 兩個都有才 `telegram_available: true`；token 只放環境變數，不寫進 log（`logredact` 會把 `/bot<token>/` 換成 `***`） |
| `SESSION_SECRET` | api＋**worker**（同一個值） | worker 要用它解開 Discord webhook；`FORLIOSA_ENV=prod` 時 worker 沒設會拒絕啟動 |
| `FRONTEND_URL` | api＋worker | worker 用在推播訊息的群組頁連結；正式環境沒設時訊息不附連結 |
| `CLAUDE_API_KEY_<n>`／`ANTHROPIC_API_KEY` | worker | 群組週報 |
| `AI_DIGEST_ENABLED` | worker | 預設 `true`；`false` 時週報只有 facts（標 `failed`） |
| `AI_MODEL_DIGEST` | worker | 覆寫週報用的模型（預設同 `AI_MODEL`） |

### 背景工作與保存期限

| 工作 | 時間（台北） | 內容 |
|---|---|---|
| `group_push` | 每分鐘 | 排入交易推播、送出到期的列 |
| `telegram_poll` | 每 20 秒（有設 bot 才做事） | `getUpdates`（自己的排程迴圈：不擋其他工作，也不被其他工作擋住） |
| `group_digests` | 週六 20:00（週日補做） | 建立週報並送出 Batches |
| `group_digest_poll` | 每 5 分鐘 | 收結果、退回一般呼叫、排入週報推播 |
| `sharing_retention` | 每天 04:35 | 刪除：建立超過 30 天的 outbox 列（只用來避免三天內重送）、過期超過 1 天的 Telegram 連結碼、`week_start` 超過 26 週的週報（連同它的留言、表情與 outbox 列） |

### 秘密不進 log

- `logredact.install()`（api 與 worker 都會呼叫）除了 uvicorn，也掛在 `httpx`／`httpcore` logger 與 root logger 的每個 handler：Discord webhook
  路徑（`/api/webhooks/***`）、Telegram `/bot***/`、bot token 形狀的字串，連 traceback 都會遮掉（httpx 在 INFO 會記下每個請求網址）。
- `pushers` 不記網址、不記回應內容、不讓帶網址的例外往外丟（任何非 httpx 例外也只回 `error` 標籤）。webhook 網址驗證失敗的錯誤訊息不含網址。
- 測試：`tests/conftest.py` 的 `no_push_network` 讓所有 Discord／Telegram 請求失敗，測試用 `tests/api/push_fake.py` 的假伺服器；
  週報測試以假的 Messages／Batches 端點走真正的 SDK（`tests/api/test_m5_digest.py`）。

### 分享（M5）待產品負責人確認

1. **`FRONTEND_URL` 變成正式環境必填**：沒設定時 API 拒絕啟動。部署這一版之前要先在 Railway 的 api 服務設 `FRONTEND_URL=https://app.<網域>`。
2. **更換 `SESSION_SECRET`** 會讓交易動態的舊留言找不到對象（見上）。建議先維持一把金鑰；之後若需要定期換 session 金鑰，再另外加一個專給分享用的金鑰。
3. **群組建立者也有一則「加入」動態**（建立群組那一刻）。建議維持（實作最單純，也讓新群組的動態不是空的）。
4. **排行每次請求重算**：成員多（接近 50 人）時可能要幾秒。建議第二批加「每個交易日收盤後算一次」的快取。（第二批沒有做：
   先看實際群組大小再決定。）
5. **週報推播的 AI 摘要**：只有寫進摘要的每一位成員都開著「推播」時才附上，否則只送開了推播的人的數字與連結。建議維持（摘要是用沒開推播的人的
   數字寫的）；另一個選項是不論如何都附摘要（摘要只寫群組整體）。
6. **週報保存 26 週**（連同留言）。建議維持；要更久可改成 52 週。
7. **「交易日在 3 個日曆日內」解讀為今天與前兩天**（週五的交易週一才記，就不推播）。建議維持；若要寬一點可改成「今天往前 3 天」。
8. **worker 現在需要 `SESSION_SECRET`（與 api 相同）**，正式環境沒設會拒絕啟動；部署 worker 時一起設（見 `docs/deploy.md` 2.3）。
9. **換推播目的地時其他成員的「推播」自動關閉**（審查發現：成員看不出 Discord 推到哪個頻道，owner 換 webhook 後原本的同意會沿用）。已實作：
   換成另一個 webhook（即使在同一個 Discord 頻道）、連到另一個 Telegram 聊天室、解除後再設定，都要成員重新打開；群組第一次設定不影響。
   建議維持（保守、實作簡單）。另一個選項是設定時讀 webhook 的資料（名稱、頻道 id）顯示給成員，但只有 webhook 名稱可讀、而且由 owner 自己
   取名，不能真的分辨是哪個伺服器。前端要在成員的「推播」開關旁說明「群組換推播頻道時會自動關閉」；目前沒有另外通知成員。
10. **webhook 設定次數與 circuit breaker**：每人、每群組 10 分鐘 5 次；10 分鐘內 500 次無效回應就暫停 webhook 請求 10 分鐘。建議維持；
    計數在記憶體裡，API 開多個程序時每個程序各算各的（目前 Railway 只有一個）。

## 2026-11-13 討論串（公開／群組主題、回覆、表情、檢舉、站方管理）

實作合約「討論串、線圖留言（彈幕）與指數頁」裡**討論串**的部分。**線圖留言（`/chart-comments`）與指數頁（`^TAIEX`、`^TPEX`）這一版沒有做**
（產品負責人延後）：沒有相關資料表、端點或商品主檔項目；檢舉的 `target` 只有 `topic:<id>`、`reply:<id>`，管理端的檢舉項目沒有 `symbol`；
主題的 `symbols` 只接受目前商品主檔裡的代號（指數 → 422 `unknown_symbol`）。既有的 `^TAIEXTR`／`^TPEXTR` 基準沒有動。

程式：`services/discussions.py`（規則都在這裡）、`api/routes/discussions.py`、`api/schemas_discussions.py`；資料表在 migration `0013`
（`discussion_topics`、`discussion_topic_symbols`、`discussion_replies`、`discussion_reactions`、`discussion_reports`、
`discussion_suspensions`、`discussion_post_log`，以及 `users.public_name`、`public_name_key`、`public_name_changed_at`）。

### 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `ADMIN_EMAILS` | 空 | 站方管理員的 email（逗號分隔、不分大小寫，和 `users.email` 比對）。不是管理員呼叫 `/admin/*` → 404；沒登入 → 401。`GET /me` 的 `is_admin` 也看它 |

### 合約沒寫清楚、我做的解讀

- **`GET /users/me`**：既有的端點是 `GET /me`。兩個路徑都有，回應相同，都多了 `public_name`、`is_admin`、`public_posting_suspended_until`
  （`POST /auth/dev-login`、`PATCH /me`、`PATCH /me/preferences` 的 `User` 也有）。`PUT /users/me/public-name` 另有別名 `PUT /me/public-name`。
- **時間格式**：這一節的時間（`created_at`、`last_activity_at`、`first_reported_at`、`until`、`public_posting_suspended_until`）照合約範例用
  UTC、`Z` 結尾、到秒（`2026-11-13T02:10:00Z`）；其他章節維持 `+08:00`。
- **錯誤多帶的欄位放在 `error` 物件裡**（和 `code`、`message` 同一層）：`rate_limited` → `error.retry_after_seconds`（整數秒，至少 1；
  另有標準的 `Retry-After` 標頭）；`posting_suspended` → `error.until`；`public_name_cooldown` → `error.retry_after_days`（整數，1–7）。
- **公開暱稱**：
  - 唯一性用 NFKC＋casefold 後的字串比對（連續空白視為一個）；顯示用使用者輸入的原樣（去頭尾空白）。
  - 保留字比對同樣不分大小寫與全半形，字中間夾空白也算（`s y s t e m`）→ 422 `validation_error`。
  - 「顯示名稱規則」放行、但畫面上看不到的字元（零寬連接符、韓文填充字、點字空白、變體選擇符等，`textsafe.visible`）：比對唯一性與
    保留字時忽略，而且看得見的字至少要 2 個（擋掉「空白暱稱」與夾隱形字元冒充別人）。標題、內文、回覆也至少要有一個看得見的字。
  - **「7 天內只能改一次」：第一次設定不算**（合併時調整）：第一次設定不啟動冷卻，之後每改一次要等 7 天；打錯字可以馬上改一次
    （存成一模一樣的名字不算、不重新計時）。
- **頻率限制**：
  - 「天」「小時」是**滾動視窗**（過去 24 小時、過去 60 分鐘），不是日曆日；`retry_after_seconds` 是最早那一則離開視窗、或 10 秒間隔結束
    的時間（取較晚的）。
  - 由 `discussion_post_log`（每則發言一列，不含內容）計算，沒有記憶體狀態；**刪掉發言不會把額度還回來**。同一位使用者超過 1 天的列在他
    下次發言時刪除。
  - 「任兩則公開發言至少間隔 10 秒」跨主題與回覆；群組發言沒有間隔，也不佔公開的額度。
  - 數字都在 `services/discussions.py` 最上面（`RATE_LIMITS`、`PUBLIC_POST_GAP`、`PUBLIC_NAME_COOLDOWN`）；時鐘可用 `set_clock` 換掉（測試不用等）。
  - 公開發言的檢查順序：停權（403）→ 沒有公開暱稱（409）→ 頻率（429）。
- **沒登入讀群組主題**：`GET /discussions/topics/{id}` 與 `…/replies` 對沒登入的人回 **404**（和不存在的 id 一樣，不透露主題存在）；
  清單的 `scope=group`／`all`、`mine=true` 以及所有寫入才是 401。
- **清單參數**：`scope` 預設 `public`；`scope=group` 一定要帶 `group_id`（沒帶 422、不是成員 404）；其他 `scope` 帶了 `group_id` 會被忽略（不會多看到
  東西）。`symbol` 找不到商品就是空清單。`limit` 上限 100。發主題時 `scope=public` 帶 `group_id` → 422（避免把群組的話誤發成公開）。
- **內文**：Tab 也算控制字元 → 422（只有換行例外）；開頭、結尾的空行會去掉。`symbols` 最多 5 個，重複的只留一個，找不到 → 422 `unknown_symbol`。
- **群組範圍的作者**：已離開群組的人顯示 `{"name": "已離開的成員", "is_you": false, "user_id": null, "avatar_url": null}`（和群組留言相同，
  不再露出身分）；帳號刪除是 `name: null`。公開範圍的作者物件**只有** `name`、`is_you` 兩個鍵（沒有值為 null 的 `user_id`／`avatar_url`）。
  群組端點不會出現公開暱稱（公開身分和群組身分互相對不起來）。
- **隱藏**：
  - 隱藏的主題不出現在**任何**清單，包括作者自己的 `mine=true`（照合約字面）。
  - 直接打開隱藏的主題時 `body` 是 `null`，但**標題、標記的商品、回覆仍然回傳**（合約只寫 `body: null`）。
  - `reply_count` 含被隱藏的回覆（它們留在原位）。被隱藏的內容仍可按表情、被檢舉、被作者刪除。
  - `can_reply`：已登入而且主題沒被隱藏。沒有公開暱稱、被停權時仍是 `true`（發的時候才回 409／403）。
- **刪除**：公開內容只有作者能刪（站方管理員 403）；群組內容另外允許 owner／admin。刪回覆後 `last_activity_at` 退回剩下最新的那一則
  （沒有回覆就是主題建立時間）。刪除群組時連同它的主題一起刪。
- **表情**：`PUT`／`DELETE /discussions/reactions` 都回 204、沒有內容（重新讀主題或回覆才看得到新的 `reactions`）。
- **唯讀查看（`X-Forliosa-View-As`）**：`GET /discussions/topics`、`/discussions/topics/{id}`、`…/replies`、`GET /users/me` 忽略標頭，
  以登入者本人回答；寫入仍然被全站的規則擋下（403 `read_only`），`/admin/*` 的讀取回 403 `view_as_not_allowed`。
- **AI**：沒有新增任何 AI 工具；`forliosa/ai` 不讀這些資料表（有測試）。

### 檢舉與站方管理

- 檢舉：`note` 最多 300 字、可換行（規則同內文）。同一人對同一則只留第一次（之後換理由也不算）。已處理過的對象再被別人檢舉，會回到 `open`。
- `GET /admin/discussions/reports`：依「最近一次被檢舉的時間」新到舊。`status=open` 是還有未處理檢舉的對象，`resolved` 是全部處理完的。
  `report_count`、`reasons`、`notes` 算這個對象的所有檢舉（含已處理的）。`topic_id` 每一筆都有（主題就是它自己）。主題的 `excerpt` 是
  「標題｜內文」的前 120 字，回覆是內文前 120 字。
- `POST /admin/discussions/moderation`：沒有人檢舉的公開內容也可以直接 `hide`。`unhide` 不會把檢舉改回未處理。
- 停權：`days` **一定要給**（`1`、`7`、`30` 或明寫 `null`＝永久；沒給 422），避免漏欄位變成永久停權。`POST` 回 201 與那一筆
  （`{"id", "public_name", "until", "reason", "created_at"}`，`reason` 沒填是 `null`）。同一個人已經在停權中再停一次，是**改掉原本那一筆**
  （同一個 `id`，新的 `until`／`reason`）。作者帳號已刪除 → 422。解除已解除的 → 204；不存在的 id → 404。
- 管理端點對群組範圍的 `target` 一律 404（站方看不到群組內容）。

### 討論串待產品負責人確認

1. ~~公開暱稱第一次設定也算一次~~：合併時已改成第一次設定不算（之後每改一次等 7 天）。
2. ~~隱藏的主題仍看得到標題~~：合併時已改——作者與站方管理員以外的人拿到 `title: "（已被站方隱藏的主題）"`、`symbols: []`、`body: null`（合約已同步）。
3. **作者在自己的清單裡看不到被隱藏的主題**（合約：隱藏的不出現在清單）。建議之後讓 `mine=true` 列出自己被隱藏的主題並標示 `status: "hidden"`。
4. **頻率限制用滾動 24 小時／60 分鐘**。建議維持（比「每天午夜歸零」難鑽漏洞）。
5. ~~檢舉本身沒有頻率限制~~：合併時已加——每人每小時 20 則新的檢舉（`REPORT_LIMIT`；重複檢舉同一則不算），超過回 429 `rate_limited`。

## 2026-11-13 盤中狀態與收盤價公布偵測

實作合約「收盤價的標示與盤中狀態」的後端部分：`GET /meta/market-status`、報價的 `as_of`／`is_realtime`、worker 的收盤價公布偵測。
沒有新的資料表，也沒有新的環境變數。

### `GET /meta/market-status`（`market_calendar.market_status`）

- 不用登入、不讀使用者資料；帶 `X-Forliosa-View-As` 也照常回（`/meta/*` 本來就忽略標頭）。
- `is_trading_day` 用官方行事曆：每次請求重讀一次存檔的 `market_holidays`（一個小查詢）；那一年沒有官方資料時用內建清單。
- `is_open`：交易日 09:00（含）到 13:30（**不含**）。剛好 13:30:00 回 `false`——和前端「已過 13:30」的狀態接得上。
  `timeutil.is_tw_market_open` 也一併改成不含 13:30（原本只差在 13:30:00 整那一瞬間；AI 的頁面情境文字用它）。
- `date` 是台北時間的今天；`open`／`close` 固定 `"09:00"`、`"13:30"`。時鐘可用 `market_calendar.set_clock` 換掉（測試用）。

### 報價的 `as_of` 與 `is_realtime`

- 檢查結果：所有真實來源（存檔、證交所／櫃買 OpenAPI、shioaji-data）本來就把 `as_of` 設成資料列日期的 13:30（+08:00）、`is_realtime` 是 `false`；
  `is_realtime: true` 只會出現在 personal 模式的示範資料抖動。
- 另外在 `MarketData.quotes` 加了一道保證：`DATA_POLICY=commercial` 時，不論來源回什麼，台股報價的 `as_of` 一律是 `trade_date` 的收盤時間、
  `is_realtime` 一律 `false`（之後接新來源也不會破壞合約）。`/quotes`、`/instruments/{symbol}/quote`、`/stream/quotes`、自選都經過這裡。

### 收盤價公布偵測（worker 的 `close_watch`，`archive.py`：`close_watch_day`、`ClosePublication`、`close_archived`）

- **時間**：交易日 13:35 起到隔天 08:30（不管隔天是不是交易日），每 15 分鐘一次；非交易日的下午與晚上、每天 08:30–13:35 都不做。
  交易日同樣依官方行事曆。
- **問法**：對兩個收盤檔——證交所 `openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL`、櫃買
  `www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes`（就是存檔本來在抓的那兩個檔）——各送一個**條件式請求，而且只要前 1,024 位元組**
  （`If-None-Match`／`If-Modified-Since`＋`Range: bytes=0-1023`，`Accept-Encoding: identity`；`HttpFetcher.probe`）。
  檔案沒換：304、沒有內容。檔案換了：206，回前 1 KB，第一列的 `Date` 就是資料日期。
  2026-11-13 12:35（台北）實測兩台主機都支援：`If-None-Match` 與 `If-Modified-Since` 都回 304、`Range` 回 206、也都有 `ETag`／`Last-Modified`。
  主機若哪天不理會條件或 `Range`，就自動變成「每次檢查一個一般請求」（只讀前 1 KB 就關閉連線），邏輯不變。
- **頻率**：和其他請求共用同一個每主機間隔（`twse.com.tw` ≥ 3 秒、`tpex.org.tw` ≥ 2 秒）與白名單（`ALLOWED_URL_PREFIXES`）；
  不碰證交所網站與 MIS。一個市場一天最多 76 次檢查，幾乎都是 304。
- **公布之後**：那個市場的存檔群組（`twse` 或 `tpex`）跑一次——和排程跑的是同一個 `Worker.archive`，所以收盤價、本益比、公告、參考價、指數、
  股利自動入帳都一起更新——接著跑一次 `after_close_refresh`（商品主檔、持股與自選的收盤）。API 端的報價快取 30 秒，之後畫面就是新的收盤價；
  估值、持股市值、今日損益都是讀取時計算，不需要另外重算。
- **只做一次、重啟不受影響**：某個市場「當天進來了沒」只看資料庫：`dataset_status` 的 `twse-openapi/price`／`tpex-openapi/price`
  （存收盤價時一起寫，值是已存檔的最新交易日，**只會往前不會倒退**——CDN 偶爾回舊檔時不會讓已存的日子看起來不見）。
  進來了就不再問那個市場；兩個市場都進來就完全停止。排程的存檔先拿到也算。記憶體裡只留上次的 `ETag`／`Last-Modified`（讓下一次是 304），
  重啟後第一次檢查重新讀前 1 KB，不會重抓整個檔，也不會重跑已完成的市場。
- **失敗**：連不上、被拒絕 → 記一行警告，下一次檢查再問；另一個市場照常。偵測到公布但存檔失敗（檔案抓不下來）→ 下一次檢查會再跑一次存檔
  （仍是 304，但資料庫還沒有那一天）。到 08:30 都沒公布 → 停止，等當天 08:10／21:40 的排程。
- **原有排程都保留**（08:10、14:40、21:40 存檔；14:35、23:45 `after_close_refresh`）：它們還負責群組裡其他資料集，也是偵測沒涵蓋到時的保底。
- 附帶：`/meta/attributions` 的 `twse-openapi/price`、`tpex-openapi/price` 現在有 `last_updated`（原本是 `null`）。
- 測試（不連網）：`tests/test_close_watch.py`（假時鐘＋`httpx.MockTransport`：22:30 公布、隔天 04:00 公布、一直沒公布、一早一晚、中途重啟、
  存檔失敗重試、排程先拿到、主機不支援條件式請求、主機連不上、非交易日與官方休市日）、`tests/marketdata/test_http_probe.py`、
  `tests/marketdata/test_quote_time.py`、`tests/api/test_market_status.py`。

### 待產品負責人確認

1. **14:35 的 `after_close_refresh` 與 14:40 的存檔現在大多拿不到當天收盤**（交易所晚上到清晨才公布，只觀察過一天）。這一版都保留；
   建議上線觀察一兩週 worker 記錄裡 `close watch: … has published` 的時間，再決定要不要拿掉 14:35／23:45 那兩次。
2. **公布之後跑的是整個市場群組**（上市 12 個存檔工作、上櫃 8 個，每個工作 1–5 個請求），不是只抓收盤檔。好處是本益比、參考價、公告同時更新，
   代價是每個市場每天多一輪請求（都受每主機間隔限制）。建議維持。

## 2026-11-13 AI 技術分析與盤中價格（`get_technicals`）

產品負責人的決定（2026-11-13）：AI 可以做技術分析；盤中回答時用「拿得到的最新合法價格」——使用者自己在問題裡打的價格，或模型用既有的
`web_search` 在可引用的公開來源找到的價格。**後端沒有新增任何向交易所、MIS、券商或資料商取報價的工具**，`web_fetch` 照舊封鎖
`www.twse.com.tw`、`mis.twse.com.tw`。AI 的既有限制不變：只做分析與整理、不下買賣指令、不給目標價；數字只來自工具結果、使用者自己的說法、
或附引用的網路來源。沒有新端點、沒有 migration；`docs/api-contract.md` 的 AI 段落沒有工具清單，所以沒有改它。

### 指標（`domain/technicals.py`，純函式、不連網、沒有 pandas／numpy）

輸入是未還原權息的日 K（和 `get_stock_history` 同一份資料）。每個區塊都有 `date`（最後一根 K 的日期），高低點與事件各自帶日期。

| 項目 | 算法與慣例 |
|---|---|
| 均線 MA5／10／20／60／120／240 | 收盤價簡單平均；`bias_pct`（乖離率）＝收盤 ÷ MA − 1。根數不夠的不出現 |
| RSI(14) | Wilder：前 14 個漲跌的簡單平均當起點，之後 `(前值 × 13 + 當日) ÷ 14`；需 15 根。漲跌平均都是 0（完全沒動）時不給值並在 `notes` 說明 |
| KD(9,3,3) | 台灣慣例：RSV＝(收盤 − 9 日最低) ÷ (9 日最高 − 9 日最低) × 100；K＝⅔·前 K＋⅓·RSV；D＝⅔·前 D＋⅓·K；起始值 50；需 9 根。9 日高低相同時 RSV 取 50。缺最高／最低價的日子用收盤價代替（`notes` 會說） |
| MACD(12,26,9) | 用**收盤價**（不是需求指數 DI）；EMA 的 α＝2 ÷ (n＋1)，以前 n 筆的簡單平均當起點；`dif`＝EMA12 − EMA26、`macd`＝DIF 的 9 日 EMA（訊號線）、`osc`＝DIF − MACD（柱狀體，不乘 2）；需 34 根 |
| 布林通道(20, 2σ) | 中軌 MA20、σ 是母體標準差；`percent_b`＝(收盤 − 下軌) ÷ (上軌 − 下軌)；`bandwidth`＝(上軌 − 下軌) ÷ 中軌 |
| 量比 | 最新成交量 ÷ **前** 5／20 日（不含當日）的平均量（`ratio_prev5`、`ratio_prev20`）；需 6／21 根。成交量是 0 或沒有的日子視為「沒有成交量資料」，含這種日子的區間不算（`notes` 會說） |
| 20／60 日高低點 | 含當日的最高價／最低價與日期（相同時取最近一天）、收盤價距高點與低點的幅度 |
| 連漲連跌、缺口 | `streak`（方向與天數）；`change`／`change_pct`（對前一日收盤）；`open_gap_pct`（開盤對前一日收盤）；`gap`: `up`／`down` 只在整根 K 高於前一日最高或低於前一日最低時出現 |
| 事件（最近 10 根 K，新的在前） | MA5／MA20、MA20／MA60 交叉；K／D 交叉（附 K、D 值與所在區：80 以上、20 以下、之間）；MACD 柱狀體正負轉換；收盤在布林上軌之上／下軌之下；最高價創 20／60 日新高、最低價創新低（同一天只報較長的那個）。每筆 `{date, type, text}`，是帶日期的事實，沒有建議字眼。兩線相等的日子沿用前一天的方向，不算交叉 |

- 根數不夠的項目**不出現**，並在區塊的 `notes` 第一句點名：「日 K 只有 115 根（2026-06-01 起），不足以計算：MA120（需 120 根）、MA240（需 240 根）」。
  存檔從 2026-06-01 開始，所以 120／240 日均線目前通常沒有。不到 100 根時另外提醒 RSI／KD／MACD 是遞迴指標、和用更長歷史的看盤軟體可能略有差異。
- 四捨五入：價格、均線 2 位；RSI、K、D 2 位；MACD 3 位；量比 2 位；其他比率 4 位（分數，0.0123＝1.23%）。

### 工具 `get_technicals`（`ai/tools.py`）

輸入（`strict`）：`symbol`（必填，代號或名稱）、`price`（選填，數字）、`price_source`（選填，`"user"`｜`"web"`；有 `price` 就必填）、
`price_time`（選填，自由文字，例如「11/13 10:42」或來源的寫法，最多 80 字）。進度標籤：「計算 2330 的技術指標」。

```jsonc
{"symbol": "2330.TW", "name": "台積電", "currency": "TWD",
 "as_of_close": {                       // 官方收盤資料；沒有任何日線時是 null
   "official": true, "date": "2026-11-12", "close": 1085.0,
   "prev_close": {"date": "2026-11-11", "close": 1070.0}, "change": 15.0, "change_pct": 0.014,
   "open_gap_pct": 0.0047, "gap": "up",              // gap 只在有缺口時出現
   "streak": {"direction": "up", "days": 3},         // up | down | flat
   "ma": {"ma5": {"value": 1072.4, "bias_pct": 0.0117}, "ma10": {…}, "ma20": {…}, "ma60": {…}},
   "rsi14": 62.31, "kd": {"k": 71.2, "d": 65.4}, "macd": {"dif": 12.3, "macd": 10.1, "osc": 2.2},
   "bollinger": {"upper": 1090.2, "mid": 1051.3, "lower": 1012.4, "percent_b": 0.93, "bandwidth": 0.074},
   "volume": {"latest": 33056476, "prev5_avg": 28000000, "ratio_prev5": 1.18, "prev20_avg": 30000000, "ratio_prev20": 1.1},
   "high_low": {"20d": {"high": 1095.0, "high_date": "2026-11-12", "low": 1010.0, "low_date": "2026-10-21",
                        "close_vs_high_pct": -0.0091, "close_vs_low_pct": 0.0743}, "60d": {…}},
   "events": [{"date": "2026-11-10", "type": "ma5_ma20_cross_up", "text": "5 日均線由下往上穿越 20 日均線（黃金交叉）"}],
   "notes": ["日 K 只有 115 根（2026-06-01 起），不足以計算：MA120（需 120 根）、MA240（需 240 根）"]},
 "with_provisional_price": {            // 只有傳了 price 而且用得上時才有
   "official": false, "price": 1096.0, "price_source": "user",       // user | web
   "price_label": "你提供的價格",                                     // web：「網路來源報導的價格」
   "price_time": "11/13 10:42",                                       // 沒給：「未提供」
   "caveat": "不是官方報價，也不是即時報價：把這個價格暫時當成 2026-11-13 的收盤價算出來的結果，盤中還會變動，收盤後以官方收盤價為準",
   "date": "2026-11-13", "prev_close": {"date": "2026-11-12", "close": 1085.0}, "change": 11.0, "change_pct": 0.0101,
   "streak": {…}, "ma": {…}, "rsi14": 63.0, "kd": {…}, "macd": {…}, "bollinger": {…}, "high_low": {…},
   "notes": ["今天的開盤、最高、最低價未知，都以這個價格代替：KD 與區間高低點只反映這個價格；沒有今天的成交量，不提供量比"],
   "events_if_closed_at_price": [{"date": "2026-11-13", "type": "new_high_20d", "text": "這個價格 1,096 高於前 19 個交易日的最高價（20 日新高）"}]},
 "units": "價格是未還原權息的原始價…", "notes": ["資料累積中：自 2026-06-01 起存檔"],
 "sources": ["…"], "is_demo": false}
```

- 資料走 `services.instruments.history(md, symbol, "5Y")`（就是 `get_stock_history` 用的那一個），所以 `DATA_POLICY`、`sources`、`is_demo`、
  「資料累積中」的 `notes` 都和它一致；只取最後 500 根計算。商用模式的美股：`as_of_close: null`、`notes: ["美股目前沒有可商用的行情來源，不提供價格資料"]`。
- **暫定價的那一天**＝今天（或今天以前）最近的台股交易日。存檔裡已經有那天的官方收盤 → 不用暫定價，`notes` 說明「…的官方收盤價已經有了，沒有使用提供的價格」
  （不是錯誤）。暫定 K 棒的開高低都等於那個價格、沒有成交量：這個區塊沒有 `volume`、`gap`、`open_gap_pct`，事件只列這一根會造成的（`events_if_closed_at_price`）。
- **被拒絕的價格**（`is_error` 的工具結果，模型可以轉述）：不是大於 0 的數字；有 `price` 沒有合法的 `price_source`；台股／台股 ETF 的價格和最近收盤價相差超過
  ±10.5%（超出單日漲跌幅，多半是打錯或看錯股票）。訊息會寫出最近收盤價、日期、差距，並要模型向使用者確認、不要自己改價格。
- 合約沒寫、我做的選擇：
  1. 存檔落後時（最近收盤和暫定日之間隔了 k 個交易日），界線放寬成 (1 ± 10.5%)^k，並在 `notes` 說缺了幾個交易日、指標可能失真。
  2. 最近收盤之後到暫定日之間有除權息日時（從 `instruments.dividends` 看），除權息參考價會低於前一日收盤，**不做漲跌幅檢查**並在 `notes` 說明。
     分割、減資、新上市前五日無漲跌幅這幾種情況沒有處理，仍會被 ±10.5% 擋下（見待確認）。
  3. 最近 60 根 K 之內有除權息日時，最上層 `notes` 列出日期並提醒「價格未還原，當天的缺口與跨過那天的均線、指標都含除權息的影響」。
  4. 美股（personal 模式有示範資料時）不支援暫定價：照常給收盤區塊，`notes` 說「暫定價只支援台股與台股 ETF」。
  5. `price_source` 沒給就拒絕，而不是猜成 `user`：來源標錯比多一輪工具呼叫嚴重。

### 系統提示（`ai/prompts.py`，`CHAT_SYSTEM`）

- 「資料從哪裡來」第一條多一個數字來源：「或使用者在對話中自己提供的數字（要標明是使用者提供的）」；「網路搜尋不是行情來源…」那一句後面加
  「（唯一的例外是下面「技術分析與盤中價格」寫的盤中價格）」。其他規則沒有動。
- 新增「## 技術分析與盤中價格」一節：技術面問題呼叫 `get_technicals`、白話說明並寫日期、只描述訊號不下指令不給目標價／停損價；未還原權息與存檔不足要照實說；
  盤中（頁面情境寫「盤中」）而問題和現在的價格有關時，先寫最新官方收盤價與日期，然後 (1) 使用者給了價格就用（`price_source: user`，稱為「你提供的價格」，
  不是查證過的資料）、(2) 沒給就用 `web_search` 找可引用的公開來源寫的最近價格，沒找到換關鍵字再找，找到後 `price_source: web`、`price_time` 填來源寫的時間，
  寫那個價格的句子一定要引用那個來源、寫出來源名稱與時間（來源沒寫時間就照實說）、說可能已經過時、不可稱為即時或官方報價、(3) 找不到就直說、用最新收盤分析、請使用者輸入價格；絕對不要猜價格；
  `as_of_close` 與 `with_provisional_price` 分開說明。
- 系統提示是快取前綴的一部分：部署後既有對話的第一個請求會重寫快取；重播的 thinking 區塊若被拒絕，照既有機制改用純文字接續。

### 「無來源」標記（`ai/grounding.py`）

這個工具的數字和其他工具一樣沒有引用、也不會被標「無來源」（檢查只找「像新聞敘述」的句子）。盤中流程會同時用到 `web_search`，所以技術分析的句子會被檢查；
實測既有規則會誤標三種句子，已收窄：
- 指標縮寫（`MA20`、`EMA`、`SMA`、`RSI`、`KD`、`MACD`、`DIF`、`OSC`、`RSV`、`BIAS`、`Bollinger`）不算「具名的主體」（原本任何大寫開頭的英文字都算）。
- 弱動詞在描述我們自己的價格資料時不算：「收盤價…公布／公告」「公布的（官方）收盤價」「交叉／訊號／型態…成立」「向上／向下／往上／往下通過」。
  同一句裡另有新聞動詞仍然會標（「台積電 11/12 公布財報後，收盤價大漲。」照標）。
- 既有的誤標沒有動：「投資人」裡的「投資」加上日期仍會被當成新聞句（例如「投資人仍要留意 11/20 的法說會」）。

### 背景工作：`session_purge`

`api/deps.py` 的 `purge_expired_sessions` 原本沒有任何地方呼叫（過期的登入 session 只會被拒絕，不會被刪）。worker 新增 `session_purge`：每天 04:50（台北）
刪除 `expires_at` 已過的 `sessions` 列。測試在 `tests/test_worker.py`。

### 測試（不連網）

`tests/domain/test_technicals.py`（18 個：RSI 用常見的 33 筆收盤價範例，第一個值手算 70.46，並與範例表的數字相差不到 0.08；KD 三天手算；MACD 用直線的
閉合解（DIF 恆為 14、柱狀體 0）與另一份獨立寫法比對；布林、量比、高低點、事件逐項手算或暴力比對；平盤、缺高低價、根數不足、零成交量）、
`tests/ai/test_technicals_tool.py`（13 個：只有收盤、使用者價格、網路價格、被拒絕的價格、短歷史、美股、官方收盤已入檔、存檔落後、除權息日、
註冊與標籤、含 `web_search` 的一輪對話與「無來源」、系統提示）、`tests/test_worker.py`（`session_purge`）。

### `python -m forliosa.ai.smoke --ask "…" [--symbol 2330.TW]`

smoke 多一個選項：只問這一題（給 `--symbol` 就當成在那檔的個股頁問），用來看實際模型怎麼用 `get_technicals`。原本的兩題不變。

### 實測（2026-11-13，`claude-haiku-5-5`，三把金鑰都正常）

- `python -m forliosa.ai.smoke`（原本兩題）：正常，合計約 US$0.026（第二題搜尋 2 次）。
- `--ask "台積電的技術面怎麼樣？…" --symbol 2330.TW`，示範資料（`DATA_POLICY=personal`）：模型只呼叫 `get_technicals` 一次，逐項說明均線、KD、RSI、MACD、
  布林與量比並寫日期，提到除權息未還原，註明示範資料，沒有買賣建議；US$0.0023。
- 同一個指令在這個沙盒的商用模式（存檔是空的）加上使用者價格：工具回「資料累積中」且沒有使用那個價格，模型照實說算不出來；US$0.0010。
- 暫時的資料庫（2330 的日 K 是**測試用的合成資料**，最後兩天用真實收盤）、時鐘設在盤中 10:45，兩題：
  1. 沒給價格：模型先搜尋一次（「台積電 2330 股價 今天 盤中」）、呼叫 `get_technicals`，再用搜尋結果裡鉅亨網報價頁的價格呼叫一次
     （`price_source: web`、`price_time: "11/13 01:11（鉅亨網頁面標示）"`）。回答先寫 11/12 官方收盤，網路價格那一句有引用、寫了時間與「來源未標明時區」、
     說不是官方數字、收盤後會改變，最後請使用者輸入現在的價格；US$0.014。第一次的提示寫法（「一定附上來源」）模型只在文字裡寫來源名稱、沒有引用，
     改成「寫出那個價格的句子一定要引用那個來源」之後才有引用。
  2. 「我看到台積電現在 2,365（10:40）…」：`price_source: user`、`price_time: "10:40"`，回答先寫官方收盤，再用「你提供的 10:40 價格 2,365（非官方報價）」
     說明 KD、均線會怎麼變，最後說明收盤後以官方收盤價為準；US$0.0011。

### 待產品負責人確認

0. **網路來源的時間不可靠**：實測搜尋結果裡報價頁的時間是「11/13 01:11」（看起來是 UTC，等於台北 09:11），模型照原文寫並說明沒有標時區。
   搜尋摘要裡的價格可能是幾小時前的；系統提示已要求寫出時間並說可能過時，但使用者仍可能把它當成現在的價格。
1. **`web_search` 每個請求最多 3 次（`AI_WEB_SEARCH_MAX_USES`）沒有改**。「搜尋夠了再回答」目前靠系統提示（沒找到就換關鍵字再找）與這個上限；
   要讓模型多找幾次可以把上限調到 5，每次搜尋另計費。建議先觀察實際對話再調。
2. **盤中價格在搜尋結果裡不一定找得到**：新聞通常只寫「早盤」「盤中一度」而沒有時間，報價頁的價格不一定出現在搜尋摘要。找不到時 AI 會照規則說查不到並請使用者輸入。
   若要提高命中率，只能靠使用者輸入或日後取得授權的報價來源。
3. **±10.5% 檢查的例外**：除權息日已處理；分割、減資恢復買賣、新上市前五個交易日（無漲跌幅）仍會被擋，使用者會被請去確認價格。建議先這樣，遇到再補。
4. **MACD 用收盤價**（多數看盤軟體與國際慣例）；部分台灣教材用需求指數 DI＝(最高＋最低＋2×收盤) ÷ 4。要改成 DI 是一行的事，但暫定價只有一個價格時兩者相同。
5. **量比定義**：最新成交量 ÷ 前 5／20 日均量（不含當日）。看盤軟體的「5 日均量」通常含當日，數字會略有不同。

## 2026-11-13 帳號：匯出資料、刪除帳號、條款版本

合約：`docs/api-contract.md`「帳號：匯出資料、刪除帳號、條款版本」。程式：`services/account.py`、`api/routes/users.py`；migration `0014`。

- **`GET /me/export`**：一律是登入者本人的資料（查看別人資產時標頭被忽略）。金額與股數是資料庫裡的十進位字串（不是浮點數），時間是 UTC（`Z`）。
  合約列的欄位之外多一個 `holding_snapshots`（「只記持股」帳戶的快照，也是使用者自己輸入的資料）。別人授權給我的（`delegations.received`）只列對方的顯示名稱與時間，
  不列對方的帳戶。AI 訊息照資料庫原樣（含工具呼叫的結果——那是使用者自己的帳本資料）。
  **頻率限制（每人每小時 5 次）記在 API 程序的記憶體裡**：重啟就歸零、多副本時各算各的。目前只有一個副本；要嚴格的話之後改記在資料庫。
- **`DELETE /me`**：一個資料庫交易。自己的資料用明確的順序刪（不依賴各資料庫 cascade 的順序）；群組留言、討論主題與回覆、AI 用量靠外鍵的 `ON DELETE SET NULL` 留下、作者變成 null。
  我送出的檢舉會刪掉（外鍵本來是 SET NULL，這裡明確刪除）。擁有的群組：最早加入的 admin → 最早加入的其他成員 → 沒有人就連內容刪除（`groups.purge`）。
- **停權不因刪除帳號而解除**：刪除時如果公開發言正在停權，留一筆 `discussion_suspension_carryovers`——鍵是登入身分（`discord:<Discord 使用者編號>`）用 `SESSION_SECRET` 做的
  HMAC-SHA256，沒有金鑰無法還原成 Discord 編號，也不含 email 或名稱。同一個 Discord 帳號再註冊時，停權接到新帳號上（到原本的期限），那筆紀錄刪除；過期的在下次有人註冊時清掉。
  **更換 `SESSION_SECRET` 會讓這些紀錄失效**（對不起來）。只有 Discord 登入建立的帳號有登入身分；開發登入的帳號沒有，不會留紀錄。
- **條款版本**：環境變數 `TERMS_VERSION`（例如 `2026-11-13`；不設＝不啟用，`GET /me` 的兩個欄位都是 null、`POST /me/terms-accept` 一律 409）。
  帳號建立時（Discord 第一次登入、開發登入）記下當時的版本與時間；版本改了之後，舊帳號的 `terms_version_accepted` 和 `terms_version_current` 不同，前端請使用者按「知道了」。
  在啟用之前就存在的帳號 `terms_version_accepted` 是 null，第一次也會被問。

### 待產品負責人確認

1. **`TERMS_VERSION` 什麼時候設**：建議兩份文件定稿（沒有【待填】）那天設成生效日期；現在不設。
2. **匯出檔裡的 AI 對話**包含 AI 工具查到的帳本資料與網路搜尋結果的摘要（都是那段對話的內容）。檔案可能很大；目前沒有分頁或壓縮。
3. **刪除帳號沒有冷靜期**：按下去就刪、不能復原（畫面上要輸入「刪除我的帳號」）。要不要改成 7 天後才真的刪除（期間可以登入取消），由產品負責人決定；建議先維持立即刪除。

## 2026-11-13 `notes` 與空狀態說明的寫法（文案改寫）

產品負責人決定：畫面只講事實，不講授權或系統怎麼存資料；為什麼沒有只在「資料來源與授權」頁講一次（`DESIGN.md`「說明文字怎麼寫」）。後端回給畫面的 `notes` 跟著改了，這份文件前面各節裡的舊句子以這裡為準：

| 以前 | 現在 | 在哪裡 |
|---|---|---|
| 資料累積中：自 2026-06-01 起存檔 | 資料從 2026/06/01 開始（`coverage.since_note`；日期用 `coverage.ymd`） | 日線、估值、籌碼、期貨 |
| 資料累積中：尚未開始存檔 | 還沒有資料 | 同上 |
| 美股目前沒有可商用的行情來源，不提供價格資料 | 美股沒有報價（`coverage.US_NOTE`） | 日線、績效 |
| …含美股時無法計算績效 | AAPL、NVDA：美股沒有報價，含美股的績效算不出來 | `GET /portfolio/performance` |
| 資料累積中：…；需要持股期間每天的收盤價才能計算績效 | 資料從 … 開始；持股期間有幾天沒有收盤價，績效算不出來 | 同上 |
| 資料累積中：…；績效從 2026-06-01 收盤開始計算 | 績效從 2026/06/01 收盤開始算，之前沒有資料 | 同上 |
| 基準 X 目前沒有可商用的資料 | 沒有 X 的資料，不能比較 | 績效、排行、週報 |
| 資料累積中：自 … 起存檔；期間／本週從 … 收盤開始計算 | 資料從 … 開始，這段期間／本週從 … 收盤起算 | 排行、週報 |
| 資料累積中：淨值自 … 起存檔 | 淨值資料從 2026/11/10 開始 | ETF 淨值 |
| 資料累積中：ETF 淨值每個交易日晚上存檔 | 還沒有淨值資料，每個交易日晚上更新 | ETF 淨值 |
| 證交所 OpenAPI 沒有上市股票的個股三大法人（…付費商品…）… | 上市股票沒有逐檔三大法人資料（不在前 20 名時加「；外資持股只公布前 20 名」） | 籌碼 |
| 證交所只公布外資持股比率前 20 名，本股只有… | 外資持股只公布前 20 名，這檔只有名列前 20 名的日子才有外資持股比 | 籌碼 |
| 目前沒有授權的盤中行情來源（…），不提供分時走勢 | 沒有盤中走勢，價格是收盤後公布的收盤價 | `GET /instruments/{symbol}/intraday` |
| ETF 沒有每股盈餘與每股帳面淨值，不提供本益比與股價淨值比區間 | ETF 沒有每股盈餘與每股淨值，所以沒有本益比與股價淨值比區間 | 估值 |
| 尚未偵測到實際公布日：… | 還不知道實際公布日；法定期限是每月 10 日前公布上個月營收／先照季報的法定期限顯示 | 事件 |
| 公司基本資料尚未存檔 | 還沒有公司基本資料 | 公司資料 |
| 美股目前沒有可商用的相關股票資料 | 美股沒有相關股票資料 | 相關股票 |
| 來源標示「本系統帳本」 | 「帳本紀錄」（`datapolicy` 的 `ledger`） | 所有帶 `sources` 的帳本資料 |

- `GET /meta/attributions` 的 `not_used`：拿掉報表代號（T86、MI_QFIIS）與環境變數名稱（`DATA_POLICY=personal`），只寫事實。
- 前端用 `lib/data-notes.ts` 的 `isCoverageNote` 判斷「資料從哪天開始」這一類的說明（舊的「資料累積中」也認得，前後端分開部署時不會漏掉）。
- AI 的提示（`ai/prompts.py`）：工具的 `notes` 會說資料從哪一天開始、缺什麼，模型照實轉述。

## 2026-11-13 Google 登入、條款更新的生效日與摘要、停權原因

**Google 登入**（`services/google_oauth.py`、`api/routes/auth.py`；合約「登入（Discord、Google OAuth）與個人資料」）

- 端點取自 Google 的 discovery document（`accounts.google.com/.well-known/openid-configuration`）：授權 `accounts.google.com/o/oauth2/v2/auth`、token `oauth2.googleapis.com/token`、userinfo `openidconnect.googleapis.com/v1/userinfo`、撤銷 `oauth2.googleapis.com/revoke`。授權碼流程，不用 PKCE、不驗 id token（個人資料是用 access token 在 TLS 上向 userinfo 讀的）。
- 帳號對應是共用的 `discord_oauth.sign_in(db, profile, provider)`：`user_identities` 一人每種登入方式各一筆（`uq_user_identity_user_provider`），同一個已驗證 email 連到同一個帳號。兩種登入都連結的帳號，`avatar_url` 是最後一次登入那一家的頭像。
- state 的簽章內容多一個 `p`（哪一家）；沒有 `p` 的舊 cookie 當成 Discord（部署當下還在登入流程中的人不受影響）。
- 設定：`GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`（SecretStr）、`GOOGLE_REDIRECT_URI`。`Settings.google_enabled`：三個都有，而且正式環境的 callback 是 https。`google_misconfigured`（設了一部分或不是 https）只記警告、不拒絕啟動——Discord 的三個變數設不齊會拒絕啟動，那條規則上線當天讓 API 起不來過一次；Google 是後加的選用登入，不該因為填到一半就讓整站停擺。
- **停權沿用**（`services/account.py`）：刪除帳號時，除了每一個登入帳號的雜湊，也留一筆 `email` 的雜湊（`identity_hash("email", <小寫 email>)`）；建立新帳號時兩種都查，取期限最長的一筆套用，查到的都刪掉。原因：只有 Discord 登入的帳號被停權後刪除，再用同一個 email 的 Google 帳號註冊，原本查不到。隱私權政策 10.3 的說法跟著改了。
- 測試：`tests/api/test_google_auth.py`（Google 的 HTTP 用 `google_oauth.set_transport` 假造）。

**條款更新的那一行**：`TERMS_EFFECTIVE_DATE`（日期）與 `TERMS_SUMMARY`（一句話，`one_line` 後截到 120 字）→ `GET /me` 的 `terms_effective_date`、`terms_summary`；`TERMS_VERSION` 沒設時兩個都是 null。兩個都還沒在正式環境設定（條款還是草稿）。

**停權原因**：`GET /me` 多 `public_posting_suspended_reason`，403 `posting_suspended` 多 `reason`——站方管理員在停權對話框填的「原因（選填）」會給被停權的人看（對話框裡已註明「對方會看到這句話」）。沿用到新帳號的停權也帶著原因。

