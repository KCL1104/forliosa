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
| `benchmark`（績效參數與 `Preferences.benchmark`） | `^TAIEXTR` | 臺灣證券交易所「發行量加權股價報酬指數」（含息），見下方 |

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
- **`Quote.is_realtime`**：只有盤中（09:00–13:30）且是當天的 MIS 報價才是 `true`；收盤後的最終價是 `false`。
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
  `error.code = "ledger_inconsistent"`。商品代號找不到回 422 `unknown_symbol`。
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
  除息日到發放日之間的 TWR 會短暫偏低，發放日再補回。示範資料把股利記在除息日（見待決事項）。
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
  `^TAIEXTR`（發行量加權股價報酬指數，證交所編製、已含息，所以直接用每日漲跌；資料來自 FinMind
  `TaiwanStockTotalReturnIndex`，`data_id=TAIEX`，收盤後公布）。指數代號用 `^` 開頭，不會和台股代號或美股代號
  衝突，也不會出現在搜尋結果。指數沒有資料時（例如 FinMind 暫時無法使用）`benchmark.twr` 與
  `benchmark_index` 為 `null`，不會用示範資料代替。`PATCH /me/preferences` 也接受 `^TAIEXTR`（大小寫不拘、
  可省略 `^`）。
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
| `CORS_ORIGINS` | `https://app.example.com`（逗號分隔） | 結尾的 `/` 會自動去掉；正式環境不能是 `*`（會拒絕啟動），因為帶 cookie 的請求不能對所有網站開放 |
| 登出 | 刪除 cookie 時帶同樣的 `Domain`／`Secure` | 否則瀏覽器不會刪掉 |

測試：`tests/api/test_deploy_config.py`。部署步驟見 [`docs/deploy.md`](../../docs/deploy.md)。


## 2026-11-12 重新設計：個股頁、自選、本週事項（資料來源政策）

### 資料來源政策 `DATA_POLICY`

| | `personal`（預設） | `commercial` |
|---|---|---|
| 可用來源 | 全部；FinMind、證交所 MIS、證交所網站（非 OpenAPI）在 `sources` 標「（非商用）」 | 只用政府開放資料：證交所／櫃買 OpenAPI、集保開放資料、shioaji-data 官方檔，以及由它們建立的自建存檔 |
| 不建立的 provider | — | `twse_mis`、`finmind`（`MarketData` 也會再過濾一次） |
| 存檔中來自 FinMind／證交所網站的資料列 | 可用 | 一律略過（`archive` 依 `source` 欄位過濾） |
| 盤中走勢 `/intraday` | 持股與自選每 60 秒存一點（MIS） | `points: []`，`notes` 說明沒有授權的即時來源 |
| 新聞 `/news` | FinMind 標題（每筆 `sources: ["FinMind（非商用）"]`） | `[]` |
| 上市股票三大法人、外資持股 | 證交所網站 T86／MI_QFIIS（逐日全市場）＋ FinMind 回補 | 不提供（OpenAPI 沒有個股資料），`chips.notes` 說明 |

兩種模式的主要路徑都是「官方開放資料＋自建存檔」，FinMind 只做回補與備援。

### 每個回應的 `sources`

- 物件型回應（`overview`、`intraday`、`chips`、`financials`、`position`、`why`、`Quote`、`History`、`Valuation`）多了
  `sources: string[]`，是給使用者看的標示文字（例如「臺灣證券交易所 OpenAPI（政府資料開放授權條款第 1 版）」）。
  非商用來源一律以「（非商用）」結尾。前端可以直接列出，不要自己翻譯。
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
| `intraday` | 多 `notes`、`is_demo`。`points[].volume` 是**該分鐘的成交量（股）**＝累計量相減；`reference_price` 是當天的參考價。只有任何使用者的持股或自選才會累積（worker 每 60 秒）；`is_partial` = 盤中或還沒有點 |
| `chips` | 多 `symbol`、`notes`；`range` 可用 `1M`、`3M`、`6M`、`1Y`。法人單位張（股數 ÷ 1000，保留小數）；外資持股 `pct` 是比率（0.6812）。`major_holders.buckets` 是集保 15 個持股分級（另有 `label`，例如「1,000 張以上」）；`pct` 是比率。集保只能下載當週，所以從開始存檔那週起才有資料 |
| `financials` | 多 `symbol`、`period`、`notes`。來源是 shioaji-data 官方季報（2023Q1 起，單季數字，千元）；若存檔中有更新一季的 OpenAPI 財報（`t187ap06` 是**年初至今累計數**），以「本季累計 − 上季累計」換成單季，現金流量為 `null`。`net_income` 是歸屬母公司業主淨利；`free_cash_flow` = 營業 + 投資活動現金流量（OpenAPI／shioaji-data 沒有資本支出科目）。`annual` 只列四季齊全的年度，EPS 用第四季的全年累計 EPS |
| `events` | 每筆多 `sources`；由新到舊排序（含未來）。範圍：過去 365 天到未來 120 天；`earnings`／`revenue_release` 是**法定期限**（季報 5/15、8/14、11/14、3/31；營收每月 10 日），只列前後 60–90 天，`detail` 會說明。`mine`：未來的除權息／發放 = 目前持有；過去的 = 該日有記股利交易（`amount_estimate` 為實際入帳金額）；其他事件 = 目前持有。除息金額未公告時 `detail` 為「金額尚未公告」 |
| `news` | 每筆多 `sources`。FinMind `TaiwanStockNews`（最近 3 天，1 小時快取，額度用完回 `[]`）；只回標題、來源、連結、時間 |
| `position` | 多 `symbol`、`currency`、`as_of`、`sources`、`is_demo`。金額為台幣，`avg_cost` 為原幣。`realized_pnl` 含交易與減資退款；`dividends_received` 已扣二代健保。`markers` 依交易日排序；`stock_dividend` 的 `quantity` 是實際配發股數。**目前股數為 0 一律回 `null`**（即使有已實現損益，見待確認 11） |
| `why` | 多 `symbol`、`sources`。規則：漲跌停 > 漲跌 ≥ 3%（對參考價）、量 ≥ 20 日均量 2 倍、除權息日、處置／注意、當天重大訊息主旨含「財務報告／財報／自結損益」或「營收」。`reasons[].kind` 為 `limit_up`、`limit_down`、`price_move`、`volume`、`ex_dividend`、`disposition`、`attention`、`earnings`、`revenue_release`。最新報價不是今天時文字用日期（「11/11 上漲 3.5%」）。`headline` = 名稱 + 前兩個理由 |
| `watchlist` | 每筆多 `sparkline_interval`（`"1m"` 盤中點、`"1d"` 最近 20 個收盤）、`sources`、`is_demo`；`quote` 可能為 `null`。`sparkline[].t` 在 `1m` 是 `"09:01"`，在 `1d` 是日期。`POST` 新增回 201、已在清單回 200（冪等）；找不到商品 422 `unknown_symbol`；最多 200 檔。`DELETE` 不在清單回 404 |
| `/portfolio/upcoming` | 多 `account_id` 參數，每筆多 `is_demo`、`sources`。`days` 1–90。`amount_estimate` = 目前股數 × 每股現金股利（台幣、未扣二代健保）；發放日已過除息日時，若已記股利交易就用交易金額；除息金額未公告時為 `null`、標題加「（金額未公告）」。**`recurring` 目前一律不會出現**：還沒有定期定額的資料模型 |

### 存檔（`python -m forliosa.archive`）

- 官方 OpenAPI 只給最新一天，所以 worker 每個交易日 08:10、14:40、21:40 存檔（冪等 upsert），週六 10:00 存集保。
- 欄位名稱全部取自真實回應（`marketdata/opendata.py` 的說明，測試 fixture 是 2026-11-12 的精簡版）。幾個容易踩到的地方：
  `t187ap04_L` 的鍵是 `"主旨 "`（尾端有空白）；`MI_MARGN` 沒有日期欄位，21:00 前視為前一個交易日的資料；
  `t187ap06` 損益是累計數；櫃買法人鍵名含空白（`ForeignInvestorsInclude MainlandAreaInvestors-Difference`）；
  `announcement/notice` 沒有資料時回一筆空白列。
- **沒有官方個股歷史**：`commercial` 下存檔只能從開始那天累積。`personal` 可用 `backfill` 從證交所網站（T86、MI_QFIIS，每日全市場，
  每 3 秒一次，太快會回 HTTP 307）與 FinMind（逐檔，額度用完就停）回補，回補資料不會覆蓋官方資料列。
- 證交所 OpenAPI 主機偶爾 reset 連線，存檔與 API 端的 OpenAPI provider 都會重試一次。

## 待產品負責人確認

1. **手續費捨去的順序**：目前是 `floor(成交金額 × 0.1425% × 折扣)`，低於最低手續費以最低計。
   有些券商是先算原始手續費 `floor(成交金額 × 0.1425%)` 再以「退佣」方式折扣，且最低 20 元是對原始手續費判斷。
   需要依各券商對帳單確認，可能要做成帳戶層級設定。
2. **二代健保的進位**：目前元以下四捨五入。另外 ETF 收益分配只有「股利所得」部分要扣，資本利得、
   收益平準金部分不用扣；目前以整筆金額判斷。
3. **美股股利預扣 30%**：目前自動帶入；若台美租稅協定生效或券商有不同處理，要再調整。
4. **股利入帳日**：要不要在交易加上 `ex_dividend_date` 欄位（記發放日、用除息日算 TWR）？
5. **FIFO 下的配股與分割**：目前按比例分攤到每一個批次（成本不變、每股成本下降）。
6. **正式登入**：`FORLIOSA_ENV=prod` 時開發登入關閉，而 Email／Google 登入不在這次範圍，
   正式環境暫時無法登入。前端在 401 時顯示說明（開發模式會自動以示範使用者開發登入）。
7. **美股資料源**：目前全部是示範資料；Yahoo 條款禁止轉發，需要決定有授權的來源。
8. **FinMind**：匿名額度很小且與同一 IP 共用；建議申請 token（非商用），商業化要升級 Sponsor Pro 或換來源。
9. **MIS 非官方端點**：偶爾回 502，商業化前必須換成有授權的即時行情。
10. **shioaji-data AI 研究資料**（簡介、產業鏈、題材）授權待定，目前照樣顯示並標示來源。
11. **`position` 已出清的股票**：合約寫「未持有回 null」，所以股數 0 時回 `null`，個股頁就看不到這檔的已實現損益與買賣點。
    要不要改成「從未交易過才回 null，出清後回 `quantity: 0` 的物件」？
12. **commercial 模式的歷史資料**：日線、股利歷史、法人等只能從開始存檔那天累積；在累積足夠之前，日線與股利會退回示範資料
    （`is_demo: true`）。是否接受，或在 commercial 下改為「資料不足」而不顯示示範資料？
13. **上市股票三大法人**：證交所 OpenAPI 沒有個股資料（只有櫃買有），commercial 下上市股票的法人與外資持股是空的。
    證交所網站 T86 是否適用政府資料開放授權需要向證交所確認。
14. **新聞來源**：只有 FinMind（非商用）；commercial 下沒有新聞。要接有授權的新聞源嗎？
15. **定期定額**：`/portfolio/upcoming` 的 `recurring` 需要定期定額計畫的資料模型（帳戶、標的、金額、扣款日）。
16. **財報公布日**：`earnings`／`revenue_release` 事件用法定期限；實際公布日要從重大訊息（已存檔）或 MOPS 判斷，要做嗎？
