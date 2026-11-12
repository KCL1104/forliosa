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
| 新聞 `/news` | 官方公告（重大訊息、證交所新聞） | 同左，FinMind 開啟時另加媒體標題（非商用） |
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
| `overview` | 多 `symbol`。`pe`／`pb`／`dividend_yield` 是證交所／櫃買公布值（存檔，personal 時 FinMind 補舊資料）；ETF 沒有公布殖利率時以近 12 個月現金股利 ÷ 現價計算。`eps_ttm` = shioaji-data 官方季報最近四季 EPS 合計（沒有季報時用 收盤價 ÷ 本益比）。`last_cash_dividend`／`ex_dividend_date` 是**最近一次（含已公告未除息）**的現金股利。`avg_volume_3m` 為近 3 個月日均量（股）。`status.attention` = 最近一個交易日或今天被列為注意股；`status.disposition` = 今天落在處置期間內 |
| `intraday` | 多 `notes`、`is_demo`。**目前 `points` 一律是 `[]`**（沒有授權的盤中來源；MIS 已移除），`notes` 說明；`reference_price` 是當天的參考價；`is_partial` 台股為 `true`。日後接上授權來源時 `points[].volume` 是該分鐘的成交量（股） |
| `chips` | 多 `symbol`、`notes`；`range` 可用 `1M`、`3M`、`6M`、`1Y`。法人單位張（股數 ÷ 1000，保留小數）；外資持股 `pct` 是比率（0.2949）。**上櫃**股票的法人與外資持股來自櫃買 OpenAPI（`tpex_3insti_daily_trading`、`tpex_3insti_qfii`，每日存檔）；**上市**股票任何模式都是空陣列（`notes` 一律有那句說明；`services/stock.py` 的 `LISTED_CHIPS_NOTE`），存檔裡已有的列（例如舊的 FinMind 回補）也不讀。`major_holders.buckets` 是集保 15 個持股分級（另有 `label`，例如「1,000 張以上」）；`pct` 是比率。集保只能下載當週，所以從開始存檔那週起才有資料 |
| `financials` | 多 `symbol`、`period`、`notes`。來源是 shioaji-data 官方季報（2023Q1 起，單季數字，千元）；若存檔中有更新一季的 OpenAPI 財報（`t187ap06` 是**年初至今累計數**），以「本季累計 − 上季累計」換成單季，現金流量為 `null`。`net_income` 是歸屬母公司業主淨利；`free_cash_flow` = 營業 + 投資活動現金流量（OpenAPI／shioaji-data 沒有資本支出科目）。`annual` 只列四季齊全的年度，EPS 用第四季的全年累計 EPS |
| `events` | 每筆多 `sources`、`estimated`、`period`；由新到舊排序（含未來）。範圍：過去 365 天到未來 120 天；`earnings`／`revenue_release`／`investor_conference` 用**實際日期**（見「2026-11-12 第二批」），只有查不到時才用法定期限（季報 5/15、8/14、11/14、3/31；營收每月 10 日；`estimated: true`，前後 60–90 天）。`mine`：未來的除權息／發放 = 目前持有；過去的 = 該日有記股利交易（`amount_estimate` 為實際入帳金額）；其他事件 = 目前持有。除息金額未公告時 `detail` 為「金額尚未公告」 |
| `news` | 每筆多 `sources`、`category`。**官方公告**：該公司的重大訊息與點名該公司的證交所新聞（最近 90 天，最多 30 筆），`source: "公告"`；FinMind 媒體標題只在 personal 明確開啟時附加（`category: "media"`） |
| `position` | 多 `symbol`、`currency`、`as_of`、`sources`、`is_demo`。金額為台幣，`avg_cost` 為原幣。`realized_pnl` 含交易與減資退款；`dividends_received` 已扣二代健保。`markers` 依交易日排序；`stock_dividend` 的 `quantity` 是實際配發股數。**目前股數為 0 一律回 `null`**（即使有已實現損益，見待確認 11） |
| `why` | 多 `symbol`、`sources`。規則：漲跌停 > 漲跌 ≥ 3%（對參考價）、量 ≥ 20 日均量 2 倍、除權息日、處置／注意、當天重大訊息主旨含「財務報告／財報／自結損益」或「營收」。`reasons[].kind` 為 `limit_up`、`limit_down`、`price_move`、`volume`、`ex_dividend`、`disposition`、`attention`、`earnings`、`revenue_release`。最新報價不是今天時文字用日期（「11/11 上漲 3.5%」）。`headline` = 名稱 + 前兩個理由 |
| `watchlist` | 每筆多 `sparkline_interval`（目前一律 `"1d"`：最近 20 個收盤；`"1m"` 保留給日後的授權盤中來源）、`sources`、`is_demo`；`quote` 可能為 `null`。`sparkline[].t` 在 `1m` 是 `"09:01"`，在 `1d` 是日期。`POST` 新增回 201、已在清單回 200（冪等）；找不到商品 422 `unknown_symbol`；最多 200 檔。`DELETE` 不在清單回 404 |
| `/portfolio/upcoming` | 多 `account_id` 參數，每筆多 `is_demo`、`sources`。`days` 1–90。`amount_estimate` = 目前股數 × 每股現金股利（台幣、未扣二代健保）；發放日已過除息日時，若除息日當天已記現金股利交易（自動入帳的股利就是這一筆）就用交易金額；除息金額未公告時為 `null`、標題加「（金額未公告）」。`recurring`（定期定額扣款）見「2026-11-12 第二批」 |

### 存檔（`python -m forliosa.archive`）

- 官方 OpenAPI 只給最新一天，所以 worker 每個交易日 08:10、14:40、21:40 存檔（冪等 upsert），週六 10:00 存集保。
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
| 媒體新聞 | 沒有；`/news` 只有官方公告 |
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

- 商品清單（`master`）的美股仍只有內建的 AAPL、NVDA、VOO、QQQ：SEC 代號表只拿來查 CIK，沒有把一萬多檔美股加進搜尋（見「待確認」23）。
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
14. **新聞來源**：目前只有官方公告（重大訊息、證交所新聞）。媒體新聞需要授權（中央社等，需詢價）。
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
- **工具**：15 個 client tools（2026-11-12 加 `get_derivatives_overview`，見「第三批」），全部 `strict: true`、`additionalProperties: false`、沒有使用者 id 欄位（伺服器帶入登入者）；可選參數合計 15
  個（上限 24）。結果是精簡 JSON（例如 K 線只給統計與最多 30 個取樣點、籌碼只給最近 10 日與區間合計），保留 `as_of`、`is_demo`、`sources`。
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
| `GET /groups/{id}/digests` | `limit` 1–52（預設 8）；依 `week_start`、`id` 新到舊；`cursor` 編碼最後一份的兩個值。`pending`／`failed` 也列出（`summary` 為空字串、`comment_count` 0、`reactions` 空） |
| `Digest` | 多 `notes`（例如 commercial 下「資料累積中：自 … 起存檔；本週從 … 收盤開始計算」）與 `is_demo` |
| `Digest.facts` | `returns` 依加入順序；`common_holdings` 要兩人以上；`industries` 是持有該產業任何一檔的人數（1 人也列，同 `GroupHoldings`）；`trades_count` 是那一週 `trade_date` 在週一到週五、可出現在動態裡的買賣筆數（每筆交易算一筆，不是合併後的則數） |
| `Channels` | 非 owner 的 `webhook_hint` 為 `null`；沒設定的頻道 `notify_*` 回 `true`（預設值） |
| `PUT /groups/{id}/channels/discord` | `notify_trades`、`notify_digest` 可省略（預設 `true`）。重新設定（換網址）會取消還沒送出的推播，`configured_at` 重設 |
| `PATCH /groups/{id}/channels/{kind}` | 回整個 `Channels`；`notify_trades` 由關到開時 `configured_at` 重設（關著那段時間的交易不補送） |
| `DELETE /groups/{id}/channels/{kind}` | 204；Telegram 一併刪除還沒用的連結碼 |
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
  （純文字的 @名稱 在 Telegram 會提及別人）；Discord 一律帶 `allowed_mentions: {"parse": []}`。
- **週報推播**：週報變成 `ready` 時排入（`dedupe_key = digest:<digest>:<kind>`）。內容只有「目前開著 `push`」的成員的數字
  （`sharing.digest_facts_view(..., pushing_only=True)`：報酬要 `returns`＋`push`、共同持股只算 `holdings`＋`push` 的成員、交易筆數只算
  `trades`＋`push`），加上兩個基準與群組頁連結。**AI 摘要**是用所有分享報酬率（以及持股、交易）的成員的數字寫的，所以只有在每一位寫進
  摘要的成員都還在群組、還開著 `push` 與當時分享的那幾項時才附上（合約沒寫，選較保守的做法）。群組裡沒有人開 `push` 時不送。
- **重試**：最多 5 次；失敗後等 1、2、4、8 分鐘（Discord／Telegram 給的 `retry_after` 較長時用它），第 5 次失敗為 `failed`。可重試：429、5xx、
  逾時、連線錯誤、Telegram 401（bot token 設錯是伺服器設定問題）。不重試：其他 4xx、3xx（不跟隨轉址）。
- **停用頻道**：Discord 401／404 → `webhook_invalid`；webhook 解不開（`SESSION_SECRET` 換過）→ `webhook_unreadable`；Telegram 403 →
  `bot_removed`、400「chat not found」→ `chat_not_found`；`my_chat_member` 顯示 bot 被移出（`left`／`kicked`）→ `bot_removed`。停用時
  這個頻道其他還沒送出的列改成 `cancelled`；`push_targets` 不再列出它。owner 重新設定就恢復。
- **Telegram 遷移**：送出時回 `parameters.migrate_to_chat_id`、或 `getUpdates` 收到含 `migrate_to_chat_id` 的訊息 → 頻道改用新的 chat id
  （送出時立刻用新 id 再送一次）。
- `last_error` 只存短標籤（`http_404`、`timeout`、`network`、`not_shared`、`channel_off` …），不存網址或對方回應的內容。

### Telegram 連結（worker `telegram_poll`，每 20 秒）

- `getUpdates`（`timeout=0`、`allowed_updates=["message","my_chat_member"]`），沒有公開的 webhook 端點。`offset` 存在 worker 記憶體：重啟後
  Telegram 會重送還沒確認的更新；超過 10 分鐘的 `/link` 訊息不處理也不回覆（不會在重啟後洗版）。
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
| `telegram_poll` | 每 20 秒（有設 bot 才做事） | `getUpdates` |
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
