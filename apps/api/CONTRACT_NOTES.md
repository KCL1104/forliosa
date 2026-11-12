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

> 2026-11-12 第二批決定已改寫本節：預設 `commercial`；證交所網站與 MIS 在任何模式都不使用；`sources` 改為顯名聲明格式。
> 細節見下方「2026-11-12 第二批」。

| | `commercial`（**預設**） | `personal`（明確開啟） |
|---|---|---|
| 可用來源 | 只用可商用資料：證交所／櫃買 OpenAPI、集保開放資料、shioaji-data 官方檔，以及由它們建立的自建存檔 | 同左，另外示範資料補缺；`MARKET_DATA_PROVIDERS` 明確列出 `finmind` 才建立 FinMind（標「（非商用）」） |
| 示範資料 | **從不使用**（demo provider 只提供商品名稱清單）；資料不足時回空並在 `notes` 說明 | 補缺 |
| 證交所網站（T86、MI_QFIIS…）、MIS、櫃買網站、MOPS 網站 | **不使用**（已移除；舊存檔的 `twse-web`／`twse-mis` 資料列也不讀） | **不使用** |
| 盤中走勢 `/intraday` | `points: []`＋`notes` | 同左 |
| 新聞 `/news` | 官方公告（重大訊息、證交所新聞） | 同左，FinMind 開啟時另加媒體標題（非商用） |
| 上市股票三大法人、外資持股 | 不提供（證交所 OpenAPI 沒有個股資料），`chips.notes` 說明 | 同左（FinMind 開啟時可回補） |

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
| `chips` | 多 `symbol`、`notes`；`range` 可用 `1M`、`3M`、`6M`、`1Y`。法人單位張（股數 ÷ 1000，保留小數）；外資持股 `pct` 是比率（0.2949）。**上櫃**股票的法人與外資持股來自櫃買 OpenAPI（`tpex_3insti_daily_trading`、`tpex_3insti_qfii`，每日存檔）；**上市**股票沒有（`notes` 說明）。`major_holders.buckets` 是集保 15 個持股分級（另有 `label`，例如「1,000 張以上」）；`pct` 是比率。集保只能下載當週，所以從開始存檔那週起才有資料 |
| `financials` | 多 `symbol`、`period`、`notes`。來源是 shioaji-data 官方季報（2023Q1 起，單季數字，千元）；若存檔中有更新一季的 OpenAPI 財報（`t187ap06` 是**年初至今累計數**），以「本季累計 − 上季累計」換成單季，現金流量為 `null`。`net_income` 是歸屬母公司業主淨利；`free_cash_flow` = 營業 + 投資活動現金流量（OpenAPI／shioaji-data 沒有資本支出科目）。`annual` 只列四季齊全的年度，EPS 用第四季的全年累計 EPS |
| `events` | 每筆多 `sources`、`estimated`、`period`；由新到舊排序（含未來）。範圍：過去 365 天到未來 120 天；`earnings`／`revenue_release`／`investor_conference` 用**實際日期**（見「2026-11-12 第二批」），只有查不到時才用法定期限（季報 5/15、8/14、11/14、3/31；營收每月 10 日；`estimated: true`，前後 60–90 天）。`mine`：未來的除權息／發放 = 目前持有；過去的 = 該日有記股利交易（`amount_estimate` 為實際入帳金額）；其他事件 = 目前持有。除息金額未公告時 `detail` 為「金額尚未公告」 |
| `news` | 每筆多 `sources`、`category`。**官方公告**：該公司的重大訊息與點名該公司的證交所新聞（最近 90 天，最多 30 筆），`source: "公告"`；FinMind 媒體標題只在 personal 明確開啟時附加（`category: "media"`） |
| `position` | 多 `symbol`、`currency`、`as_of`、`sources`、`is_demo`。金額為台幣，`avg_cost` 為原幣。`realized_pnl` 含交易與減資退款；`dividends_received` 已扣二代健保。`markers` 依交易日排序；`stock_dividend` 的 `quantity` 是實際配發股數。**目前股數為 0 一律回 `null`**（即使有已實現損益，見待確認 11） |
| `why` | 多 `symbol`、`sources`。規則：漲跌停 > 漲跌 ≥ 3%（對參考價）、量 ≥ 20 日均量 2 倍、除權息日、處置／注意、當天重大訊息主旨含「財務報告／財報／自結損益」或「營收」。`reasons[].kind` 為 `limit_up`、`limit_down`、`price_move`、`volume`、`ex_dividend`、`disposition`、`attention`、`earnings`、`revenue_release`。最新報價不是今天時文字用日期（「11/11 上漲 3.5%」）。`headline` = 名稱 + 前兩個理由 |
| `watchlist` | 每筆多 `sparkline_interval`（目前一律 `"1d"`：最近 20 個收盤；`"1m"` 保留給日後的授權盤中來源）、`sources`、`is_demo`；`quote` 可能為 `null`。`sparkline[].t` 在 `1m` 是 `"09:01"`，在 `1d` 是日期。`POST` 新增回 201、已在清單回 200（冪等）；找不到商品 422 `unknown_symbol`；最多 200 檔。`DELETE` 不在清單回 404 |
| `/portfolio/upcoming` | 多 `account_id` 參數，每筆多 `is_demo`、`sources`。`days` 1–90。`amount_estimate` = 目前股數 × 每股現金股利（台幣、未扣二代健保）；發放日已過除息日時，若已記股利交易就用交易金額；除息金額未公告時為 `null`、標題加「（金額未公告）」。`recurring`（定期定額扣款）見「2026-11-12 第二批」 |

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
- **草稿**：股數 = floor(金額 ÷ 最近收盤價)（含零股），手續費依帳戶設定另計（零股最低 1 元）、買進免稅；回應
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
| 股利歷史 | `/dividends` 只有存檔的除權息預告（陣列型回應沒有 `notes`，可能是 `[]`） |
| 績效 | 持股期間沒有每天的真實收盤價時 `series: []`＋`notes`；存檔足夠後從第一個完整存檔日（當作基準收盤，`twr_index` 1.0）開始，`notes` 說明起點 |
| 美股 | 沒有報價（`/quote` 404、`Holding.price: null` 以成本計值、`is_demo: false`）、績效空＋`notes` |
| USD/TWD 匯率 | 沒有可商用來源時固定 31.5（待確認 17） |
| 基準 `^TAIEXTR` | `benchmark.twr: null`＋`notes` |
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
9. ~~**MIS 非官方端點**~~：已移除（2026-11-12）。要盤中走勢需購買證交所延遲（約 NT$30,000／月）或即時行情授權。
10. **shioaji-data AI 研究資料**（簡介、產業鏈、題材）授權待定：commercial 下 `GET /instruments/{symbol}` 的 `summary`、`chain_stage`、`themes` 不回（`null`／`[]`），personal 照樣顯示並標示來源。
11. ~~**`position` 已出清的股票**~~：已決定（2026-11-12）：`position` 維持 `null`，出清的回合與買賣點改由
    `GET /portfolio/closed` 與 `GET /instruments/{symbol}/position/history` 提供。
12. ~~**commercial 模式的歷史資料**~~：已決定（2026-11-12）：commercial 從不使用示範資料，存檔不足時回空並在 `notes` 說「資料累積中」。
13. **上市股票三大法人**：證交所 OpenAPI 沒有個股資料（只有櫃買有），上市股票的法人與外資持股是空的；證交所網站 T86 不可程式下載。
    合法路線：Data E-Shop「三大法人買賣超檔」外部使用（約 NT$3,000／月，待確認）或書面同意（詢問信草稿見 `docs/research/data-sources-licensing.md` §1.9）。
14. **新聞來源**：目前只有官方公告（重大訊息、證交所新聞）。媒體新聞需要授權（中央社等，需詢價）。
15. ~~**定期定額**~~：已實作（2026-11-12）。待確認：扣款金額是否含手續費（目前股數 = floor(金額 ÷ 收盤價)，手續費另計）。
16. ~~**財報公布日**~~：已實作（2026-11-12），實際日期來自重大訊息與月營收資料集；查不到才用法定期限（`estimated: true`）。
17. **美股基本面（SEC EDGAR）與匯率（央行／臺銀開放資料）**：研究判定可商用，但**尚未加入**，等產品負責人決定
    （EDGAR 需在 User-Agent 寫聯絡信箱；匯率資料集要先確認仍每日更新）。在那之前美股沒有價格、USD/TWD 沒有來源時固定 31.5。
18. **月營收資料集是否逐日更新**：`t187ap05_L`／`mopsfin_t187ap05_O` 的「出表日期」在 2026-11-12 是 1151111（申報期限之後）。
    若它在每月 1–10 日逐日更新，「第一次看到的日期」就是實際公布日（誤差一天內）；若只在期限後產生一次，營收公布日會晚於實際。
    12 月初要觀察一次。
19. **重大訊息的連結**：OpenAPI 的重大訊息沒有單則網址，`/news` 的 `url` 先指向公開資訊觀測站重大訊息查詢頁
    （`https://mops.twse.com.tw/mops/#/web/t05st01`）。這個環境連不到 MOPS，網址格式沒能驗證。

## AI（M4，2026-11-12）

程式在 `src/forliosa/ai/`（`keypool`、`tools`、`prompts`、`chat`、`store`、`scope`、`grounding`、`retention`、`suggestions`、
`why`、`smoke`）與 `api/routes/ai.py`；資料表 `ai_threads`、`ai_messages`、`ai_drafts`、`ai_usage`、`ai_why_cache`
（migration `0004_ai_threads_usage`；金鑰槽與保存期限的欄位、索引在 `0005_ai_key_slots_retention`）。合約見
[`docs/api-contract.md`](../../docs/api-contract.md)「AI（M4）」。

### 設定（環境變數）

| 變數 | 預設 | 說明 |
|---|---|---|
| `CLAUDE_API_KEY_1`、`_2`、`_3`…（大小寫不拘，例如 `Claude_API_KEY_1`） | — | API 金鑰；**編號就是金鑰槽（slot）**，每把放在各自的 workspace（各有自己的速率限制與花費上限）。都沒有時用 `ANTHROPIC_API_KEY`（slot 0）。也會讀工作目錄的 `.env`（環境變數優先）。日誌與回應只出現槽號（`#1`），從不出現金鑰 |
| `AI_KEY_<n>_MONTHLY_BUDGET_USD`（大小寫不拘） | 空（不限） | 第 n 槽每月（**UTC 月**，與 Anthropic 帳單同）估計花費上限；達到後該槽不再使用，釘在它上面的對話搬到別槽。估計值來自 `ai_usage.cost_usd`（`ai/pricing.py`），建議設得比 Console 的 workspace 花費上限低一點。0／空白＝不限 |
| `AI_KEY_STICKY_WAIT_SECONDS` | 5 | 對話釘住的槽在這幾秒內會恢復（例如 `retry-after: 2`）就等它；更久就搬到別槽 |
| `AI_KEY_COOLDOWN_SECONDS`、`AI_REQUEST_TIMEOUT_SECONDS` | 60、120 | 沒有 `retry-after` 時的冷卻秒數（視為「猜測」，全部槽都在冷卻時仍可試一次） |
| `AI_DEV_DUMMY_KEY` | `false` | 沒有金鑰時送一個占位字串，給會自動注入真金鑰的 proxy 用 |
| `AI_MODEL` | `claude-haiku-5-5` | 產品負責人指定；`AI_MODEL_CHAT`／`AI_MODEL_WHY`／`AI_MODEL_IMPORT`／`AI_MODEL_REPORT` 可個別覆寫 |
| `AI_EFFORT_CHAT`、`AI_EFFORT_WHY` | `low` | `output_config.effort`（Haiku 5.5 預設 medium，這裡明確設 low） |
| `AI_MAX_TOKENS_CHAT`、`AI_MAX_TOOL_ROUNDS` | 8000、8 | 每次呼叫的輸出上限、每輪最多幾次模型呼叫 |
| `AI_DAILY_MESSAGE_LIMIT` | 50 | 每人每天（台北日）提問數，0＝不限（產品負責人確認） |
| `AI_MONTHLY_TOKEN_BUDGET` | 3,000,000 | 每人每月（台北月）計費 token，0＝不限（計法見下；產品負責人確認） |
| `AI_THREAD_MAX_CONTEXT_TOKENS` | 90,000 | 一段對話的提示超過這個大小就要求開新對話（Haiku 5.5 提示超過 10 萬 token 價格變 5 倍） |
| `AI_WEB_SEARCH`、`AI_WEB_SEARCH_MAX_USES` | `true`、3 | 每輪最多 3 次搜尋 |
| `AI_WEB_SEARCH_ALLOWED_DOMAINS` | 空（**不限網域**，產品負責人決定） | 逗號分隔；`recommended`＝內建的台灣財經媒體＋官方網域清單，`official`＝只有官方。預設由模型自己判斷何時搜尋、用哪些來源（只限財經資訊，見「範圍」） |
| `AI_WEB_FETCH`、`AI_WEB_FETCH_ALLOWED_DOMAINS` | `true`、`official` | 只讀官方網域（證交所、櫃買、集保、期交所、金管會、央行、主計總處…）；`*` 不限 |
| `AI_WEB_DYNAMIC_FILTERING` | `false` | `true` 時用網頁工具的動態過濾（code execution）；預設直接呼叫，延遲較低、可零資料保留 |
| `AI_EAGER_TOOL_STREAMING` | `false` | 工具參數很短（幾十個 token），伺服器端驗證比提早串流划算；要時可打開 |
| `AI_WHY_ENABLED`、`AI_WHY_BLOCKING` | `true`、`false` | 見下方「為什麼漲跌」（預設開啟，產品負責人決定） |
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
- **工具**：14 個 client tools，全部 `strict: true`、`additionalProperties: false`、沒有使用者 id 欄位（伺服器帶入登入者）；可選參數合計 15
  個（上限 24）。結果是精簡 JSON（例如 K 線只給統計與最多 30 個取樣點、籌碼只給最近 10 日與區間合計），保留 `as_of`、`is_demo`、`sources`。
  其他使用者的帳戶 id 會回錯誤，不會被當成篩選條件。伺服器工具：`web_search_20260318`（`user_location` 台北／TW、`max_uses` 3、預設不限網域）、
  `web_fetch_20260318`（只限官方網域、`max_uses` 2、`max_content_tokens` 8000、開啟引用）。
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
- **建議問題** `GET /ai/suggestions`：規則與前端離線版相同（`apps/web/src/ai/suggestions.ts`），不呼叫模型。
- **Live smoke**：`uv run python -m forliosa.ai.smoke`（需要金鑰；沒有示範使用者會先 seed）：一題用工具的持股問題、一題需要網路搜尋的
  台積電問題，印出用量、估計費用、「無來源」標記與每個金鑰槽的狀態。

### 實測費用（產品負責人 2026-11-12 live smoke，`claude-haiku-5-5`）

| 題目 | 輸入 | 快取寫入 | 快取讀取 | 輸出 | 估計費用 |
|---|---:|---:|---:|---:|---:|
| 1. 我目前有哪些持股？（工具） | 4 | 9,511 | 7,837 | 878 | 約 US$0.00171 |
| 2. 台積電今天的新聞（1 次網路搜尋） | 4 | 7,980 | 15,500 | 1,542 | 約 US$0.01192（其中約 US$0.01 是搜尋費） |

提示快取有效（第二次呼叫起大部分是快取讀取）。同一次 smoke 發現兩件事，已處理：預設設定下兩題都在送出前被 400 拒絕
（「…not allowed to use tool web_fetch_20260318」）→ 上面的「被拒絕的伺服器工具」；搜尋題的回答出現沒有引用的「董事會批准投資 Anthropic／OpenAI」
→ 上面的「有根據才寫」。

### AI 待產品負責人確認

1. ~~額度數字~~：已確認（2026-11-12）每天 50 題、每月 300 萬計費 token。
2. ~~網路搜尋來源~~：已決定不限網域、由模型判斷（只限財經資訊）。待確認：`web_fetch` 仍只限官方網域（讀全文較貴、轉載風險較高），要不要也放寬？
3. ~~為什麼漲跌 AI 句~~：已決定預設開啟。
4. ~~對話保存期限~~：已決定 30 天。待確認：要不要在設定頁讓使用者自己刪除全部 AI 對話（目前只能一段一段刪）？
5. ~~免責聲明~~：已決定由前端固定顯示（`done.disclaimer`／`/ai/usage.disclaimer`），前端需要改為顯示這行字。
6. **金鑰槽的 workspace 驗證**：目前假設三把金鑰各在不同 workspace（換槽一律用摘要）。`/ai/admin/keys` 會顯示每槽回報的 `workspace_id`，
   請確認三個值不同；若某兩把其實在同一個 workspace，之後可以讓它們之間換槽時不用摘要（目前沒做）。
7. **每槽預算是估計值**：依 `ai/pricing.py` 的價目估算，與實際帳單可能有出入；建議 Console 的 workspace 花費上限設為真正的硬上限，
   `AI_KEY_<n>_MONTHLY_BUDGET_USD` 設低一點作為提早換槽的門檻。
8. **「無來源」標記是啟發式**：可能漏標（沒有典型動詞的敘述）或誤標（用工具資料寫的公告句子）；需要看實際對話調整字詞。
