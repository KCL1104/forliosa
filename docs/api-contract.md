# API 介面合約（v1 草稿）

前端（`apps/web`）與後端（`apps/api`）共用的介面定義。M1、M2 的端點在前半部；AI（M4）與分享（M5：Discord 登入、授權唯讀查看、親友群組）
在後面的章節，匯入（M3）之後補上。
後端完成後會以 FastAPI 自動產生的 OpenAPI（`/api/v1/openapi.json`）為準，這份文件是開發初期的共同約定。
後端實作與本文件的差異（新增欄位、可為 null 的欄位、各交易類型的欄位用法）記錄在 [`apps/api/CONTRACT_NOTES.md`](../apps/api/CONTRACT_NOTES.md)。

## 通用規則

- 前綴：`/api/v1`
- 格式：JSON，欄位使用 `snake_case`。
- 日期：`YYYY-MM-DD`（台北時區的交易日）；時間戳：ISO 8601 含時區（例如 `2026-11-11T13:30:00+08:00`）。
- 數字：一律用 JSON number。
  - 金額：四捨五入到小數 2 位。
  - 價格：最多 4 位小數。
  - 比率：小數表示，`0.0124` 代表 1.24%。
- 金額欄位若沒有特別標示幣別，都是**新台幣（TWD）**。
- 商品代號 `symbol`：台股上市 `2330.TW`、上櫃 `6488.TWO`、美股 `AAPL`。`code` 是不含後綴的代號（`2330`）。
- 認證：httpOnly session cookie（`forliosa_session`）。正式登入用 Discord OAuth；開發環境另提供 `POST /auth/dev-login`（見「分享（M5）」→「登入」）。
- CSRF：非 `GET`／`HEAD`／`OPTIONS` 的請求若帶 `Origin`，必須在 `CORS_ORIGINS` 內，否則 403 `forbidden`。
- 唯讀查看：請求帶 `X-Forliosa-View-As: <delegation_id>` 時以授權者身分讀取（路由白名單，預設拒絕；見「分享（M5）」→「授權唯讀查看」）。
- 錯誤格式：HTTP 4xx/5xx，body 為 `{"error": {"code": "not_found", "message": "找不到商品"}}`。
- 分頁：`?limit=50&cursor=...`，回應 `{"items": [...], "next_cursor": "..." | null}`。
- 示範資料：任何含有模擬數據的回應都帶 `"is_demo": true`，前端必須顯示「示範資料」標示。

## 認證與使用者

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/auth/providers` | 不需登入：可用的登入方式（見「分享（M5）」） |
| GET | `/auth/discord/start`、`/auth/discord/callback` | Discord OAuth（見「分享（M5）」→「登入」） |
| POST | `/auth/dev-login` | body `{"email": "...", "display_name": "..."}`；僅在 `FORLIOSA_ENV=dev` 時啟用；設定 cookie，回傳 `User` |
| POST | `/auth/logout` | 清除 session |
| GET | `/me` | 回傳 `User`；未登入回 401 |
| PATCH | `/me` | `{"display_name"}`（1–30 字）→ `User` |
| PATCH | `/me/preferences` | body 為 `Preferences` 的部分欄位 |

```json
// User
{
  "id": "usr_01J...",
  "email": "demo@forliosa.local",
  "display_name": "示範使用者",
  "avatar_url": null,               // Discord 頭像網址（M5），可為 null
  "preferences": {
    "color_convention": "tw",       // "tw" 紅漲綠跌 | "us" 綠漲紅跌
    "theme": "system",              // "light" | "dark" | "system"
    "quantity_unit": "lot",         // "lot" 以張顯示（X 張＋Y 股）| "share" 以股顯示
    "privacy_mode": false,          // true 時前端遮蔽金額與股數
    "cost_method": "average",       // "average" 移動平均 | "fifo"
    "benchmark": "0050.TW"          // 任何商品代號，或 "^TAIEXTR"（發行量加權股價報酬指數）、"^TPEXTR"（櫃買報酬指數）
  }
}
```

## 券商帳戶

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/accounts` | `Account[]` |
| POST | `/accounts` | 建立 |
| PATCH | `/accounts/{id}` | 更新 |
| DELETE | `/accounts/{id}` | 刪除（連同交易、自動入帳的股利與這個帳戶的定期定額；不能復原）。前端要輸入帳戶名稱才送出 |

**「只記持股」已取消（2026-11-14，產品負責人決定：像 Google 財經，每一筆買進都有日期）**：帳戶沒有 `tracking_mode` 了，每個帳戶都是逐筆記交易；
`GET`／`PUT /accounts/{id}/holdings` 已移除（404）。舊的快照由 migration `0018` 轉成快照日的買進（見下方「取消「只記持股」、查某一天的收盤價」）。
`POST`／`PATCH /accounts` 的 body 仍容許舊分頁送來的 `tracking_mode`：`"transactions"` 忽略；`"holdings"` 回 422，
`{"error": {"code": "tracking_mode_removed", "message": "「只記持股」已經取消，每一筆買進都要記日期。"}}`。

```json
// Account
{
  "id": "acc_01J...",
  "name": "永豐－一般",
  "broker": "永豐金證券",
  "currency": "TWD",                // "TWD" | "USD"
  "fee_rate": 0.001425,
  "fee_discount": 0.28,             // 2.8 折
  "min_fee": 20,
  "min_fee_odd_lot": 1,
  "created_at": "2026-11-11T10:00:00+08:00"   // 2026-11-14 起沒有 tracking_mode
}
```

## 商品與行情

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/instruments/search?q=台積` | 用代號或名稱搜尋，回傳 `Instrument[]`（最多 20 筆）。清單有內建商品、證交所／櫃買收盤檔裡的每一檔台股 ETF，以及 SEC〈company_tickers.json〉的美股代號（英文名）；SEC 的美股只有英文查詢搜得到，排在台股之後（代號完全相同的除外）。排序見 `apps/api/CONTRACT_NOTES.md`「2026-11-14 商品清單」 |
| GET | `/instruments/{symbol}` | `InstrumentDetail` |
| GET | `/instruments/{symbol}/quote` | `Quote` |
| GET | `/quotes?symbols=2330.TW,0050.TW` | `Quote[]`（批次） |
| GET | `/instruments/{symbol}/close?date=2026-11-12` | 那一天的官方收盤（記一筆買進時價格欄下的「那天收盤 1,085」）：`{"symbol": "2330.TW", "date": "2026-11-12", "close": 1085.0, "currency": "TWD"}`。只讀自建存檔（證交所／櫃買的收盤），**不讀 Yahoo Finance 的歷史回補**、不即時向上游查；那天沒有收盤（週末、休市、存檔開始以前、美股）時 `close` 是 `null`（仍是 200）。`date` 格式錯或晚於今天（台北）回 422；查不到商品 404（2026-11-14） |
| GET | `/instruments/{symbol}/history?range=1M` | `range`：`5D`、`1M`、`6M`、`YTD`、`1Y`、`5Y`、`MAX`；回傳 `History`。正式環境開了歷史回補（`PRICE_HISTORY_SOURCE=yahoo`）時，存檔開始以前的日線來自 Yahoo Finance：`sources` 會列出，`notes` 有一句說明哪一天以前是它的資料（`apps/api/CONTRACT_NOTES.md`「歷史日線回補」） |
| GET | `/instruments/{symbol}/valuation?range=5Y` | `Valuation`（本益比、股價淨值比河流圖用） |
| GET | `/instruments/{symbol}/revenue` | `MonthlyRevenue[]`（由舊到新） |
| GET | `/instruments/{symbol}/dividends` | `DividendRecord[]`（由新到舊） |
| GET | `/stream/quotes?symbols=...` | SSE，事件名 `quote`，data 為 `Quote` |

```json
// Instrument
{
  "symbol": "2330.TW",
  "code": "2330",
  "name": "台積電",
  "market": "TWSE",          // "TWSE" | "TPEX" | "US"
  "type": "stock",           // "stock" | "etf"
  "currency": "TWD",
  "industry": "半導體業",    // 可為 null（SEC 代號表的美股沒有）
  "has_quote": true          // false：目前的資料政策沒有這個市場的報價（商用模式的美股），搜尋結果標「沒有報價」
}

// InstrumentDetail = Instrument + 
{
  "summary": "全球最大的專業積體電路製造服務公司……",   // 可為 null
  "chain_stage": "晶圓製造",                           // 可為 null
  "themes": ["CoWoS", "AI 伺服器"],
  "shares_outstanding": 25932666666,
  "market_cap": 28000000000000,
  "data_sources": ["shioaji-data（政府資料開放授權條款第 1 版）"]
}

// Quote
{
  "symbol": "2330.TW",
  "price": 1085.0,
  "prev_close": 1070.0,
  "change": 15.0,
  "change_pct": 0.0140,
  "open": 1072.0,
  "high": 1090.0,
  "low": 1068.0,
  "volume": 32105000,        // 股數
  "as_of": "2026-11-11T13:30:00+08:00",
  "is_realtime": false,
  "is_demo": false,
  "source": "shioaji-data"
}

// History
{
  "symbol": "2330.TW",
  "interval": "1d",
  "candles": [{"t": "2026-11-10", "o": 1060, "h": 1075, "l": 1055, "c": 1070, "v": 28000000}],
  "is_demo": true
}

// Valuation：前端依 eps_ttm × 倍數 畫本益比河流圖；bvps × 倍數 畫股價淨值比河流圖
{
  "symbol": "2330.TW",
  "per_multiples": [12, 16, 20, 24, 28],
  "pbr_multiples": [3, 4, 5, 6, 7],
  "series": [
    {"t": "2026-11-10", "close": 1070, "eps_ttm": 52.3, "bvps": 190.1, "per": 20.46, "pbr": 5.63, "dividend_yield": 0.0168}
  ],
  "current": {"per": 20.7, "pbr": 5.7, "dividend_yield": 0.0166, "per_percentile_5y": 0.62},
  "is_demo": true
}

// MonthlyRevenue（單位：新台幣千元，與公開資訊觀測站一致）
{"period": "2026-10", "revenue": 330000000, "yoy_pct": 0.21, "mom_pct": 0.05, "ytd": 3100000000, "ytd_yoy_pct": 0.32}

// DividendRecord（2026-11-12 起多 status、progress、board_date、meeting_date、cash_sources、sources；見下方「第三批」）
{"year": 2026, "period": "2026Q2", "cash_dividend": 5.0, "stock_dividend": 0, "ex_dividend_date": "2026-12-11", "payment_date": "2027-01-08",
 "status": "announced", "progress": "董事會決議", "board_date": "2026-08-11", "meeting_date": null,
 "cash_sources": {"earnings": 5.0, "legal_reserve": 0, "capital_surplus": 0}, "sources": ["臺灣證券交易所〈上市股票除權除息預告表〉（2026），依政府資料開放授權條款第 1 版"]}
```

## 交易

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/transactions?account_id=&symbol=&type=&from=&to=&limit=&cursor=` | 分頁，由新到舊 |
| POST | `/transactions` | 建立；買賣的 `fee`、`tax` 未提供時是 0（2026-11-14 起不自動算手續費與證交稅）；股利的 `tax`（美股預扣）、`health_insurance` 未提供時自動計算 |
| PATCH | `/transactions/{id}` | 更新（自動入帳的股利改過後變成 `auto_edited`，見下方「股利自動入帳」） |
| DELETE | `/transactions/{id}` | 刪除（自動入帳的股利刪除後不會再自動產生） |
| POST | `/transactions/preview` | 預估稅費，body 同建立，回傳 `TradePreview` |

```json
// Transaction
{
  "id": "txn_01J...",
  "account_id": "acc_01J...",
  "symbol": "2330.TW",            // 現金類交易為 null
  "type": "buy",
  // "buy" | "sell" | "cash_dividend" | "stock_dividend" | "split" | "capital_reduction"
  // | "deposit" | "withdrawal" | "fee" | "tax" | "interest"
  "trade_date": "2026-11-10",
  "quantity": 1000,               // 股數；split 為「每 1 股變成幾股」；capital_reduction 為「每 1 股減少幾股」；現金類為 null
  "price": 1070.0,                // buy/sell 成交價；stock_dividend 為每股配股「元」；cash_dividend 為每股現金股利；現金類與 split 為 null
  "amount": 1070000,              // 成交金額或現金金額（交易幣別）
  "fee": 426,                     // 1,070,000 × 0.1425% × 0.28 = 426.93，無條件捨去
  "tax": 0,
  "health_insurance": 0,          // 二代健保補充保費（現金股利）
  "currency": "TWD",
  "is_day_trade": false,
  "note": "",
  "source": "manual",             // "manual" | "import" | "ai_draft" | "auto" | "auto_edited"（見下方「股利自動入帳」）
  "created_at": "2026-11-10T14:00:00+08:00"
}

// TradePreview
{"gross": 1070000, "fee": 0, "tax": 0, "health_insurance": 0, "net_cash": -1070000, "rules": []}
```

### 股利自動入帳（2026-11-12）

產品負責人決定：Forliosa 看不到銀行，不記股利的話，除息日的股價下跌就會變成帳上的虧損，所以台股的現金股利與配股由系統**依規則自動記成交易**
（不是 AI，也不需要使用者確認）。同步時機、略過紀錄、資料涵蓋範圍等實作細節見 [`apps/api/CONTRACT_NOTES.md`](../apps/api/CONTRACT_NOTES.md)「2026-11-12 股利自動入帳」。

`Transaction.source`：

| 值 | 意義 |
|---|---|
| `manual` | 使用者手動輸入 |
| `import` | 對帳單匯入 |
| `ai_draft` | AI 或定期定額草稿，使用者簽名後建立 |
| `auto` | 系統自動入帳的股利（只會是 `cash_dividend` 或 `stock_dividend`）；之後會隨持股與除權息預告自動更新或移除 |
| `auto_edited` | 使用者改過的自動股利；之後系統不再更新、移除它 |

- **對象**：台股上市、上櫃的現金股利與配股，依證交所／櫃買的除權除息預告。金額為 0 或尚未公告的不記（公告後補上）；除息（權）日還沒到的不記
  （當天起才記）；示範資料從不入帳。美股沒有可商用的股利資料，仍由使用者手動記。
- **日期與股數**：`trade_date` 是除息（權）日，所以除息日的股價下跌與股利同一天抵銷；`quantity` 是除息（權）日**前一天收盤**時該帳戶的持股
  （含之前配發的股數）：除息日當天才買的不算，當天賣出的仍算。
- **金額**：與手動記一筆股利的計算相同。現金股利：`price` = 每股現金股利，`amount` = 股數 × 每股（台幣元以下捨去），`health_insurance` 自動估算
  （資本公積發放的部分排除）。配股：`quantity` = 配發股數，`price` = 每股配股（元），`amount` = 不足一股以面額折付的現金。`note` 寫出算法，發放日
  已公告時附上，例如「10,000 股 × 每股 2 元，07/10 發放」（股數是除息前一日的持股）。
- **使用者自己記的優先**：同帳戶、同商品已有 `manual`／`import`／`ai_draft` 的同類股利（現金對現金、配股對配股），日期在除息（權）日當天到
  120 天內，就不產生自動那一筆（已產生的會移除）。一筆紀錄只抵一次除息：對到期間內最近的除息日，有填每股金額（`price`）時優先對同金額的那次；
  日期早於除息日的紀錄不算。刪掉自己的紀錄後，自動那筆會回來。
- **修改**：`PATCH` 一筆 `auto` 交易（改任何欄位）後，回應的 `source` 是 `auto_edited`（body 裡的 `source` 不採用）；之後同步不會覆蓋或移除它，
  也不會為同一次除息再產生一筆。
- **刪除**：`DELETE` 一筆 `auto` 交易照常回 204；之後同一帳戶、同一商品、同一除息（權）日的同類股利**不再自動產生**（刪掉 `auto_edited` 也一樣）。
  目前沒有端點可以列出或恢復；要記回來就自己新增一筆。
- **不能自己建立自動交易**：`POST /transactions`、`PATCH /transactions/{id}` 的 `source` 只接受 `manual`、`import`、`ai_draft`；帶 `auto` 或
  `auto_edited` 回 422 `validation_error`。
- **重算**：交易新增、修改、刪除，以及每天存檔之後，自動股利會依最新的持股與預告新增、更新或移除
  （例如回頭補一筆除息前的買進，股數就跟著變；預告金額更正，金額就跟著變）。重算若會讓原本一致的帳目變得不一致（例如把一筆買進改到除權日之後，
  自動配股跟著變少，但原本配到的股數之後已經賣掉），整個請求回 422 `ledger_inconsistent`，`message` 以「自動入帳的股利依這筆變更重算後帳目不一致：」開頭，
  **什麼都不會寫入**。檢查的是重算後的帳目：除權前補記賣出、刪掉唯一的買進這類讓舊的自動配股失效的變更，會連同自動列一起更新，不會被擋。
- **資料暫時讀不到時**，已入帳的自動股利保持原狀，等下一次同步；不會因此被刪掉。
- **只填每股金額記股利**：股數是那次除息日前一天收盤的持股（不含同一次的自動配股、也不含除息後才買的）。
- **其他端點直接使用這些交易，沒有另外的計算**：帳本（`/portfolio/summary` 的 `dividend_income`、`holdings`、`position`）、績效、出清回合
  （`/portfolio/closed`、`position/history`）、個股事件（過去的除息事件因此標 `mine`）都把它們當一般股利交易。`/portfolio/upcoming` 的
  `dividend_payment` 在除息日已記有現金股利交易時用那筆的金額（自動入帳的股利就記在除息日）。
- **前端**：`auto` 的交易標「自動」；編輯、刪除前說明後果（改過就變成使用者自己的版本、刪除後不會再自動產生）。

## 投資組合

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/portfolio/summary?account_id=` | `PortfolioSummary`（不帶 `account_id` 為全部帳戶） |
| GET | `/portfolio/holdings?account_id=` | `Holding[]` |
| GET | `/portfolio/performance?range=1Y&benchmark=0050.TW&account_id=` | `Performance`；`range`：`1D`、`5D`、`MTD`、`1M`、`3M`、`6M`、`YTD`、`1Y`、`ALL`（`1D`／`5D` 以交易日計，第一點是基準收盤；`MTD` 從上月最後收盤起，M5 新增）；`benchmark` 省略時用使用者偏好，可為任何商品或 `^TAIEXTR` |

```json
// PortfolioSummary
{
  "as_of": "2026-11-11T13:30:00+08:00",
  "market_value": 3284500,
  "cost_basis": 3123000,
  "unrealized_pnl": 161500,
  "unrealized_pnl_pct": 0.0517,
  "realized_pnl": 42000,
  "dividend_income": 38500,       // 已扣二代健保
  "total_pnl": 242000,            // 未實現＋已實現＋股利
  "total_return_pct": 0.0775,
  "day_change": 40320,
  "day_change_pct": 0.0124,
  "allocation": {
    "by_market":   [{"key": "TWSE", "label": "上市", "value": 2500000, "weight": 0.76}],
    "by_industry": [{"key": "半導體業", "label": "半導體業", "value": 1800000, "weight": 0.55}],
    "by_currency": [{"key": "TWD", "label": "新台幣", "value": 2900000, "weight": 0.88}],
    "by_type":     [{"key": "etf", "label": "ETF", "value": 900000, "weight": 0.27}]
  },
  "upcoming_dividends": [{"symbol": "0056.TW", "name": "元大高股息", "ex_dividend_date": "2026-11-20", "cash_dividend": 0.866, "estimated_amount": 8660}],
  "is_demo": true
}

// Holding
{
  "symbol": "2330.TW",
  "code": "2330",
  "name": "台積電",
  "market": "TWSE",
  "type": "stock",
  "currency": "TWD",
  "industry": "半導體業",
  "quantity": 1500,
  "avg_cost": 612.5,              // 原幣，含買進手續費
  "cost_basis": 918750,           // TWD
  "price": 1085.0,                // 原幣
  "prev_close": 1070.0,
  "market_value": 1627500,        // TWD
  "day_change": 22500,            // TWD
  "day_change_pct": 0.0140,
  "unrealized_pnl": 708750,       // TWD
  "unrealized_pnl_pct": 0.7714,
  "weight": 0.4955,
  "account_ids": ["acc_01J..."]
}

// Performance
{
  "range": "1Y",
  "start_date": "2025-11-11",
  "end_date": "2026-11-11",
  "twr": 0.184,
  "xirr": 0.162,
  "max_drawdown": -0.121,
  "volatility": 0.198,            // 年化
  "benchmark": {"symbol": "0050.TW", "name": "元大台灣50", "twr": 0.151},
  "series": [
    {"t": "2025-11-11", "market_value": 2800000, "net_invested": 2700000, "twr_index": 1.0, "benchmark_index": 1.0}
  ],
  "dividends_by_month": [{"month": "2026-07", "amount": 12000}],
  "realized_by_year": [{"year": 2026, "amount": 42000}],
  "is_demo": true
}
```

## 績效計算定義（後端實作依據）

- 投資組合價值 `V_t`：當日收盤後所有持股市值（換算成台幣）；第一版不含現金部位。
- 美股換算成台幣：USD/TWD 一律用中央銀行〈銀行間新臺幣對美元收盤匯率〉（當天或之前最近一個營業日的收盤匯率；見「匯率」）。成本、賣出、股利用各自交易日的匯率，市值用最新匯率。
- 每日報酬：`r_t = (V_t + O_t) / (V_{t-1} + I_t) - 1`
  - `I_t`（流入，視為開盤前發生）：當日買進成本（含手續費）。
  - `O_t`（流出，視為收盤後發生）：當日賣出淨收入（扣手續費與證交稅）、收到的現金股利（扣二代健保）。
  - 分母為 0 時 `r_t = 0`。
- TWR：`∏(1 + r_t) - 1`。
- XIRR：投資人觀點的現金流（買進為負、賣出與股利為正，期末市值為正），以年化內部報酬率求解。
- 最大回撤：以 `twr_index` 計算。
- 價格一律用**未還原**收盤價；股利以交易記錄，避免重複計算。台股股利由系統在除息（權）日自動記錄（見「股利自動入帳」）。

---

## 重新設計新增（2026-11-12）：個股頁、帳本、自選、AI 草稿

依 `PRODUCT.md`、`docs/research/stock-page-research.md` 與帳本方向合約（`apps/web/.impeccable/surfaces/src-pages-ledger-ledgerpage-tsx.md`）。
資料來源政策：**優先可商用來源**（證交所／櫃買 OpenAPI 每日存檔、shioaji-data 官方資料）；FinMind、Yahoo、MIS 只作備援並在 `sources` 標示「非商用」。所有回應帶 `sources: string[]` 與 `as_of`。
後端實作（2026-11-12）：陣列型回應（events、news、watchlist、upcoming）的 `sources` 放在**每一筆**；`as_of` 只在有報價時間意義的回應（overview、position、why、Quote）。`DATA_POLICY=commercial` 時新聞與盤中點為空。各端點的新增欄位（`notes`、`sparkline_interval`、`label` 等）與規則見 [`apps/api/CONTRACT_NOTES.md`](../apps/api/CONTRACT_NOTES.md)「2026-11-12 重新設計」。

### 報價修正
- `Quote` 新增 `reference_price`（參考價）、`limit_up`、`limit_down`。除權息日的 `change`／`change_pct` 以參考價計算（不是昨收）。

### 個股
| 方法 | 路徑 | 回傳 |
|---|---|---|
| GET | `/instruments/{symbol}/overview` | `{open, high, low, prev_close, reference_price, limit_up, limit_down, volume, avg_volume_3m, market_cap, pe, pb, dividend_yield, last_cash_dividend, ex_dividend_date, eps_ttm, high_52w, low_52w, shares_outstanding, status: {attention, disposition, note}, as_of, sources, is_demo}`；欄位缺資料時為 `null`。台股 ETF 另有 `etf_nav`（淨值與同一天的折溢價，見下方「ETF 淨值與折溢價」） |
| GET | `/instruments/{symbol}/intraday` | `{symbol, date, prev_close, reference_price, points: [{t: "09:01", price, volume}], is_partial, sources}`；只有持股與自選會累積盤中點（每 30–60 秒輪詢），其他回 `points: []` |
| GET | `/instruments/{symbol}/chips?range=3M` | `{institutional: [{t, foreign, trust, dealer, total}]（單位：張）, margin: [{t, margin_balance, short_balance}]（張）, foreign_holding_pct: [{t, pct}], major_holders: {as_of, buckets: [{level, holders, shares, pct}]} \| null, sources}`；**上市（TWSE）股票的 `institutional` 任何模式都是 `[]`**；`foreign_holding_pct` 只在名列證交所外資持股前 20 名時有值（多 `foreign_top20`，見「相關股票、關於〈公司〉、上市股票外資持股前 20 名」），其他為 `[]`，`notes` 說明原因（產品負責人 2026-11-12：不寄信給證交所、不買 Data E-Shop；上櫃照常用櫃買 OpenAPI）；融資融券與集保照常 |
| GET | `/instruments/{symbol}/financials?period=quarterly\|annual` | `{periods: ["2026Q2", …], income: {revenue, gross_profit, operating_income, net_income, eps}, balance: {total_assets, total_liabilities, equity}, cashflow: {operating, investing, financing, free_cash_flow}, margins: {gross, operating, net}, sources}`；每個欄位是與 `periods` 等長的陣列，金額單位新台幣千元（美股：美元、公司會計年度，見「美股基本面（SEC EDGAR）」） |
| GET | `/instruments/{symbol}/events?mine=false` | `[{date, type, title, detail, url, mine, amount_estimate}]`；`type`：`ex_dividend`、`dividend_payment`、`earnings`、`revenue_release`、`material_info`、`attention`、`disposition`、`shareholder_meeting`；美股另有 `sec_filing`（`form`：8-K／10-Q／10-K） |
| GET | `/instruments/{symbol}/news` | `[{published_at, title, source, outlet, url, category, date_only, sources}]`：官方公告在前、新聞報導在後（只有標題、媒體、時間、連結；見「新聞報導」） |
| GET | `/instruments/{symbol}/position` | 未持有回 `null`；否則 `{quantity, avg_cost, cost_basis, market_value, unrealized_pnl, unrealized_pnl_pct, realized_pnl, dividends_received, day_change, markers: [{date, type: "buy"\|"sell"\|"dividend"\|"stock_dividend", quantity, price, amount}], upcoming_dividend: {ex_dividend_date, amount_estimate} \| null}` |
| GET | `/instruments/{symbol}/why` | `{show, headline, reasons: [{kind, text}], as_of}`；規則判斷（漲跌 ±3%、成交量 2 倍、漲跌停、注意／處置、除權息日、財報日），M4 前用模板句，之後由 AI 改寫 |

### 自選
| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/watchlist` | `[{symbol, name, quote: Quote, sparkline: [{t, price}]}]`（盤中點；收盤後為當日） |
| POST | `/watchlist` | body `{symbol}` |
| DELETE | `/watchlist/{symbol}` | |

### 帳本
| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/portfolio/upcoming?days=7` | `[{date, type: "ex_dividend"\|"dividend_payment"\|"recurring", symbol, title, amount_estimate}]`（「本週事項」） |

### AI（M4 前為規則版，前端可先用）
- 「買 0050 2 張 52.4」這類記帳指令：前端（或之後的 AI）解析後呼叫 `POST /transactions/preview` 取得草稿，使用者簽名確認後再 `POST /transactions`（帶 `source: "ai_draft"`）。
- 建議問題、對話紀錄、AI 任務：M4 前由前端 mock，端點在 M4 定義。

---

### 第二批（2026-11-12）：出清紀錄、只用可商用資料、定期定額、實際公布日、資料授權
細節與計算規則見 [`apps/api/CONTRACT_NOTES.md`](../apps/api/CONTRACT_NOTES.md)「2026-11-12 第二批」。

- **資料政策**：`DATA_POLICY` 預設 `commercial`，只用可合法商用的資料（證交所／櫃買 OpenAPI、集保開放資料、shioaji-data 官方檔、自建存檔），**從不回示範資料**；存檔不足時回空資料並在 `notes` 說「資料累積中：自 YYYY-MM-DD 起存檔」（`History.notes`、`Valuation.notes`、`Performance.notes`、`chips.notes`、`intraday.notes`）。`/intraday` 目前一律 `points: []`（沒有授權的盤中來源）。
- **`sources` 是顯名聲明**：「提供機關〈資料集名稱〉（年份），依政府資料開放授權條款第 1 版」，前端必須顯示。

| 方法 | 路徑 | 回傳 |
|---|---|---|
| GET | `/portfolio/closed?account_id=` | `[{symbol, name, account_id, currency, opened_at, closed_at, holding_days, total_bought_qty, total_sold_qty, cost_basis, realized_pnl, realized_pnl_pct, dividends_received, fees_and_taxes, sources}]`（一檔可有多個回合：0 股 → 持有 → 0 股；出清的股票不在 holdings） |
| GET | `/instruments/{symbol}/position/history` | `{symbol, rounds: [同上], markers: [{date, type, quantity, price, amount, account_id}], sources}`；未持有也會回（`/instruments/{symbol}/history` 已是日線端點，所以放在 position 底下）。`/position` 未持有仍回 `null` |
| GET | `/recurring?account_id=` | `[{id, account_id, symbol, name, amount, day_of_month: int[], start_date, end_date, active, note, next_date, created_at, updated_at}]` |
| POST | `/recurring` | body `{account_id, symbol, amount (TWD 整數), day_of_month: 1–28 或陣列 [6, 16, 26], start_date?, end_date?, active?, note?}` → 201 |
| GET／PATCH／DELETE | `/recurring/{id}` | PATCH 部分更新（`end_date: null` 清除）；DELETE 204 |
| POST | `/recurring/{id}/draft?date=` | `{plan_id, scheduled_date, date, name, amount, price_as_of, transaction: {account_id, symbol, type: "buy", trade_date, quantity, price, note, source: "ai_draft"}, preview: TradePreview, is_demo, sources}`；`trade_date` = 扣款日（`date`，遇休市順延）；股數 = floor(金額 ÷ 收盤價)（含零股），手續費另計。**收盤價**：扣款日已經過去（補記）用**扣款日當天**的收盤價（`price_as_of` = 扣款日）；今天或之後的扣款用最近收盤價；過去的扣款日沒有真實的收盤價（示範資料不算）時改用最近收盤價，並在 `preview.rules` 說明「沒有 11/5 的收盤價，改用最近收盤價（11/11）估算，請照對帳單修改」。**不建立交易**，使用者簽名後 `POST /transactions` |
| GET | `/meta/attributions` | `{policy, notice: [授權條款第 2、3 點], datasets: [{key, agency, dataset, url, used_for, year, license, license_url, commercial, attribution}], not_used: [...]}`（不需登入） |

- `/portfolio/upcoming` 的 `type: "recurring"`：扣款日遇非交易日順延（證交所休市日），多 `plan_id`、`account_id`、`scheduled_date`；`amount_estimate` 為扣款金額。
- `/instruments/{symbol}/events`：每筆多 `estimated`、`period`；`type` 多 `investor_conference`（法說會，日期是開會當天）。`earnings`／`revenue_release` 用實際日期（重大訊息、月營收資料集第一次出現的日期），查不到才用法定期限並標 `estimated: true`。
- `/instruments/{symbol}/news`：官方公告（重大訊息、證交所新聞），每筆多 `category: "material_info" | "exchange_news" | "media"`，官方公告的 `source` 是 `"公告"`。
  媒體新聞（`category: "media"`）見下方「新聞報導（2026-11-12）」。
- `POST /transactions` 的 `source` 可為 `"ai_draft"`。

### 第三批（2026-11-12）：開放資料 P0——期交所、報酬指數、股利決議、公司基本資料
依 [`docs/research/open-data-inventory.md`](research/open-data-inventory.md)；細節、解析陷阱與存檔排程見
[`apps/api/CONTRACT_NOTES.md`](../apps/api/CONTRACT_NOTES.md)「2026-11-12 第三批」。

- **授權狀態**：每個資料集標 `ogdl` 或 `conditional`。期交所〈期貨每日交易行情〉〈選擇權每日交易行情〉〈每日外幣參考匯率〉〈選擇權大額交易人未沖銷部位資料〉
  等在 data.gov.tw 找不到對應的開放授權資料集，標 `conditional`：**照常存檔，但 `DATA_POLICY=commercial` 下不顯示**，直到
  `TAIFEX_CONDITIONAL_CONFIRMED=true`（預設 `false`，產品負責人取得期交所書面確認後設定）。前端遇到未顯示的部分會拿到空陣列／`null`＋`notes`。
  〈每日外幣參考匯率〉只存檔、不再用來換算（USD/TWD 改用中央銀行，見「匯率」）。

| 方法 | 路徑 | 回傳 |
|---|---|---|
| GET | `/derivatives/overview` | `{as_of, futures: [{code, name, contract_month, regular: {open, high, low, close, change, change_pct, volume, settlement_price, open_interest}, after_hours: {open, high, low, close, change, change_pct, volume}}], put_call_ratio: {date, volume_ratio, oi_ratio, put_volume, call_volume, put_oi, call_oi, oi_ratio_prev} \| null, institutional: {TX: [Position], TXO: [Position＋calls/puts]}, large_traders: {TX: {contract, name, all_months, near_month} \| null, TXO: {contract, name, calls, puts} \| null}, served: {futures, options_large_traders}, notes, sources}`；`futures` 是 TX、MTX、TE、TF 的近月，`after_hours` 是同一交易日的夜盤（前一交易日 15:00 → 當日 05:00）；`Position` = `{investor: "dealers"\|"trust"\|"foreign", investor_name, oi_net, oi_net_change, oi_long, oi_short, oi_net_value_k, net_volume}`（口數；金額千元）；大額交易人區塊 = `{top5_buy, top5_sell, top10_buy, top10_sell, top5_net, top10_net, market_oi, specific: {top5_net, top10_net}}` |
| GET | `/derivatives/futures/{code}/history?range=3M` | `{code, name, range, series: [{t, contract_month, open, high, low, close, change, change_pct, volume, settlement_price, open_interest, after_hours}], notes, sources}`；近月連續（到期換月時 `contract_month` 改變）；`range`：`1M`、`3M`、`6M`、`1Y`、`MAX` |

- `/instruments/{symbol}/dividends`：`DividendRecord` 多 `status`（`"announced"` 有除權息日｜`"resolved"` 只有董事會／股東會決議）、`progress`、`board_date`、
  `meeting_date`、`cash_sources: {earnings, legal_reserve, capital_surplus} | null`（資本公積發放的現金一般不屬股利所得）、`sources`。上市公司的決議來自證交所
  〈上市公司股利分派情形〉；上櫃公司沒有開放來源（櫃買資料集 2021-08 停更），只有除權息預告。
  `"resolved"` 的決議只列董事會日期（沒有時用股東會日期）在最近 180 天內的（2026-11-14）：更舊而沒有對上除權息預告的，多半在存檔開始前就已除權息。
- `/instruments/{symbol}/events`：`type` 多 `dividend_resolution`（日期是董事會日）。
- `/instruments/{symbol}/overview`、`/instruments/{symbol}`：多 `listed_date`；`market_cap`、`shares_outstanding` 改用證交所／櫃買〈公司基本資料〉的已發行普通股數（市值 = 股數 × 最新收盤）。
- `/portfolio/performance`：`benchmark` 可用 `^TAIEXTR`（自建存檔：證交所 `MI_INDEX`／`MFI94U`）與 `^TPEXTR`（櫃買 `tpex_reward_index`），`benchmark.twr` 不再是 `null`（存檔自 2026-11-02 起）；有美股時 `notes` 說明 USD/TWD 的來源（見「匯率」）。
- `Quote.reference_price`／`limit_up`／`limit_down`：上櫃股票除權息日優先用櫃買〈上櫃股票除權除息計算結果表〉的官方值。
- `/meta/attributions`：每筆多 `license_status`、`license_basis`、`served`、`last_updated`、`last_fetched`；最上層多 `taifex_conditional_confirmed`、
  `conditional[]`（已存檔但未顯示的資料集與原因）、`stale[]`（停更端點與最後資料日期）。`datasets` 仍只列目前顯示的資料集。
- AI：新工具 `get_derivatives_overview`（唯讀、沒有參數、不含使用者資料）。

### 匯率（2026-11-12）：中央銀行〈銀行間新臺幣對美元收盤匯率〉
產品負責人決定（[`docs/handoff.md`](handoff.md) §3.3）；細節見 [`apps/api/CONTRACT_NOTES.md`](../apps/api/CONTRACT_NOTES.md)「2026-11-12 匯率改用中央銀行開放資料」。
沒有新端點，也沒有改欄位，只換了 USD/TWD 的來源與說明文字。

- **來源**：中央銀行〈銀行間新臺幣對美元收盤匯率〉（data.gov.tw 7232，政府資料開放授權條款第 1 版），每個營業日下午公布，歷史從 2008-01-02 起，
  自建存檔每天 21:40 更新。任何 `DATA_POLICY` 都用它；取代原本的固定 31.5 與期交所〈每日外幣參考匯率〉（兩者數字相同，但期交所的授權仍是「有條件」）。
- **換算規則**：某天的匯率 = 當天或之前最近一個營業日的收盤匯率（假日沿用前一個營業日）；2008-01-02 以前的交易用 2008-01-02 的匯率。
  只有在完全沒有存檔時才用固定 31.5，並在 `notes` 說明；存檔停更時沿用最後一筆匯率（加下面的停更說明），不會退回 31.5。
- `Performance.notes`（有美股時）：「USD/TWD 匯率：中央銀行〈銀行間新臺幣對美元收盤匯率〉（2026），依政府資料開放授權條款第 1 版」；
  沒有存檔時「USD/TWD 以固定 31.5 換算：還沒有中央銀行〈銀行間新臺幣對美元收盤匯率〉的存檔」；最新匯率比今天早 14 天以上（含 14 天）時再加
  「USD/TWD 匯率只到 YYYY-MM-DD（匯率），之後的日子沿用這個匯率」。前端照原文顯示（`DataNotes`）。
- `/instruments/{symbol}/position`：美股的 `sources` 多一筆上面的顯名聲明（台幣金額用到匯率）。
- `/meta/attributions`：`datasets` 多 `cbc-opendata/fx`（`agency: "中央銀行"`、`license_status: "ogdl"`、`license_basis: "data.gov.tw 7232"`、
  `last_updated` = 存檔最新的匯率日期）；期交所 `taifex-openapi/fx` 仍在 `conditional[]`，`used_for` 改為「只存檔」。
- AI 工具 `get_portfolio_summary`、`get_holdings`、`get_position`（美股）的 `notes` 多匯率來源與「美股市值以 YYYY-MM-DD 的 USD/TWD X 換算成新台幣」。

### 新聞報導（2026-11-12）：媒體原標題＋媒體＋時間＋原文連結
產品負責人決定（`PRODUCT.md`「相關新聞」與「個股頁補強」第 1、2 項；研究 [`docs/research/news-and-external-sources.md`](research/news-and-external-sources.md)）。
細節見 [`apps/api/CONTRACT_NOTES.md`](../apps/api/CONTRACT_NOTES.md)「2026-11-12 新聞報導」。沒有新端點：`GET /instruments/{symbol}/news` 在官方公告之後加上媒體標題。

```json
[
  {"published_at": "2026-11-11T17:30:00+08:00", "title": "代子公司 TSMC Arizona 公告取得機器設備", "source": "公告",
   "outlet": null, "url": "https://mops.twse.com.tw/mops/#/web/t05st01", "category": "material_info", "date_only": false,
   "sources": ["臺灣證券交易所〈上市公司每日重大訊息〉（2026），依政府資料開放授權條款第 1 版"]},
  {"published_at": "2026-11-12T15:00:00+08:00", "title": "台積電CPO霸主地位穩了？法人看好2027年EPS估達151元", "source": "GDELT",
   "outlet": "新頭殼", "url": "https://newtalk.tw/news/view/2026-11-12/1070753", "category": "media", "date_only": false,
   "sources": ["The GDELT Project〈GDELT DOC 2.0 新聞索引〉（2026），依 GDELT 使用條款引用：https://www.gdeltproject.org/"]}
]
```

- **順序**：先官方公告（台股；最近 90 天、最多 30 則，新的在前），再新聞報導（最近 30 天、最多 40 則，新的在前）。美股只有新聞報導。
- **美股新聞只收美國與英國媒體的英文報導**（2026-11-14，產品負責人照建議；GDELT 查詢見 `apps/api/CONTRACT_NOTES.md`「2026-11-12 新聞報導」）：外國的轉載
  （印度、澳洲、新加坡的地方報）不列。回應形狀不變。
- **新聞報導**（`category: "media"`）：`title` 是媒體原標題（去掉 GDELT 插入的空白與「| 財經」「- 自由財經」這類重複媒體或版名的尾巴）；
  `outlet` 是媒體名稱（依網域：udn.com 聯合新聞網、money.udn.com 經濟日報、cna.com.tw 中央社…；不認得的顯示網域）；
  `url` 是原文連結（去掉 `utm_*`、`fbclid`、`gclid` 這類追蹤參數；AMP 快取連結換成媒體自己的網址）；`source` 是怎麼找到的：`"GDELT"`、
  `"SearXNG"`（我們自架、只對內的元搜尋，**預設開啟**，2026-11-12 第三輪）、`"AI 搜尋"`（GDELT 與 SearXNG 最近 7 天合計少於 3 則才用）、
  `"Yahoo股市"`（只有 `DATA_POLICY=personal`）、`"FinMind"`（personal 明確開啟）。`source: "SearXNG"` 的 `sources` 是
  `["SearXNG 自架元搜尋（只取標題、媒體、時間與連結）"]`；同一則新聞 GDELT 與 SearXNG 都找到時只列一次（先存到的那個來源）；
  `date_only: true` 表示來源只給日期（顯示日期，不顯示「N 小時前」）。官方公告的 `outlet` 是 `null`、`date_only` 是 `false`。
- **不提供**內文、摘要、og:description、圖片或縮圖；同一則（同網址或幾乎相同的標題）只列一次，原始媒體優先於轉載（Yahoo、LINE TODAY、MSN），
  一般網頁優先於 AMP／手機版（先存到手機版、之後才找到一般網頁時，連結會換成一般網頁）。「同網址」比對時不分 http／https、`www.`／`m.`／`amp.`、追蹤參數、結尾斜線與 AMP 路徑（`/amp/`、`.amp.html`）。
  搜尋引擎的轉址連結（`news.google.com/articles/…`、`bing.com/news/apiclick.aspx…` 等）直接丟掉，不會去解析。
- **前端**：個股頁總覽第三層的「新聞報導」區（先列 3 則，「看更多」再加）：「媒體・N 小時前」，標題連到原文（新視窗，`rel="noopener noreferrer"`）；
  有 `source: "GDELT"` 時，在頁尾的「資料來源與授權」引用 The GDELT Project 並連到 https://www.gdeltproject.org/（使用條款要求；每頁一個頁尾，展開可見）；
  `source: "Yahoo股市"` 要同時顯示「Yahoo股市」與原始媒體。
  總覽的「事件」表（官方公告與接下來的事依日期合成一張表）與事件分頁只放官方公告（`category` 不是 `media`）。
- `/meta/attributions` 多了 `gdelt/doc`（`license_status: "open"`，可商用、需引用），personal 另有 `yahoo-rss/stock`（`license_status: "non_commercial"`）；
  `notice` 多一行 GDELT 條款，commercial 的 `not_used` 多「新聞網站本身」與「Yahoo股市 RSS」兩行。

### 相關股票、關於〈公司〉、上市股票外資持股前 20 名（2026-11-12）
產品負責人決定（`PRODUCT.md`「個股頁補強」第 4、6、7、8 項；規則 [`docs/research/news-and-external-sources.md`](research/news-and-external-sources.md) §8、§9）。
細節見 [`apps/api/CONTRACT_NOTES.md`](../apps/api/CONTRACT_NOTES.md)「2026-11-12 相關股票、公司資料、外資持股前 20 名」。

| 方法 | 路徑 | 回傳 |
|---|---|---|
| GET | `/instruments/{symbol}/related` | `{symbol, items: [RelatedCard]（最多 4 張）, sources, notes}`；美股 `items: []`＋`notes` |
| GET | `/instruments/{symbol}/company` | `CompanyAbout`（台股：證交所／櫃買〈公司基本資料〉；美股：SEC submissions；ETF：〈基金基本資料彙總表〉）＋`description` |

```json
// RelatedCard
{"symbol": "3443.TW", "name": "創意", "reason": "affiliate", "reason_label": "台積電是其法人董事及大股東",
 "close": 1960.0, "change_pct": -0.0126, "as_of": "2026-11-11",
 "sparkline": [{"t": "2026-10-14", "price": 1890.0}], "is_index": false, "notes": [], "is_demo": false}

// CompanyAbout（台股）
{"symbol": "2330.TW", "name": "台灣積體電路製造股份有限公司", "short_name": "台積電", "english_short_name": "TSMC",
 "market": "TWSE", "type": "stock", "industry": "半導體業", "incorporated": "1987-02-21", "years_since_incorporation": 39,
 "listed_date": "1994-09-05", "listing": "上市", "hq": "新竹科學園區", "registered_in": null, "website": "https://www.tsmc.com",
 "paid_in_capital": 259323700670, "chairman": "魏哲家", "president": "總裁: 魏哲家", "auditor": "勤業眾信聯合會計師事務所",
 "transfer_agent": "中國信託商業銀行 代理部", "exchanges": [], "fiscal_year_end": null, "former_names": [], "fund": null,
 "description": {"kind": "wikipedia", "text": "台灣積體電路製造，簡稱台積電……", "label": "節錄", "title": "台積電",
                 "url": "https://zh.wikipedia.org/zh-tw/%E5%8F%B0%E7%A9%8D%E9%9B%BB", "source": "維基百科",
                 "license": "CC BY-SA 4.0", "license_url": "https://creativecommons.org/licenses/by-sa/4.0/deed.zh-hant",
                 "revision_id": 95542651, "updated_at": "2026-11-12T14:35:00+08:00"},
 "data_date": "2026-11-11", "sources": ["臺灣證券交易所〈上市公司基本資料〉（2026），依政府資料開放授權條款第 1 版", "…"], "notes": []}
```

- **相關股票**（只用政府開放資料，規則挑選，不用 AI、不用別人的觀察清單）：
  - `reason`：`benchmark`（使用者的比較基準，`reason_label`「你的比較基準」；基準是指數時 `is_index: true`、「你的比較基準（指數）」，不能點）、
    `constituent`（上櫃且為富櫃五十成分股 → 006201「富櫃五十成分股（櫃買中心公布）」）、`affiliate`（董監事持股餘額明細：上市櫃公司擔任法人董事或大股東，
    「台積電是其法人董事及大股東」「世界的大股東」）、`leader`（同產業市值最大）、`peer`（同產業、市值最接近；其他電子業改用電子類「電子類、市值相近」）、
    `holding`（其他業：使用者自己的持股「你的持股、市值相近」）、`same_index`／`same_type`（ETF 頁：追蹤同一指數、同類型受益人數多）。
  - **不寫「某 ETF 持有本股」**：臺灣50 等成分股清單沒有開放授權（授權詢問信稿：`docs/outreach/etf-holdings-inquiry.md`）。存託憑證（91）不出現。
  - 順序：基準／成分股、關係企業（1 張；雜項產業 2 張）、同業補滿；`sparkline` 是存檔收盤（約 1 個月）；`notes` 有關係企業時寫資料年月。
  - 前端：總覽「相關股票」列（桌機一列 4 格、手機橫向捲動），**少於 2 張就不顯示**。
- **關於〈公司〉**：產業別、成立日期（`years_since_incorporation`＝「成立 N 年」）、上市／上櫃日期、總部（`hq`：從中文地址取縣市，「新竹科學園區」照原文；
  櫃買只有英文地址，對照確定才給，否則 `null`；KY 等外國企業給 `registered_in` 註冊地、`hq` 為 `null`）、網站（https）、實收資本額（元）、
  **董事長、總經理（照官方原文，例如「總裁: 魏哲家」）**、簽證會計師事務所、股務代理（只有名稱）、英文簡稱；`data_date` 是出表日期。
  董事長、總經理每天覆寫、不留歷史，只出現在這個端點：不進 AI 提示或 AI 工具輸出，也不和董監持股、質押合併。
  美股：`industry`（SIC）、`hq`（「Cupertino, CA」；外國公司「Hsinchu, Taiwan」）、`exchanges`、`fiscal_year_end`（「09-26」）、`former_names`。
  ETF：`fund: {fund_type, index_name, custodian, units}`、成立與上市日期。
- **`description`**：`kind: "wikipedia"`＝中文維基百科條目開頭節錄（zh-tw 字形、在句號處截斷、**原文不改寫**），前端標「節錄」並連到條目與 CC BY-SA 4.0；
  `kind: "ai"`＝沒有條目時 AI 只依官方資料（產業、成立與上市日期、總部、實收資本額、最近月營收規模、ESG 產品類別）寫的 2–3 句，`label`「AI 依公開資料整理」，
  外層 `sources` 列出寫這段時用到的每個資料集（公司基本資料，以及有用到時的月營收、ESG 產品與安全），
  不含人名；沒有時 `null`。簡介由 worker 每小時處理追蹤中的股票（維基百科每月更新一次，AI 只在官方資料變動時重寫），第一次看的股票稍後才有。
- **上市股票外資持股**：`GET /instruments/{symbol}/chips` 多 `foreign_top20: {as_of, rank, pct, limit_pct} | null`。上市股票名列證交所
  〈集中市場外資及陸資持股前 20 名彙總表〉（`MI_QFIIS_sort_20`）時，`foreign_holding_pct` 是在榜那些天的持股比、`notes` 說明「證交所只公布前 20 名」；
  不在**最新一份**名單上時維持空陣列＋說明（區間內曾經在榜也一樣，避免把以前的持股比當成現在的）。上市股票的 `notes` 一律說明為什麼沒有三大法人：
  在榜時是不含外資持股那句的版本，再加前 20 名的說明。上市股票的 `institutional` 仍然一律是空的。前端：籌碼分頁「外資持股比」與總覽籌碼小卡的「外資持股」。
- `/meta/attributions`：多 `twse-openapi/foreign_top20`、`twse-openapi/board`、`tpex-openapi/board`、`tpex-openapi/tpex50`、`tdcc-opendata/holders_twse`、
  `tdcc-opendata/holders_tpex`、`twse-openapi/esg_products`、`tpex-openapi/esg_products`、`wikipedia/zh`（`license_status: "open"`，CC BY-SA 4.0）、
  `wikidata/entities`（CC0）；`notice` 多一行維基百科授權。

### ETF 淨值與折溢價（2026-11-12）
產品負責人決定（`PRODUCT.md`「個股頁補強」第 9 項；驗證見 [`docs/research/news-and-external-sources.md`](research/news-and-external-sources.md) §11）。
細節見 [`apps/api/CONTRACT_NOTES.md`](../apps/api/CONTRACT_NOTES.md)「2026-11-12 ETF 淨值與折溢價」。沒有新端點：`GET /instruments/{symbol}/overview` 多 `etf_nav`。

- **來源**：金融監督管理委員會證券期貨局〈證券投資信託基金每日淨值〉（data.gov.tw 11109，政府資料開放授權條款第 1 版；檔案放在投信投顧公會
  `www.sitca.org.tw`），worker 每個交易日 21:40 存檔、08:10 再讀一次；只存「受益憑證代號」是上市櫃 ETF 交易代號的列。收盤價是證交所／櫃買 OpenAPI 的存檔，**從不用示範資料**。
- **折溢價 = 收盤價 ÷ 淨值 − 1，只用同一天**：`premium_date` 是收盤價與淨值都有的最近一天。海外標的的淨值常是前一個營業日的，證交所的收盤檔晚上也可能還是前一天，
  所以最新淨值日（`nav_date`）與最新收盤日（`close_date`）可能不同，兩個都回傳；沒有同一天的資料時 `premium_pct` 為 `null`。
- **歷史**：從開始存檔那天累積（`history_start`），`history` 最多 60 點、由舊到新；不到 20 點時 `notes` 有「淨值資料從 YYYY/MM/DD 開始」，前端滿 20 點才畫走勢。
  `history` 只收同一天有收盤也有淨值的日子，**不一定是連續的交易日**：`history_missing` 列出第一點到最後一點之間沒有資料的交易日（worker 停機等存檔缺口，
  依證交所休市日判斷；檔案只有最新一天，補不回來），前端在那裡把線斷開，標題寫「N 個有資料的交易日（M/D–M/D）」，有缺口時加「中間 K 個交易日沒有資料」。
- **追蹤誤差不提供**：要用標的指數的每日資料，指數沒有開放授權。
- `sources`：區塊裡每個數字的資料集：淨值的顯名，加上收盤價的證交所〈上市個股日成交資訊〉或櫃買〈上櫃股票行情〉（只要回傳了 `close` 就列，沒有同一天的配對時也是）。
- 股票、美股的 `etf_nav` 是 `null`；台股 ETF 一定是物件。**沒有淨值時所有數字欄位都是 `null`（`close`／`close_date` 也是，報價看 overview 本身）**、
  `history`／`history_missing`／`sources` 是 `[]`、`notes` 說明。有淨值時 `close`／`close_date` 是最近一筆存檔的官方收盤（可能和 `nav_date` 不同天）。

```json
// overview.etf_nav（00679B：淨值是前一個營業日的；淨值與 11/12 收盤是 2026-11-12 的真實值，11/11 的收盤 26.58 是示意）
{"nav": 26.4989, "nav_date": "2026-11-11", "currency": "TWD", "fund_name": "元大美國政府20年期(以上)債券基金",
 "close": 26.61, "close_date": "2026-11-12", "premium_pct": 0.003061, "premium_date": "2026-11-11",
 "history": [{"t": "2026-11-11", "nav": 26.4989, "close": 26.58, "premium_pct": 0.003061}],
 "history_start": "2026-11-11", "history_missing": [], "notes": ["淨值資料從 2026/11/11 開始"],
 "sources": ["金融監督管理委員會證券期貨局〈證券投資信託基金每日淨值〉（2026），依政府資料開放授權條款第 1 版",
             "證券櫃檯買賣中心〈上櫃股票行情〉（2026），依政府資料開放授權條款第 1 版"]}
```

- `notes` 的固定文字：「還沒有淨值資料，每個交易日晚上更新」（還沒有任何淨值存檔）、「〈證券投資信託基金每日淨值〉沒有這檔 ETF 的淨值」（期貨信託 ETF、外幣交易線、
  多數上櫃債券 ETF 不在這份資料）、「還沒有同一天的收盤價與淨值，不計算折溢價」、「淨值資料從 YYYY/MM/DD 開始」。
- 有淨值時 `overview.sources` 也多一行上面的顯名聲明；`/meta/attributions` 多 `sfb-opendata/nav`（`license_status: "ogdl"`、`license_basis: "data.gov.tw 11109"`）。
- 前端：總覽與估值分頁的「淨值與折溢價」：淨值、收盤、折溢價（各自的日期）、日期不同時一句說明、滿 20 點的走勢（0 軸是「淨值」）與區間、「逐日數字」、
  追蹤誤差那一句、顯名聲明。折溢價不是價格漲跌：用墨色與「溢價／折價」文字，不用紅綠、不加 ▲▼。
- AI：`get_stock_overview` 對台股 ETF 多 `etf_nav`（最新數字、`history_range` 區間〔`points` 有資料的天數、`from`／`to`、`missing_trading_days` 缺口天數、最高最低〕、
  最近 10 點與「只用同一天、說出日期、點數不是交易日數、沒有追蹤誤差」的 `note`）。

## AI（M4）

後端用 Anthropic Claude（預設 `claude-haiku-5-5`）＋我們自己的工具回答；細節與待決事項見 [`apps/api/CONTRACT_NOTES.md`](../apps/api/CONTRACT_NOTES.md)「AI（M4）」。
規則：AI 只讀**目前登入者**自己的資料（工具由伺服器帶入使用者，模型無法指定別人）；只回答投資理財、台美股、使用者的持股與 Forliosa 用法，其他要求一句話婉拒；數字與事實只來自工具結果或附引用的網路來源；**AI 從不寫入帳本**，記帳一律先產生草稿，使用者簽名後前端才 `POST /transactions`（`source: "ai_draft"`）；**免責聲明由前端固定顯示**在每則 AI 回答下方（文字取 `done.disclaimer` 或 `GET /ai/usage` 的 `disclaimer`，模型不會自己寫）；引用來源必須顯示給使用者，`grounding` 標出的句子要標「無來源」。對話、訊息與草稿在最後活動 30 天後刪除（`AI_RETENTION_DAYS`）；用量紀錄保留但不含內容。

| 方法 | 路徑 | 說明 |
|---|---|---|
| POST | `/ai/chat` | SSE 串流（`text/event-stream`）。body `{"thread_id": "thr_…" \| null, "message": "買 0050 2 張 52.4", "page": {"route": "/stock/2330.TW", "symbol": "2330.TW" \| null}, "privacy": false}`；`thread_id` 省略＝開新對話。選填 `"mode": "deep"`＝**深度搜尋**：這一題多查幾輪網路資料（`web_search` 上限從 3 次提高到 12 次）、寫成一份整理（兩三句結論、最多 8 點、最多 3 個短標題，仍是純文字），算 `Usage.deep_search_cost` 題（預設 5）；只對這一題有效 |
| GET | `/ai/threads?limit=30&cursor=` | `{"items": [ThreadSummary], "next_cursor"}`，最近更新的在前 |
| GET | `/ai/threads/{id}` | `ThreadDetail`（別人的對話回 404） |
| DELETE | `/ai/threads/{id}` | 204；草稿保留 |
| DELETE | `/ai/threads` | 204；刪除自己**全部**的對話與訊息（設定頁「刪除全部 AI 對話」）。規則同上：草稿保留（`thread_id` 改成 `null`），已簽名草稿建立的交易留在帳本；用量紀錄保留。沒有對話也是 204。查看別人的資產時（`X-Forliosa-View-As`）403 `read_only` |
| GET | `/ai/drafts?status=pending` | `DraftCard[]`；`status`：`pending`（預設）、`signed`、`discarded`、`all` |
| PATCH | `/ai/drafts/{id}` | body `{"status": "signed", "transaction_id": "txn_…"}`、`{"status": "discarded"}`，或復原後 `{"status": "pending"}`；回 `DraftCard` |
| GET | `/ai/suggestions?route=/stock/2330.TW&symbol=2330.TW` | `Suggestions`（規則產生，不呼叫模型） |
| GET | `/ai/usage` | `Usage`（含固定的 `disclaimer`） |
| GET | `/ai/briefings/latest` | 每日收盤簡報：最新的一則 `Briefing`，沒有時 `null`（沒打開「每日收盤簡報」的人永遠是 `null`）。查看別人的資產時不提供 |
| GET | `/ai/briefings?limit=14` | 最近的簡報 `Briefing[]`（新的在前，最多 30 則） |
| POST | `/ai/briefings/{id}/read` | 標示看過（204）；別人的或不存在的 404 |
| GET | `/ai/admin/keys` | `KeySlots`（API 金鑰槽狀態，不含金鑰；只在 `FORLIOSA_ENV=dev`／`test` 或 `AI_ADMIN_EMAILS` 列出的帳號，其他人 404） |
| GET | `/instruments/{symbol}/why` | 原有欄位＋`ai`、`citations`、`rule_headline`（見下方；AI 句預設開啟） |

### `POST /ai/chat` 的事件

每個事件是 `event: <名稱>` ＋ `data: <JSON>`。順序：`thread` 一定最先、`done` 一定最後；`error` 之後仍會送 `done`。

| 事件 | data | 說明 |
|---|---|---|
| `thread` | `{"id": "thr_…", "title": "我有哪些持股？", "created": true}` | 新對話時 `created: true` |
| `text` | `{"delta": "台積電今天"}` | 回答文字片段，依序串接；換到下一輪（查完工具）時會先送 `"\n\n"` |
| `tool` | `{"id": "toolu_…", "name": "get_holdings", "status": "running" \| "done" \| "error", "label": "查看持股"}` | 進度細線；`web_search` 的 label 是「搜尋網路：<關鍵字>」，`web_fetch` 是「讀取 <網域>」 |
| `citation` | `{"url": "https://…" \| null, "title": "中央社", "cited_text": "最多 150 字"}` | 網路來源引用（已去重），顯示在回答下方 |
| `draft` | `DraftCard` | `draft_transaction` 產生的草稿卡；按「確認」後前端用 `input` 呼叫 `POST /transactions`，再 `PATCH /ai/drafts/{id}` 標示已簽名 |
| `chart` | `ChartCard` | `draw_chart` 畫出來的圖卡（一則回答最多 3 張）：每條線的點都在裡面，前端照著畫；資料不足沒有畫時不送這個事件（同一份也存在 `ThreadMessage.charts`） |
| `grounding` | `{"items": [GroundingItem]}` | 只在這一輪用了 `web_search`／`web_fetch` 時、最後一個 `text` 之後送：沒有引用又像新聞敘述的句子，前端在該句標「無來源」（同一份也存在 `ThreadMessage.grounding`） |
| `error` | `{"code": "…", "message": "zh-TW 說明"}` | `refusal`（模型拒答；前端應**丟棄這一輪已串流的文字**，改顯示 message）、`ai_busy`、`ai_unavailable`、`ai_unreachable`、`ai_error`、`too_many_steps`、`max_tokens`、`truncated`（文字太長被截斷，已顯示的部分保留）、`internal_error` |
| `done` | `{"thread_id", "turn_id", "model": "claude-haiku-5-5", "stop_reason": "end_turn", "usage": {"input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "web_search_requests", "web_fetch_requests"}, "disclaimer": "AI 回答僅供參考，非投資建議。"}` | `usage` 是這一輪所有模型呼叫的合計；`disclaimer` 由前端固定顯示在回答下方。`stop_reason: "off_topic"`＝明顯離題、沒有呼叫模型就婉拒（`usage` 全為 0，算一則提問） |

串流開始前的錯誤用一般 JSON 錯誤格式：401；422（body 格式）；404 `not_found`（別人的或不存在的 `thread_id`）；409 `thread_too_long`（對話太長，請開新對話）；429 `ai_daily_limit`（今天的提問數已達上限，每天 50 題；深度搜尋而今天剩下的題數不夠時也是這個代碼，訊息是「今天還剩 3 題，深度搜尋一次要 5 題。」，錯誤物件多 `remaining`、`cost`）／`ai_monthly_budget`（本月用量已達上限，每月 300 萬計費 token）；503 `ai_unavailable`（沒有設定 API 金鑰，或所有金鑰都失效／額度用完；`mode: "deep"` 而這個環境沒開網路搜尋時也是）。

後端有多把 API 金鑰（各在自己的 workspace）：每段對話固定用同一把；那把不能用時自動換到別把，並以先前對話的純文字接續（前端不需要處理，`ThreadDetail` 不變）。

```json
// DraftCard
{
  "id": "drf_01J…",
  "status": "pending",               // "pending" | "signed" | "discarded"
  "input": {"account_id": "acc_…", "symbol": "0050.TW", "type": "buy", "trade_date": "2026-11-12",
            "quantity": 2000, "price": 52.4, "amount": null, "currency": "TWD", "is_day_trade": false,
            "note": "", "source": "ai_draft"},        // 直接當 POST /transactions 的 body
  "instrument": {"symbol": "0050.TW", "code": "0050", "name": "元大台灣50", "market": "TWSE", "currency": "TWD"},  // 現金類為 null
  "preview": {"gross": 104800, "fee": 41, "tax": 0, "health_insurance": 0, "net_cash": -104841, "rules": ["…"]},
  "notes": ["沒有寫價格，以 11/12 收盤價 52.35 估算，確認前請改成實際成交價"],
  "account": {"id": "acc_…", "name": "永豐－一般"},
  "transaction_id": null,            // 簽名後的交易 id
  "created_at": "2026-11-12T14:05:00+08:00"
}

// ThreadSummary
{"id": "thr_…", "title": "我有哪些持股？", "created_at": "…", "updated_at": "…", "message_count": 3, "preview": "最新回答的前 80 字"}

// ThreadDetail（messages 依時間排序；一問一答）。使用者的那一則有 `mode`：`"deep"`＝那一題是深度搜尋，其餘是 null
{"id": "thr_…", "title": "…", "model": "claude-haiku-5-5", "created_at": "…", "updated_at": "…",
 "messages": [
   {"id": "12", "turn_id": "trn_…", "role": "user", "text": "台積電今天為什麼漲？", "citations": [], "drafts": [], "tools": [], "error": null, "at": "…"},
   {"id": "15", "turn_id": "trn_…", "role": "ai", "text": "…", "citations": [{"url", "title", "cited_text"}],
    "drafts": [DraftCard], "charts": [ChartCard], "tools": [{"name": "web_search", "label": "搜尋網路：台積電"}],
    "grounding": [GroundingItem], "error": null, "at": "…"}
 ]}

// ChartCard（draw_chart；數字全部由伺服器讀取，模型只決定畫什麼）
{"id": "cht_…", "kind": "compare",            // price | compare | revenue | eps | performance
 "title": "台積電、鴻海 漲跌幅（近 6 個月）",
 "unit": "pct",                               // price＝收盤價（原幣，見 currency）｜pct＝分數（0.0123＝1.23%）｜amount_k＝新台幣千元｜eps＝每股盈餘（元）
 "currency": null,                            // price、eps、revenue 才有（"TWD" | "USD"）
 "x": "date",                                 // date（t＝YYYY-MM-DD）｜month（YYYY-MM）｜quarter（2026Q3；美股是 FY2026Q1）
 "range": "6M",                               // 1M | 3M | 6M | YTD | 1Y | 5Y；revenue、eps 是 null
 "series": [{"name": "台積電", "symbol": "2330.TW", "points": [{"t": "2026-05-13", "v": 0.0}, {"t": "2026-05-14", "v": 0.0123}]},
            {"name": "鴻海", "symbol": "2317.TW", "points": [{"t": "2026-05-13", "v": 0.0}]}],  // 「我的報酬率」的 symbol 是 null
 "notes": ["漲跌幅只算價格變動，不含股利"],   // 照原文顯示：資料從哪一天開始、哪一檔沒有畫、分割已調整…
 "sources": ["臺灣證券交易所〈上市個股日成交資訊〉（2026），依政府資料開放授權條款第 1 版"],
 "is_demo": false}

// GroundingItem（start／end 是 text 裡的 Unicode code point 位置；text 是那一句本身）
{"index": 2, "start": 22, "end": 49, "text": "董事會批准投資 Anthropic 與 OpenAI。", "reason": "uncited_news_claim",
 "signals": ["verb:批准", "actor:董事會"]}

// Suggestions（questions 最多 3 題；介面上不加「本頁建議」之類的說明字樣）
{"route": "stock",                   // "ledger" | "stock" | "groups" | "history" | "other"
 "symbol": "2330.TW",
 "questions": [{"kind": "why_move", "text": "台積電今天為什麼漲？", "lines": ["今天", "為什麼漲？"], "symbol": "2330.TW"}],
 "actions": [{"kind": "draft_transaction", "label": "記一筆 台積電", "prompt": "買 2330 ", "symbol": null, "count": null},
             {"kind": "watchlist_add", "label": "加入自選", "prompt": null, "symbol": "2330.TW", "count": null},
             {"kind": "review_drafts", "label": "確認 2 筆草稿", "prompt": null, "symbol": null, "count": 2}]}

// Usage（上限為 null 表示不限制；messages_today 含今天觸發的法人觀點查詢，每次算一題）
// deep_search_cost：深度搜尋一次算幾題（null＝這個環境沒有深度搜尋，前端不放切換鈕）；深度搜尋的那一題在 messages_today 裡算這麼多題
{"date": "2026-11-12", "month": "2026-11", "messages_today": 3, "daily_message_limit": 50, "messages_remaining": 47,
 "tokens_month": 41200, "monthly_token_budget": 3000000, "tokens_remaining": 2958800, "cost_usd_month": 0.0123,
 "model": "claude-haiku-5-5", "available": true, "deep_search_cost": 5, "disclaimer": "AI 回答僅供參考，非投資建議。"}

// KeySlots（GET /ai/admin/keys；slot = CLAUDE_API_KEY_<n> 的 n；不含金鑰）
{"month": "2026-11",                  // UTC 月（預算以 UTC 月計）
 "sticky_wait_seconds": 5.0,
 "slots": [{"slot": 1, "configured": true,
            "state": "ok",            // ok | cooling | disabled | exhausted | over_budget | not_configured
            "retry_in_seconds": null, "workspace_id": "wrkspc_…", "month_cost_usd": 0.4211, "month_calls": 312,
            "monthly_budget_usd": 50.0, "budget_remaining_usd": 49.5789, "headroom": 0.97,
            "rate_limits": {"tokens": {"remaining": 970000, "limit": 1000000}}, "threads": 41, "failures": 0,
            "last_error": null}],    // 例如 "429 rate_limit_error"
 "server_tools": ["web_search_20260318", "web_fetch_20260318"],
 "excluded_tools": [{"type": "web_fetch_20260318", "name": "web_fetch", "reason": "API 的錯誤訊息", "at": "…"}]}

// /instruments/{symbol}/why 新增欄位
{"…原有欄位": "…", "ai": true, "headline": "AI 寫的一句話（ai=false 時是規則句）",
 "rule_headline": "台積電今天上漲 3.5%", "citations": [{"url", "title", "cited_text"}]}
```

`kind`（建議問題）：帳本 `onboard`、`drag`、`lift`、`dividends_next`、`concentration`；個股 `why_move`、`foreign_flow`、`next_dividend`、`cost_on_river`、`add_one_lot`、`is_expensive`、`if_hold_dividend`；群組 `group_share`（與前端離線規則相同）。

- `foreign_flow`「最近外資對這檔的動向？」（`lines: ["最近外資", "對這檔的動向？"]`）：只在**上市個股**（TWSE、`type: "stock"`）出現，排在 `why_move` 之後。上市股票沒有逐檔三大法人與外資持股，AI 用 `web_search` 找最近的新聞與公開資訊回答，每一點附來源與日期（系統提示與 `get_chips` 的說明都這樣要求）；上櫃股票的法人資料在籌碼分頁，不出這題。
- **圖卡（2026-11-13）**：使用者要求畫圖或比較走勢時，模型呼叫 `draw_chart`（`kind`＋`symbols`（最多 5 檔）＋`range`）。`price` 一檔的收盤價；`compare` 2–5 檔的漲跌幅（從共同的第一天起算，分割與減資已調整，不含股利）；`revenue` 月營收（近 24 個月）；`eps` 每季每股盈餘（近 8 季，台股和美股不放在同一張）；`performance` 使用者自己的時間加權報酬率和基準（只有百分比，任何模式都沒有金額、成本、股數）。每張圖所有線合計最多 480 個點（長的區間平均取樣，頭尾都留）。資料畫不出來（收盤價不到兩天、沒有營收…）時工具回 `status: "no_data"` 與原因，不送 `chart`。前端：日期軸畫折線；月份／季別的柱子總數 ≤ 24 畫柱狀、再多改畫折線；一個縱軸；兩條線以上有圖例，線尾標代號。
- 新工具 `get_related_stocks`（個股頁「相關股票」那一列，不含走勢小圖）：模型查不到某一檔當天的消息時，用它找同產業與相關個股，再搜尋類股與大盤的消息。
- 伺服器工具 `web_fetch` 一律帶 `blocked_domains: ["www.twse.com.tw", "mis.twse.com.tw"]`（不自動擷取證交所網站與 MIS；`web_search` 的結果不受影響）。API 的 `allowed_domains` 與 `blocked_domains` 只能二選一：設定了 `AI_WEB_FETCH_ALLOWED_DOMAINS` 時改成從允許清單拿掉這兩個主機，涵蓋它們的上層網域（`twse.com.tw`）換成 `openapi.twse.com.tw`；清單只剩被封鎖的主機時不提供 `web_fetch`。

### 法人觀點與美股基本面（2026-11-12 新增；法人觀點待後端實作，美股基本面已實作）

**法人觀點**（產品負責人同意：AI 可引用第三方已公開的評級與目標價，必附來源與日期；AI 自己不給目標價；不計算平均、上漲空間、不排名、不寫買賣提示）。後端已實作（`forliosa.ai.analyst`，2026-11-12）。
| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/instruments/{symbol}/analyst-views` | 讀取當日共用結果；沒有時回 `status: "none"`。查不到（`unavailable`）超過 10 分鐘後也回 `none`，讓畫面重新出現查詢按鈕 |
| POST | `/instruments/{symbol}/analyst-views` | 觸發 AI 網路搜尋並立刻回 `pending`（在背景產生，實測約 20–30 秒）；之後用 GET 輪詢。今天已經有 `pending`／`ready`（或 10 分鐘內的 `unavailable`）時直接回那一份，**不重查、不計費** |

```json
{
  "status": "ready",                 // "none" | "pending" | "ready" | "unavailable"
  "symbol": "2330.TW",
  "as_of": "2026-11-12T14:05:00+08:00",       // 查詢完成時間（只有 ready 有）
  "expires_at": "2026-11-13T14:05:00+08:00",  // 建立後 24 小時，到時刪除（none 時為 null）
  "items": [
    {"institution": "範例證券", "action": "調升", "rating_text": "加碼", "target_price": 1350, "currency": "TWD",
     "date": "2026-11-10", "source_title": "報導標題", "url": "https://…"}
  ],
  "disclaimer": "以下為媒體報導的第三方觀點，可能不完整或未經授權轉載，非 Forliosa 建議。",
  "notes": []                         // unavailable 時例如 "14:20 之後可以再查一次。"
}
```
- **共用**：同一檔、同一個台股交易日（台北時間今天；週末與休市日算最近一個交易日）全體使用者共用一份，建立後 24 小時刪除。
- **計費**：觸發搜尋的人算一題（`/ai/usage.messages_today`，和對話共用 `AI_DAILY_MESSAGE_LIMIT`），token 計入他的每月額度；其他人讀同一份不計。額度用完回 429 `ai_daily_limit`／`ai_monthly_budget`；沒有可用金鑰回 503 `ai_unavailable`；功能關閉（`AI_ANALYST_ENABLED=false` 或網路搜尋停用）回 200 `unavailable`＋說明，不計費。
- **只有個股**：ETF 回 422 `analyst_views_stocks_only`（ETF 沒有個別機構的評等與目標價）；找不到商品 404。
- **items**：最多 5 筆，依報導日期新到舊，同一家機構只留最新一筆（大摩／摩根士丹利／Morgan Stanley 這類常見別名算同一家；`institution` 照報導原文）。每筆的 `url` 必定是這次 AI 網路搜尋實際拿到的搜尋結果之一，`source_title` 是該搜尋結果自己的標題；`date` 是那篇報導的日期，由搜尋結果的網址日期或頁面日期核對（核對不到、超過 90 天、沒有具名機構——「美系外資」「外資券商」「Wall Street analysts」這類泛稱也算沒有具名——、評等與目標價都沒有、目標價幣別不是這檔股票的交易幣別，或來源是評等彙整站／報價頁／評等預測頁的，都不列）。`action` 是 調升／調降／維持／首評，報導沒寫為 `""`；`rating_text`、`target_price` 照報導原文，沒寫為 `null`；`currency` 是這檔股票的交易幣別。數字不換算、不平均、不比較。
- **ready 且 items 是空的**＝近期查無附來源與日期的機構報導。核對後一筆都沒有，但搜尋結果裡有**這檔股票**的評等／目標價標題，或有候選只因網址或日期核對不到而被刪掉時，不宣稱「查無」，改回 `unavailable`（10 分鐘後可重查）；別檔股票的評等新聞不算。

**美股基本面（SEC EDGAR，2026-11-12 已實作）**：User-Agent 需含聯絡信箱（`Forliosa/1.0 <SEC_CONTACT_EMAIL>`），從環境變數 `SEC_CONTACT_EMAIL` 讀取，不寫進程式碼；請求頻率 ≤ 10 次／秒（每個行程 ≤ 4 次／秒）。資料是美國政府公開資料（「sec.gov 的政府內容與 EDGAR 公開申報可自由存取與再利用」），`sources` 顯名為「美國證券交易委員會（SEC）〈資料集〉（年），美國政府公開資料」。後端把抓到的資料存在自己的資料庫：worker 每天更新有人持有或自選的美股，請求當下快取超過 24 小時才重抓（短逾時，失敗就用快取並在 `notes` 說明）。沒有設定信箱、SEC 拒絕連線、或找不到公司時回空資料＋`notes`，不用示範資料。實作細節見 [`apps/api/CONTRACT_NOTES.md`](../apps/api/CONTRACT_NOTES.md)「第四批」。

只對**美股個股**（`market: "US"`、`type: "stock"`）；美股 ETF 的 financials 回空＋`notes: ["ETF 沒有財務報表資料"]`，events 不含申報。

`GET /instruments/{symbol}/financials?period=quarterly|annual`：與台股同一個形狀，另有下列欄位（台股也會帶，值不同）：

| 欄位 | 台股 | 美股 |
|---|---|---|
| `periods` | `"2026Q2"`、`"2025"`（日曆季／年） | 公司會計年度 `"FY2026Q1"`、`"FY2025"`（Apple 的 FY2026Q1 是 2025-09-28～2025-12-27）；季報最多 12 期、年報最多 10 年，舊到新 |
| `period_ends` | 各期最後一天（季底、12/31） | 各期最後一天（會計年度不一定在月底結束，例如 `"2026-09-26"`） |
| `currency` | `"TWD"` | `"USD"` |
| `amount_unit` | `1000`（金額單位千元） | `1`（金額單位美元） |
| `income.eps` | 基本 EPS（元） | **稀釋** EPS（美元） |
| `cashflow.free_cash_flow` | 營業 + 投資活動現金流量 | 營業活動現金流量 − 購置不動產、廠房及設備 |
| `shares` | `null` | `{outstanding, outstanding_as_of, diluted_average: [...]}`：封面頁流通股數與日期、各期稀釋加權平均股數（推算的季度為 `null`） |
| `as_of` | `null` | 這份公司資料從 SEC 取得的時間（ISO，+08:00） |

```json
// GET /instruments/AAPL/financials?period=quarterly（節錄）
{"symbol": "AAPL", "period": "quarterly", "currency": "USD", "amount_unit": 1,
 "periods": ["…", "FY2026Q3", "FY2026Q4"], "period_ends": ["…", "2026-06-27", "2026-09-26"],
 "income": {"revenue": [… , 109417000000, 114477000000], "eps": [… , 2.02, 2.1], "…": []},
 "shares": {"outstanding": 14532182000, "outstanding_as_of": "2026-10-23", "diluted_average": [… , 14714676000, null]},
 "as_of": "2026-11-12T08:05:00+08:00",
 "sources": ["美國證券交易委員會（SEC）〈EDGAR XBRL 財報數據（companyfacts）〉（2026），美國政府公開資料"],
 "notes": ["美股依公司會計年度標示：FY2026Q1 是 2025-09-28 至 2025-12-27 的季度", "金額單位：美元；…",
           "10-Q 的現金流量是年初至今累計、10-K 只報全年：單季數字由累計數相減得出", "第四季（或只有累計數的季度）EPS 為累計 EPS 相減的近似值"]}
```

- 單季數字：有三個月的數字就用；只有年初至今累計時用相減（第四季 = 全年 − 前三季累計）。這類推算會在 `notes` 說明，EPS 推算是近似值。
- 同一期被後來的報告重編時用最新的數字。
- 股票分割：`income.eps` 與 `shares.diluted_average` 一律以**目前的股數**為準。分割後的報告只重編最近幾期（10-K 三年、10-Q 去年同期），更早、沒被重編的數字由後端依分割比例換算（EPS ÷ 比例、股數 × 比例）；第四季 EPS 也用換算後的累計數相減。分割從同一期在分割前後申報的股數變化找出（沒有股數標籤時用 EPS，且要兩期一致）。顯示的期間內有分割時 `notes` 多一行：「EPS 與稀釋平均股數都以目前的股數為準：2021-08-20 起申報的財報反映 1 股拆成 4 股、2024-08-28 起申報的財報反映 1 股拆成 10 股；更早申報、後來沒有重編的數字已依分割比例換算」（日期是第一份採用新股數的申報）。
- 會計年度名稱用那一期自己的年度：新上市公司的第一份 10-K 一起帶出的前兩年，SEC 標的是那份申報的年度，後端會往回推（例如 FY2025 10-K 裡的 2023、2024 年是 `FY2023`、`FY2024`）。
- `GET /instruments/{symbol}/overview`（美股個股）：`eps_ttm` = 最近四季稀釋 EPS（剛好一整個會計年度時用 10-K 全年 EPS），`shares_outstanding` = 封面頁流通股數；只讀快取，沒抓過時為 `null`。

`GET /instruments/{symbol}/events`（美股個股）加入 SEC 申報：

| 欄位 | 值 |
|---|---|
| `type` | `"sec_filing"` |
| `form` | `"8-K"`、`"10-Q"`、`"10-K"` 或修正 `"8-K/A"`、`"10-Q/A"`、`"10-K/A"`（其他表單不列；台股事件沒有這個欄位或為 `null`） |
| `date` | 申報日 |
| `title` | 「10-K 年度報告」「10-Q 季度報告」「8-K 營運結果與財務狀況」（8-K 用申報項目名稱；修正加「（修正）」） |
| `detail` | 「會計年度截至 2026-09-26」「季度截至 2026-06-27」「申報項目：2.02 營運結果與財務狀況、9.01 財務報表與附件；事件日期 2026-11-02」 |
| `url` | sec.gov 原文：`https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm` |
| `mine` | 持有時 10-K、10-Q 為 `true`；8-K 只有最近 7 天的為 `true` |
| `sources` | `["美國證券交易委員會（SEC）〈EDGAR 公司申報清單（submissions）〉（2026），美國政府公開資料"]` |

`GET /meta/attributions`：多三個資料集 `sec-edgar/tickers`、`sec-edgar/companyfacts`、`sec-edgar/submissions`（`license_status: "public"`，`license`／`license_url` 是 SEC 的網站政策），`notice` 多一行 SEC 的再利用說明。AI 工具 `get_financials`、`get_events` 對美股回傳同樣的資料（`units` 寫明美元與會計年度）。

---

## 分享（M5）

登入、授權唯讀查看、親友群組、群組 AI 週報與頻道推播（2026-11-12 定案，後端全部已實作）。後端實作的解讀與新增欄位見
[`apps/api/CONTRACT_NOTES.md`](../apps/api/CONTRACT_NOTES.md)「2026-11-12 分享（M5）第一批」（登入、授權、群組）與「第二批」（週報、頻道、推播）。

產品負責人決定（`PRODUCT.md`「分享（M5）範圍」）：照 `docs/product-spec.md` §4.8 一次做完；正式登入用 **Discord OAuth**、開放任何人註冊；
排行看今日、本月、今年，另外顯示總報酬率（含股利），可對照大盤與 0050；交易動態只顯示買賣哪一檔，可選擇附上價格，**沒有理由欄位**；
推播要本人另開「推播」開關；加入群組前先選分享；授權唯讀查看只能給同群組的成員。

### 共通規則

- **分享投影**：群組、授權查看、推播與 AI 週報讀別人的資料時，一律經過 `services/sharing.py`。投影依「這位成員目前在這個群組的分享設定」或
  「這份授權目前的範圍」過濾，**每次讀取時重新套用**（關掉開關、離開群組、撤銷授權，立刻看不到，包括過去的週報與動態）。
  沒開放的欄位**不出現在回應裡**（鍵不存在，不是 `null` 也不是 0）。測試必須逐項證明關掉的開關不會洩漏（金額、股數、交易價格、帳戶名稱、備註）。
- **不透露誰沒分享**：沒開放的成員不出現在排行、動態、持股裡，也沒有「未分享」標記；`SharedPortfolio` 沒開任何項目時只回身分欄位。
  前端不得拿成員名單去比對排行或動態，也不顯示「某某沒分享」；沒有資料時和「還沒有資料」顯示一樣的中性狀態。
- **精度**：分享投影裡的權重四捨五入到 0.01、報酬率到 0.0001。同時打開「持股」與「金額」時，別人可以推算大約股數：前端在開關旁提示。
- **存在與權限**：不是成員的人，群組相關端點一律 404 `not_found`（不透露群組是否存在）；是成員但權限不足回 403 `forbidden`。
- **CSRF**：非 `GET`／`HEAD`／`OPTIONS` 的請求若帶 `Origin`，必須在 `CORS_ORIGINS` 內，否則 403 `forbidden`（全站適用）。
- **上限**：每個群組最多 50 位成員；每人最多加入 20 個群組（超過回 409 `limit_reached`）。
- 錯誤代碼：`forbidden`、`not_found`、`read_only`、`view_as_not_allowed`、`delegation_revoked`、`already_member`、`invite_invalid`、
  `limit_reached`、`webhook_failed`、`telegram_unavailable`（409：伺服器沒有設定 Telegram bot）、`rate_limited`（429：設定 Discord
  webhook 太頻繁，或伺服器暫停呼叫 Discord）、`oauth_*`（見登入）；格式錯誤一律 422 `validation_error`。
- **名稱只能是一行**：顯示名稱與群組名稱不能有換行、Tab 等控制字元，也不能有看不見的格式字元（雙向文字控制、零寬空白、BOM 等；
  組合 emoji 用的 U+200D 可以），否則 422 `validation_error`。Discord 登入取得的名稱會自動去掉這些字元。

### 登入（Discord、Google OAuth）與個人資料

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/auth/providers` | 不需登入：`{"discord": true, "google": true, "dev_login": false}`（`discord`、`google` 依各自的環境變數是否齊全） |
| GET | `/auth/discord/start?next=/invite/abc` | 302 到 Discord 授權頁（scope `identify email`、`prompt=none` 不帶） |
| GET | `/auth/discord/callback?code=&state=` | 驗證 state、換 token、讀 `/users/@me`；成功建立 session（輪換 session id）後 302 到 `{FRONTEND_URL}{next}`；失敗 302 到 `{FRONTEND_URL}/login?error=<code>` |
| GET | `/auth/google/start?next=/invite/abc` | 302 到 Google 授權頁（scope `openid email profile`、`prompt=select_account`） |
| GET | `/auth/google/callback?code=&state=` | 同 Discord 的 callback：驗證 state、換 token、讀 userinfo（`sub`、`email`、`email_verified`、`name`、`picture`）；成功或失敗的導向相同 |
| PATCH | `/me` | `{"display_name"}`（1–30 字，去頭尾空白，只能一行：見共通規則）→ `User`。群組裡顯示的就是這個名稱 |

- **state**：隨機值＋`next`，以 `SESSION_SECRET` 做 HMAC 簽章，存在 10 分鐘的 cookie（正式環境 `__Host-forliosa_oauth`：
  `Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=600`；開發環境不加 `__Host-` 前綴、不加 `Secure`）。callback 以固定時間比對，
  不論成敗都刪除這個 cookie（一次性）。不可用 `SameSite=Strict`（callback 是從 discord.com 來的跨站導覽）。
- **`next`**：解碼一次後必須符合 `^/(?![/\\])[\x21-\x7E]{0,511}$`，否則改成 `/`（避免 `//evil.com`、`/\evil.com`）。
- **帳號對應**：先以 Discord 使用者 id 找。找不到時，只有既有帳號**還沒連結任何 Discord id** 才以**已驗證**的 email 連結；那個 email
  已連結到別的 Discord id → `oauth_email_conflict`。都沒有就建立新帳號（`display_name` 取 Discord 的 global name，否則 username）。
  建立或連結時要求 Discord 回報 email 已驗證（否則 `oauth_email_unverified`）；已連結的帳號之後照常登入，每次登入更新 email 與頭像。
- 不儲存 Discord 的 access／refresh token（只用一次讀個人資料）。
- 失敗代碼：`oauth_disabled`、`oauth_denied`（使用者按取消）、`oauth_state`、`oauth_email_unverified`、`oauth_email_conflict`、`oauth_failed`。
- 環境變數：`DISCORD_CLIENT_ID`、`DISCORD_CLIENT_SECRET`、`DISCORD_REDIRECT_URI`（API 主機上的 callback 網址，與 Discord Developer Portal 設定一致）、
  `FRONTEND_URL`。`FORLIOSA_ENV=prod` 啟動時檢查：`FRONTEND_URL` 在 `CORS_ORIGINS` 裡、兩者與 `DISCORD_REDIRECT_URI` 都是 https，否則拒絕啟動。
- **Google 登入（2026-11-13）**：和 Discord 同一套規則。帳號對應以 Google 的 `sub` 找；找不到時，既有帳號**還沒連結任何 Google 帳號**才以**已驗證**的 email 連結——所以同一個人今天用 Discord、明天用 Google（同一個 email）登入，是同一個帳號（`user_identities` 一人每種登入方式各一筆）。那個 email 已連結到別的 Google 帳號 → `oauth_email_conflict`。新帳號的 `display_name` 取 Google 帳號的名稱，`avatar_url` 是 Google 的頭像網址（每次登入更新成這次登入那一家的頭像）。不儲存 Google 的 access token、id token（讀完 userinfo 就撤銷）。state 簽章裡帶著是哪一家：Discord 發的 state 不能拿到 Google 的 callback 用，反之亦然。
  環境變數 `GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`、`GOOGLE_REDIRECT_URI`（`…/api/v1/auth/google/callback`，正式環境 https）。Google 是選用的：三個沒設齊或正式環境的 callback 不是 https 時，`google` 是 false、啟動時記一行警告，**不會**拒絕啟動。
- `POST /auth/dev-login` 照舊只在開發環境啟用。開放任何 Discord 帳號註冊；每人的 AI 額度照現有限制。
- `User` 新增 `avatar_url`（Discord 頭像網址，可為 `null`）。

### 授權唯讀查看（一對一）

只能授權給**和自己同在至少一個群組**的成員。

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/delegations` | `{"granted": Delegation[], "received": Delegation[]}`（我授權給別人的／別人授權給我的） |
| GET | `/delegations/candidates` | 可以授權的人：和我同群組的成員 `[{"user_id", "display_name", "avatar_url"}]`（已授權的也列，帶 `delegation_id`） |
| POST | `/delegations` | `{"viewer_user_id", "scope": "all" \| "accounts", "account_ids": [...]}` → `Delegation`。對方不是同群組成員回 404；已授權過回 409 `already_member`（改用 PATCH）；`account_ids` 必須是自己的帳戶（否則 422） |
| PATCH | `/delegations/{id}` | 授權者修改範圍：`{"scope", "account_ids"}` |
| DELETE | `/delegations/{id}` | 授權者撤銷，或被授權者自己移除；立即生效 |

```json
// Delegation
{
  "id": "dlg_01J...",
  "owner": {"user_id": "usr_...", "display_name": "爸爸", "avatar_url": null},
  "viewer": {"user_id": "usr_...", "display_name": "小明", "avatar_url": null},
  "scope": "accounts",                       // "all" 也包含之後新增的帳戶
  "accounts": [{"id": "acc_...", "name": "永豐－一般"}],   // 授權範圍內的帳戶；帳戶刪除後自動移出
  "created_at": "2026-11-12T20:00:00+08:00"
}
```

- 授權者與被授權者之後不再同群組時，授權**不會**自動撤銷（授權是一對一的決定）；授權者可隨時撤銷。

**以唯讀身分查看**：前端在請求加上標頭 `X-Forliosa-View-As: <delegation_id>`（CORS `allow_headers` 包含它）。以路由白名單實作，預設拒絕：

1. **使用者資料端點**只允許這些 `GET`：`/accounts`、`/portfolio/summary`、`/portfolio/holdings`、`/portfolio/performance`、
   `/portfolio/closed`、`/portfolio/upcoming`、`/transactions`、`/transactions/{id}`、`/instruments/{symbol}/position`、
   `/instruments/{symbol}/position/history`、`/instruments/{symbol}/events`。回應以授權者身分計算，**而且授權者只有授權範圍內的帳戶**
   （`allocation.by_account`、`upcoming` 的定期定額、`events` 的 `mine`／`amount_estimate` 都只算範圍內）；`account_id` 參數超出範圍回 404。
2. **不讀使用者資料的端點**忽略這個標頭：商品搜尋、`/instruments/{symbol}`、報價、K 線、某一天的收盤（`/instruments/{symbol}/close`）、估值、月營收、股利、總覽、盤中、籌碼、財務、
   新聞、為什麼漲跌、`/quotes`、`/stream/quotes`、`/derivatives/*`、`/meta/*`、`/auth/providers`、`GET /me`。
3. 其他請求：寫入（非 `GET`）回 403 `read_only`；其他使用者資料端點（AI、自選、群組、授權、設定、匯出）回 403 `view_as_not_allowed`。
4. 授權不存在、已撤銷、或被授權者不是我：一律 403 `delegation_revoked`（不區分），前端退出查看模式。

- 顯示偏好（紅漲綠跌、以張或股、隱私模式）用查看者自己的；成本法、基準用授權者的。
- AI 不讀被查看者的資料：查看模式下前端停用全域 AI 輸入框與 AI 面板，並隱藏「加入自選」「記一筆」「問 AI」這類動作。

### 親友群組

角色：`owner`（擁有者，一位）、`admin`（管理員）、`member`（成員）。

| 方法 | 路徑 | 權限 | 說明 |
|---|---|---|---|
| GET | `/groups` | 登入 | `GroupSummary[]`（我加入的群組） |
| POST | `/groups` | 登入 | `{"name"}`（1–40 字，只能一行）→ `Group`；建立者為 owner，分享設定為預設值 |
| GET | `/groups/{id}` | 成員 | `Group` |
| PATCH | `/groups/{id}` | 管理員；`ranking_enabled` 只限 owner | `{"name"?, "ranking_enabled"?}` |
| DELETE | `/groups/{id}` | owner | 刪除群組（含留言、週報、頻道設定） |
| POST | `/groups/{id}/transfer` | owner | `{"user_id"}` 把 owner 轉給另一位成員（原 owner 變 admin） |
| PATCH | `/groups/{id}/members/{user_id}` | owner | `{"role": "admin" \| "member"}` |
| DELETE | `/groups/{id}/members/{user_id}` | 管理員移除成員；任何人移除自己 | owner 要先轉移才能離開；admin 不能移除 owner 或其他 admin。移除成員時撤回群組所有「可多次使用」的邀請。離開或被移除後分享設定刪除，重新加入時重新選 |
| POST | `/groups/{id}/invites` | 管理員 | `{"expires": "24h" \| "7d", "multi_use": false}`（預設 7 天、單次）→ `{"id", "url", "expires_at", "multi_use", "uses"}`；`url` 只在建立時回傳 |
| GET | `/groups/{id}/invites` | 管理員 | 有效的邀請（不含 `url`） |
| DELETE | `/groups/{id}/invites/{invite_id}` | 管理員 | 撤回 |
| GET | `/invites/{token}` | 不需登入 | 預覽 `{"group_name", "inviter_display_name", "status": "valid" \| "member"}`（`member`：已登入且已是成員，這時多一個 `group_id`，只有成員本人拿得到，前端直接連到那個群組；2026-11-14）。無效的 token 404；過期、撤回、用完 410 `invite_invalid` |
| POST | `/invites/{token}/accept` | 登入 | `{"share": ShareSettings}`（必填：前端先讓使用者確認開關）→ `Group`；已是成員 409 `already_member`；無效 404／410 |
| GET | `/groups/{id}/share` | 成員 | 我在這個群組的 `ShareSettings` |
| PUT | `/groups/{id}/share` | 成員 | 更新我在這個群組的 `ShareSettings`（立即生效） |
| GET | `/groups/{id}/leaderboard?period=day` | 成員 | `Leaderboard`；`period`：`day`、`month`、`year` |
| GET | `/groups/{id}/holdings` | 成員 | `GroupHoldings` |
| GET | `/groups/{id}/members/{user_id}/shared` | 成員 | `SharedPortfolio` |
| GET | `/groups/{id}/feed?limit=30&cursor=&user_id=` | 成員 | `{"items": FeedItem[], "next_cursor"}`；`user_id` 篩選一位成員 |
| GET | `/groups/{id}/comments?target=&limit=50&cursor=` | 成員 | 一個對象的留言，舊到新，`{"items": Comment[], "next_cursor"}` |
| POST | `/groups/{id}/comments` | 成員 | `{"target", "body"}`（1–500 字）→ `Comment` |
| DELETE | `/groups/{id}/comments/{comment_id}` | 作者或管理員 | 刪除留言 |
| PUT | `/groups/{id}/reactions` | 成員 | `{"target", "emoji"}` 加表情（重複呼叫不重複計） |
| DELETE | `/groups/{id}/reactions?target=&emoji=` | 成員 | 收回自己的表情 |
| GET | `/groups/{id}/digests?limit=8&cursor=` | 成員 | 群組 AI 週報，新到舊（`limit` 1–52），`{"items": Digest[], "next_cursor"}` |
| GET | `/groups/{id}/channels` | 成員 | `Channels`（`webhook_hint` 只有 owner 看得到，其他人為 `null`） |
| PUT | `/groups/{id}/channels/discord` | owner | `{"webhook_url", "notify_trades"?, "notify_digest"?}`（兩個開關預設 `true`）→ `Channels`；儲存前送一則測試訊息，失敗 422 `webhook_failed`；網址格式不符 422 `validation_error`（錯誤訊息不含網址）；同一人或同一群組 10 分鐘內超過 5 次 → 429 `rate_limited`（不送出）；換成另一個 webhook 時，其他成員的 `push` 自動關閉（見推播） |
| PATCH | `/groups/{id}/channels/discord` | owner | `{"notify_trades"?, "notify_digest"?}` → `Channels`；還沒設定 404 |
| DELETE | `/groups/{id}/channels/discord` | owner | 解除（204；還沒送出的推播取消；之後再設定算新的目的地） |
| POST | `/groups/{id}/channels/telegram/link` | owner | → `{"code", "bot_username", "expires_at"}`：把 bot 加進 Telegram 群組，在群組裡傳 `/link <code>`（10 分鐘內、一次性；再產生一組會讓舊的失效）；伺服器沒有 bot 時 409 `telegram_unavailable` |
| PATCH | `/groups/{id}/channels/telegram` | owner | `{"notify_trades"?, "notify_digest"?}` → `Channels`；還沒連結 404 |
| DELETE | `/groups/{id}/channels/telegram` | owner | 解除（204） |

```json
// GroupSummary
{"id": "grp_...", "name": "家族投資", "my_role": "owner", "member_count": 5, "ranking_enabled": true,
 "latest_activity_at": "2026-11-12T13:40:00+08:00", "latest_digest_at": "2026-11-15T20:00:00+08:00"}

// Group
{
  "id": "grp_...", "name": "家族投資", "my_role": "owner", "ranking_enabled": true,
  "created_at": "2026-11-12T20:00:00+08:00",
  "members": [{"user_id": "usr_...", "display_name": "爸爸", "avatar_url": null, "role": "owner",
               "joined_at": "2026-11-12T20:00:00+08:00", "is_me": true}],
  "my_share": ShareSettings,
  "push_targets": [{"kind": "discord", "label": "Discord 頻道"}, {"kind": "telegram", "label": "家族投資群"}]   // 每位成員都看得到
}

// ShareSettings（預設只開 returns；接受邀請時由本人確認）
{
  "returns": true,        // 報酬率（只有 %）：今日、本月、今年、總報酬率
  "holdings": false,      // 持股名稱與權重（不含股數、金額）
  "amounts": false,       // 實際金額與損益：市值、今日損益、總損益
  "trades": false,        // 交易動態：買進／賣出哪一檔（打開時也顯示最近 90 天）
  "trade_prices": false,  // 交易動態附上成交價（trades 關閉時保存但無作用）；沒有理由欄位
  "push": false           // 把我開放的內容送到群組的 Discord／Telegram 頻道（預設關）
}

// Leaderboard
{
  "period": "month",
  "date": "2026-11-12",                   // 最新收盤的交易日
  "start_date": "2026-10-30",             // 期間起點（上月最後收盤）
  "as_of": "2026-11-12T13:30:00+08:00",
  "ranked": true,                         // owner 關掉排行時為 false：沒有 rank，依加入順序
  "entries": [{"user_id": "usr_...", "display_name": "爸爸", "avatar_url": null, "return_pct": 0.0321,
               "total_return_pct": 0.284, "rank": 1, "is_me": false}],
  "benchmarks": [{"symbol": "^TAIEXTR", "name": "發行量加權股價報酬指數", "return_pct": 0.0254},
                 {"symbol": "0050.TW", "name": "元大台灣50", "return_pct": 0.0247}],
  "notes": [], "sources": ["臺灣證券交易所〈…〉（2026），依政府資料開放授權條款第 1 版"],
  "is_demo": false,
  "comment_count": 2, "reactions": [{"emoji": "🎉", "count": 3, "mine": true}]   // 當天排行的討論串 leaderboard:<date>（2026-11-14）
}
```

- **排行的表情與留言數**（2026-11-14，產品負責人照建議）：`comment_count`、`reactions` 是對象 `leaderboard:<date>` 的計數，和 `FeedItem`、`Digest` 同一種形狀；
  三個期間的 `date` 相同，所以是同一串。只有計數與「我按過沒有」（`mine`），不列出誰按的；沒開報酬率的成員照樣不在 `entries` 裡，也不另外計數。
  排行最早的那一天（群組在週末或收盤前建立時，排行顯示的是前一個收盤日）也能留言、按表情。
- **期間定義**：以收盤價、該成員全部帳戶合併、新台幣計。`day` = 最新收盤相對前一收盤；`month` = 上月最後收盤到最新收盤的 TWR；
  `year` = 去年最後收盤到最新收盤的 TWR。所有成員與基準共用同一個 `start_date`（期間起點與存檔起點較晚者）；期間中才開始持有的成員從第一天
  有持股起算。**整段期間都沒有收盤價的持股（commercial 下的美股）不算進期間報酬**（和帳本的「今日」同一條
  規則，2026-11-14）；`LeaderboardEntry.excludes_unpriced` 只在**自己那一列**是 `true`（別人的一律 `false`：別人有沒有美股不是群組該知道的）。
  其他缺價（期間中有幾天沒有收盤價）時該成員所有期間為 `null`，排在最後、沒有 rank，不說明原因。報酬率四捨五入到 4 位後相同就並列名次（1、1、3）。
- **總報酬率** `total_return_pct` 每筆都附上、不排名、沒有基準（各人起點不同）；同 `PortfolioSummary.total_return_pct`（含股利）。
- `/portfolio/performance` 的 `range` 新增 `MTD`（上月最後收盤起）；分享卡的「本月」用它。

```json
// GroupHoldings（只有開了 holdings 的成員）
{
  "members": [{"user_id": "usr_...", "display_name": "爸爸",
               "holdings": [{"symbol": "2330.TW", "name": "台積電", "weight": 0.42}]}],
  "common": [{"symbol": "2330.TW", "name": "台積電", "holder_count": 3}],     // 兩人以上持有，依人數排序
  "industries": [{"industry": "半導體業", "holder_count": 4}],
  "is_demo": false
}

// SharedPortfolio（只出現對方開放的區塊；沒開放的鍵不存在）
{
  "user_id": "usr_...", "display_name": "爸爸", "avatar_url": null,
  "returns": {"day": 0.0124, "month": 0.0321, "year": 0.152, "total": 0.284},
  "holdings": [{"symbol": "2330.TW", "name": "台積電", "weight": 0.42}],
  "amounts": {"market_value": 3284500, "day_change": 40320, "total_pnl": 242000},
  "is_demo": false
}

// FeedItem
{
  "id": "gfi_...", "type": "trade",              // "trade" | "member_joined"
  "user_id": "usr_...", "display_name": "爸爸", "avatar_url": null,
  "side": "buy", "symbol": "2330.TW", "name": "台積電", "trade_date": "2026-11-12",
  "count": 1,                                    // 同一人同一天同一檔同方向的交易合併成一則（定期定額不會洗版）
  "price": 1085.0, "currency": "TWD",            // 只有開了 trade_prices 才有這兩個鍵：交易幣別的成交價（多筆合併時為加權平均），不含費用
  "created_at": "2026-11-12T13:40:00+08:00",
  "comment_count": 2,
  "reactions": [{"emoji": "👍", "count": 3, "mine": true}]
}

// Comment
{"id": "gcm_...", "target": "trade:gfi_...", "user_id": "usr_...", "display_name": "小明", "body": "跟上",
 "created_at": "2026-11-12T20:05:00+08:00", "can_delete": true}
// 已離開群組的成員的留言：display_name 為「已離開的成員」、user_id 為 null

// Digest（群組 AI 週報）
{
  "id": "gdg_...", "status": "ready",          // "pending"（AI 還在寫）| "ready" | "failed"（AI 沒寫成；facts 照樣有）
  "week_start": "2026-11-09", "week_end": "2026-11-13",
  "created_at": "2026-11-14T20:00:00+08:00",
  "summary": "本週群組整體……",                 // 只有 ready 才有內容；AI 只寫群組整體，不點名個人，不給買賣建議或目標價；
                                               // 寫進摘要的成員有人離開或關掉當時分享的項目時為 ""（見群組 AI 週報）
  "facts": {                                   // 讀取時依「目前」的成員身分與分享設定過濾
    "returns": [{"user_id": "usr_...", "display_name": "爸爸", "week_return_pct": 0.012}],
    "benchmarks": [{"symbol": "^TAIEXTR", "name": "發行量加權股價報酬指數", "week_return_pct": 0.008}],
    "common_holdings": [{"symbol": "2330.TW", "name": "台積電", "holder_count": 3}],
    "industries": [{"industry": "半導體業", "holder_count": 4}],
    "trades_count": 7                          // 只算開了 trades 的成員
  },
  "notes": [],                                 // 例如「資料從 2026/06/01 開始，…」；摘要不再顯示時加一則說明
  "disclaimer": "AI 分析僅供參考，不構成投資建議。",
  "sources": ["…"], "is_demo": false,
  "comment_count": 0, "reactions": []          // 只有 ready 的週報能留言、按表情
}

// Channels
{
  "discord": {"configured": true, "status": "active", "disabled_reason": null, "webhook_hint": "…/a1b2",
              "notify_trades": true, "notify_digest": true},
  "telegram": {"configured": false, "status": null, "disabled_reason": null, "chat_title": null,
               "notify_trades": true, "notify_digest": true},
  "telegram_available": true            // 伺服器有設定 bot 時才為 true
}
// disabled_reason："webhook_invalid"（Discord 回 401／404）、"webhook_unreadable"（SESSION_SECRET 換過，解不開）、
//                  "bot_removed"（bot 被移出 Telegram 群組）、"chat_not_found"；owner 重新設定即恢復
```

**交易動態**

- 來源：開了 `trades` 的成員，`source` 為 `manual`、`import`、`ai_draft` 的 `buy`／`sell`（股利、自動入帳都不列），
  `trade_date`（台北）在最近 90 天內。打開 `trades` 時最近 90 天的也會出現（開關旁明講）。排序：`trade_date`、`created_at`、`id` 由新到舊。
- 成員關掉 `trades` 或離開群組，他的動態立刻消失（留言保留但看不到；重新打開時恢復）；交易被刪除時，那則動態和底下的留言一起刪除。
- 新成員加入時產生一則 `member_joined`（每個人都看得到加入的事實，不含任何分享內容）。

**留言與表情**

- 對象 `target`：`trade:<feed_item_id>`、`digest:<digest_id>`、`leaderboard:<YYYY-MM-DD>`（當天排行的討論串）。對象必須屬於這個群組、而且在目前的
  分享投影裡看得到；看不到、不存在、屬於別的群組的，一律 404 `not_found`（同一個訊息）。`comment_count`／`reactions` 只算看得到的對象。
- 表情固定六個：`👍`、`🎉`、`🔥`、`😮`、`😢`、`👀`；其他值 422 `validation_error`。

**群組 AI 週報**

- 一週 = 台北的週一到週五；`week_return_pct` = 週一前最後收盤到週五（或之前最後一個交易日）收盤。沒有交易日的週、開了 `returns` 的成員少於 2 位
  的群組不產生。worker 每週六 20:00（台北）以 Message Batches API 送出（週六晚上沒跑到時，週日補做），結果回來（`ready`）後才推播；
  Batches 不能用或單筆失敗時改用一般呼叫。
- `facts` 由伺服器從分享投影計算，以 `user_id` 儲存，讀取時依目前的成員身分與開關過濾（關掉或離開的人從過去的週報消失）。
  AI 只拿到匿名代號（成員 A、B…，每份週報隨機排序）與數字，`summary` 只描述群組整體；顯示名稱、群組名稱不進 prompt。
  回答裡出現成員代號或目標價的不採用（`failed`）。週報不計入成員的 AI 額度。
- **`summary` 也依目前的設定顯示**：摘要是用送給 AI 的那幾位成員的數字寫的（例如報酬分布的範圍），所以只有在他們**每一位**都還在群組、
  還開著當時分享的那一項（報酬率、持股、交易動態）時才顯示；否則 `summary` 為空字串，`notes` 加一則「摘要不再顯示」的說明
  （狀態仍是 `ready`，facts、留言、表情照常）。他重新打開那一項時摘要恢復。推播用同一套規則，另外要求每一位都開著 `push`。
- 週報（連同留言、表情）保存 26 週。

**推播**

- 只推播 `push` 為 true 的成員所開放的內容：交易動態（`notify_trades`；`trades` 開啟、交易日在 3 個日曆日內（今天與前兩天，台北）、
  建立時間晚於頻道設定與他打開 `push`／`trades` 的時間；建立 15 分鐘後才送，期間刪除或關閉就不送；送出後的修改不重送；有開 `trade_prices`
  才附價格；同一則動態裡同時到期的交易合併成一則訊息）與週報（`notify_digest`；只含 `push` 為 true 的成員的數字；AI 摘要只在寫進摘要的
  每一位成員都還開著 `push` 時才附上）。訊息只有顯示名稱、買賣、商品、日期、筆數（與價格），附群組頁連結但不含群組 id。
- **訊息裡的名稱**（顯示名稱、群組名稱、商品名稱、AI 摘要）一律先變成一行（去掉換行與控制字元），Discord 再把 Markdown 符號加上反斜線
  （名稱不能變成連結、標題、引用、劇透或程式碼），Telegram 把 `@` 換成全形 `＠`。Discord 訊息另外帶 `flags: 4`（`SUPPRESS_EMBEDS`，
  不產生連結預覽）。
- **換推播目的地要重新同意**：owner 把頻道指到別的地方（Discord 換成另一個 webhook——即使在同一個頻道；Telegram 連到另一個聊天室；
  或解除後再設定）時，**其他成員**的 `push` 自動關閉，要本人看過 `push_targets` 後重新打開；設定的 owner 自己的開關不變。同一個 webhook
  或同一個聊天室重新設定、Telegram 升級成超級群組，不算換目的地。群組第一次設定頻道時不影響已開的 `push`。
- `notify_trades` 從關到開時，頻道的「設定時間」重設：關著那段時間的交易不會補送。
- Discord：webhook 網址解析後主機必須是 `discord.com` 或 `discordapp.com`、沒有帳密與連接埠、路徑為 `/api/webhooks/{id}/{token}`；不跟隨轉址；
  加密儲存、不寫進 log、回應只給最後 4 碼。訊息帶 `allowed_mentions: {"parse": []}`（名稱與內容不能 @everyone）。404／401 → 頻道 `disabled`。
  設定 webhook 每次都會真的打到 Discord，所以每人、每群組 10 分鐘最多 5 次（429 `rate_limited`）；Discord 會暫時封鎖 10 分鐘內有 1 萬次
  401／403／429 的 IP（Discord 登入也在同一台 API），伺服器在 10 分鐘內收到 500 次這類回應時，暫停所有 webhook 請求 10 分鐘（設定回 429
  `rate_limited`，推播延後重試）。
- Telegram：worker 以 `getUpdates` 輪詢（不開公開的 webhook 端點），處理 `/link <code>` 與 `/link@<bot> <code>`；連結成功時 bot 回覆群組名稱，
  owner 在 app 裡看到 `chat_title` 確認。訊息不用 `parse_mode`。403（bot 被移出）→ `disabled`；`migrate_to_chat_id` 時更新 chat id。
  任何人都能傳訊息給 bot，所以輪詢在時間預算內把積壓的更新讀完、`/link` 以外的訊息不做任何事、失敗的 `/link`（私訊、無效的碼）
  每個聊天室每分鐘最多回一次，而且輪詢在 worker 裡獨立執行，不會拖慢其他工作。
- 送出失敗會重試（最多 5 次、指數退避）。環境變數：`TELEGRAM_BOT_TOKEN`、`TELEGRAM_BOT_USERNAME`（沒設定時 `telegram_available: false`）。
- 個人通知管道（`docs/product-spec.md` §4.9 的個人 Telegram／Discord）不在 M5。
- Telegram 的 bot 預設開著隱私模式（只收到明確給它的指令），前端顯示連結指令時用 `/link@<bot_username> <code>` 的形式最可靠。

**帳號刪除**：見「帳號：匯出資料、刪除帳號、條款版本」。擁有的群組轉給最早的 admin，沒有就最早加入的成員，沒有成員就刪除群組；授權全部刪除；留言顯示「已刪除的帳號」。

## 帳號：匯出資料、刪除帳號、條款版本（2026-11-13）

產品負責人決定：開放註冊前要有「匯出我的資料」與「自助刪除帳號」；登入頁要連到服務條款與隱私權政策，並記錄使用者同意的版本。文件草稿在 `docs/legal/`。

- 這一節的端點一律以**登入者本人**為準，查看別人資產（`X-Forliosa-View-As`）時回 403 `read_only`（刪除、同意條款）或忽略標頭（匯出只匯出本人的）。

### 匯出我的資料

- `GET /me/export` → `application/json`，`Content-Disposition: attachment; filename="forliosa-export-<YYYYMMDD>.json"`。每人每小時最多 5 次（429 `rate_limited`，帶 `retry_after_seconds`）。
- 內容只有這個帳號自己的資料，一個 JSON 物件：
  ```jsonc
  { "exported_at": "2026-11-13T08:00:00Z", "format_version": 1,
    "profile": { /* 顯示名稱、email、公開暱稱、偏好設定、建立時間、同意的條款版本 */ },
    "accounts": [...], "transactions": [...], "recurring_plans": [...], "watchlist": [...],
    "auto_dividend_skips": [...],
    "ai": { "threads": [ /* 還在保存期內的對話與訊息 */ ], "drafts": [...] },
    "groups": [ /* 我加入的群組：名稱、角色、我的分享設定 */ ],
    "group_comments": [ /* 我寫的留言 */ ], "group_reactions": [...],
    "delegations": { "given": [...], "received": [...] },
    "discussions": { "topics": [...], "replies": [...], "reactions": [...] } }
  ```
- 不含：別人的資料（群組其他成員的內容、別人授權給我的帳本內容）、行情資料、機密（session、群組頻道的 webhook 網址與 Telegram 連結碼）、站方的檢舉與停權紀錄。金額與股數照帳本原樣（不受隱私模式影響）。

### 刪除帳號

- `DELETE /me`，body `{"confirm": "刪除我的帳號"}`（字串不符 → 422）→ 204，並清除 session cookie。不能復原。
- 刪除的：個人資料（email、顯示名稱、頭像、公開暱稱、偏好）、所有登入 session、券商帳戶與全部交易、定期定額、觀察清單、股利自動入帳的略過紀錄、AI 對話與草稿、
  群組成員身分與分享設定、我給別人與別人給我的授權、我按的表情、我送出的檢舉。
- 留下的（作者變成「已刪除的帳號」，查不回本人）：我在群組寫的留言、公開與群組的討論主題與回覆。AI 用量紀錄只留沒有內容的計數（做帳用），不再連到這個人。
- 我擁有的群組：轉給最早的 admin，沒有就轉給最早加入的成員，沒有其他成員就刪除群組（連同它的內容）。
- 正在停權公開發言的帳號刪除後，停權紀錄保留一個不可逆的識別雜湊（Discord 帳號），同一個 Discord 帳號重新註冊時停權仍然有效（到期為止）。
- 刪除在一個資料庫交易裡完成；失敗就整個不做（500），不會刪一半。

### 條款版本

- 伺服器設定 `TERMS_VERSION`（例如 `2026-11-13`；沒設定＝不啟用這一段）。帳號建立時記錄當時的版本與時間。
- `GET /me` 多 `terms_version_accepted: string | null`、`terms_version_current: string | null`。兩者不同時，前端在登入後顯示一行說明＋連結＋「知道了」。
- 那一行寫什麼（2026-11-13）：`GET /me` 另有 `terms_effective_date: "YYYY-MM-DD" | null`（`TERMS_EFFECTIVE_DATE`，新版從哪一天生效）與 `terms_summary: string | null`（`TERMS_SUMMARY`，改了什麼的一句話，一行、最多 120 字）；沒啟用版本時兩個都是 null。前端：生效日還沒到「12/1 起適用新版服務條款與隱私權政策：〈摘要〉。」；到了或過了「服務條款與隱私權政策在 12/1 更新：〈摘要〉。」；都沒填「服務條款與隱私權政策已更新。」
- `POST /me/terms-accept` `{"version": "<terms_version_current>"}` → `User`（版本不是目前的 → 409 `terms_version_mismatch`）。
- 前端頁面：`/terms`、`/privacy`（不用登入就能讀；內容來自 `docs/legal/` 的兩份文件；文件裡還有【待填】時頁面頂端標示「草稿」）。登入頁寫「登入即表示你同意〈服務條款〉與〈隱私權政策〉」並連過去；
  未登入的公開頁頁尾、設定頁也有連結。

## 收盤價的標示與盤中狀態（2026-11-13）

產品負責人決定：**不做盤中即時報價**（合法來源要付費，調查見 `docs/research/quote-refresh-terms.md`），維持收盤後資料，但要讓人看得出來「這不是即時價格」。

- `GET /meta/market-status`（不讀使用者資料，不用登入）：
  ```jsonc
  { "tw": { "date": "2026-11-13",          // 台北時間的今天
            "is_trading_day": true,         // 依官方行事曆
            "is_open": true,                // 交易日 09:00（含）到 13:30（不含），台北時間
            "open": "09:00", "close": "13:30" } }
  ```
- 報價的 `as_of` 是那個收盤價所屬交易日的收盤時間；商用模式 `is_realtime` 一律 `false`。
- **前端的三種狀態**（台股與台股 ETF；用 `market-status` 和報價的 `as_of` 日期判斷）：
  1. **盤中**（`is_open`）：價格標「收盤價・11/12（四）」，下面一行「盤中不更新・到證交所看即時報價 ↗」（不重複日期；連結
     `https://mis.twse.com.tw/stock/detail-item?id=<tse|otc>_<代號>.tw&ex=<tse|otc>&lang=zhHant`——上市 `tse`、上櫃 `otc`；產品負責人 2026-11-13 提供並確認的格式；另開新視窗；只是連結，不擷取）。
     漲跌（▲50 ▲4.83%）是那個收盤日的漲跌，和帳本一樣標上日期，不讓人以為是今天的。
  2. **收盤後、今天的收盤價還沒公布**（今天是交易日、已過 13:30、`as_of` 的日期早於今天）：一行「今天的收盤價還沒公布」，漲跌同樣標日期。
  3. **其他**（最新收盤價已經進來，或今天不是交易日）：只標「收盤價・11/13（五）」，不加說明。
  - 帳本主數字旁的時間同樣三種寫法（「11/12 收盤・盤中不更新」「11/12 收盤・今天的還沒公布」「11/13 收盤」）。
  - 「今日」損益與「今日漲跌」只有在收盤價的日期就是今天時才寫「今日」，否則寫那個日期（「11/12」）。
  - 資料來源頁固定一段：沒有盤中即時報價、價格是收盤後公布的收盤價、要看盤中請到證交所「基本市況報導」、合法取得盤中報價需要付費授權。
- **後端：收盤價公布偵測**。證交所與櫃買的收盤檔公布時間不固定（觀察到晚上到隔天清晨）。交易日 13:35 起到隔天 08:30，每 15 分鐘用很小的請求
  （條件式請求或只看檔頭）檢查上市、上櫃的收盤檔有沒有換成當天的；一換就抓進來並更新報價，兩個市場都拿到後停止。照既有的每主機頻率限制，不碰證交所網站與 MIS。

## 市場頁（2026-11-13）

登入後的「市場」頁（`/market`；首頁仍是帳本）。只有**收盤後的官方資料**：沒有盤中、沒有海外指數、美股與加密貨幣。每一塊自己帶日期（上市、上櫃、期貨、匯率公布的時間不同）；沒有的區塊是 `null`／空陣列，不補假資料。

| 方法 | 路徑 | 回應 |
|---|---|---|
| GET | `/market/overview` | 見下方（要登入；不讀個人資料，授權查看時照常回應） |

```jsonc
{
  "as_of": "2026-11-12",                       // 指數與排行裡最新的日期；什麼都沒有時 null
  "indices": [                                 // 依序：加權指數、櫃買指數、台指期近月（授權開了才有）、美元兌新台幣
    { "key": "taiex", "name": "加權指數", "unit": "點", "value": 27270.34, "change": 318.55, "change_pct": 0.0118,
      "date": "2026-11-12",                    // 這一項自己的日期
      "sparkline": [{ "t": "2026-10-16", "v": 26120.5 }] }  // 最多 20 個收盤，舊到新；不到 2 點前端不畫
  ],
  "summary": {                                 // 全站共用的 AI 收盤重點；沒有時 null
    "date": "2026-11-12", "headline": "加權指數收漲 1.18%，半導體類股領漲",   // headline 可能是 null
    "points": [{ "text": "…", "sources": [{ "url": "https://…", "title": "報導標題", "outlet": "中央社" }] }]
  },
  "sectors": { "date": "2026-11-12", "items": [{ "name": "半導體", "index_name": "半導體類指數", "close": 912.3, "change_pct": 0.0312 }] },  // 由高到低
  "movers": {
    "date": "2026-11-12", "prev_date": "2026-11-11", "count": 1088,           // 上市與上櫃都已公布的最新一天；列入排行的普通股檔數
    "gainers": [{ "symbol": "2330.TW", "code": "2330", "name": "台積電", "market": "TWSE", "close": 1085, "change": 50, "change_pct": 0.0483, "volume": 30000000 }],
    "losers": [], "volume": []                                                 // 各最多 10 檔；volume 的單位是股
  },
  "announcements": { "date": "2026-11-12", "total": 770,                       // 最新一天的重大訊息；total 是當天全部
    "items": [{ "symbol": "2330.TW", "code": "2330", "name": "台積電", "title": "…", "time": "17:30", "url": null }] },  // 新的在前，最多 30 則
  "is_demo": false, "notes": [], "sources": ["臺灣證券交易所〈…〉（2026），依政府資料開放授權條款第 1 版"]
}
```

- **排行只列普通股**（四碼、不是 00 開頭）：ETF、特別股、權證不列。漲跌幅以當天的官方參考價為準（除權息日），沒有參考價才用前一個交易日的收盤價；超過 ±11% 的不列（不是漲跌幅限制內的變動）。
- **排行的日期**是上市與上櫃**都**已公布收盤價的最新一天（兩邊公布的時間不同，只排一半的市場會誤導）。
- **AI 收盤重點**：每個交易日一則、所有人看到同一則，不計入任何人的 AI 額度。每一點的 `sources` 都是模型實際收到的搜尋結果，而且至少一則的日期是那個交易日（或之後三天內）；通過檢查的不到兩點就整塊不提供。沒有金鑰、關掉網路搜尋或 `AI_MARKET_SUMMARY_ENABLED=false` 時一律 `null`。
- 台指期近月是期交所「授權待確認」的資料集：`TAIFEX_CONDITIONAL_CONFIRMED=true` 才會出現在 `indices`。

## 討論串（2026-11-13）

產品負責人的決定見 `PRODUCT.md`「討論與彈幕」。討論串有：**範圍**（公開／群組）、**公開暱稱**、**檢舉與站方管理**、**發言頻率限制**。
線圖留言（彈幕）與指數頁**暫緩**（產品負責人 2026-11-13：先不做），設計保留在本節最後，**不要實作**。

### 共通規則

- **範圍 `scope`**：`"public"`（所有人）或 `"group"`（某個群組的成員；帶 `group_id`）。群組範圍的內容：不是成員一律 404 `not_found`（和 M5 相同）；
  離開群組後看不到，自己發過的留在群組裡。
- **誰能讀**：公開的**討論主題與回覆不用登入就能讀**（`GET`，沒有 session 時 `mine`／`can_*` 都是 `false`、`my_reactions` 為空）。
  其餘（發言、表情、檢舉、群組範圍、`scope=all`）都要登入，否則 401。
- **誰能寫**：登入的使用者本人。查看別人資產（`X-Forliosa-View-As`）時這一節的端點**一律以登入者本人**為準，不受查看模式影響；前端在查看模式擋下討論頁（和群組一樣）。
- **作者 `Author`**：
  - 公開範圍：`{"name": "公開暱稱", "is_you": false}`。**不含** `user_id`、顯示名稱、頭像、email（測試要逐項證明）。
  - 群組範圍：`{"name": "顯示名稱", "is_you": false, "user_id": "usr_…", "avatar_url": null}`（和群組動態相同）。
  - 帳號刪除後 `name: null`（前端顯示「已刪除的帳號」）；內容保留。
- **公開暱稱**：`users.public_name`，2–20 字、一行（規則同顯示名稱，另外不能只有空白、前後空白去掉）、不分大小寫與全半形唯一（409 `public_name_taken`）；
  不能是保留字（`forliosa`、`官方`、`管理員`、`站方`、`admin`、`system`，不分大小寫，含這些字也不行）。第一次設定不算；之後每改一次要等 7 天才能再改（409 `public_name_cooldown`，帶 `retry_after_days`）——打錯字可以馬上改一次。
  沒設定就發公開內容 → 409 `public_name_required`。改名後舊貼文顯示新暱稱。
  - `GET /users/me` 多 `public_name: string | null`、`is_admin: boolean`、`public_posting_suspended_until: string | null`（ISO 時間；永久為 `"9999-12-31T00:00:00Z"`）、`public_posting_suspended_reason: string | null`（站方暫停時寫的原因，只有本人看得到；沒寫是 null。403 `posting_suspended` 的錯誤也多帶 `reason`）。
  - `PUT /users/me/public-name` `{"public_name"}` → `User`。
- **內文**：純文字。主題內文 1–5000 字、回覆 1–2000 字，可換行（CRLF 轉 LF、連續空行最多 2 個、去掉行尾空白）；標題 1–80 字、一行；
  控制字元與看不見的格式字元（同名稱規則，換行除外）→ 422。不支援 Markdown、圖片；前端把 `http(s)://` 網址變成連結
  （`target="_blank" rel="nofollow ugc noopener noreferrer"`）。
- **狀態 `status`**：`"visible"`｜`"hidden"`（站方隱藏）。隱藏的主題不出現在任何清單（包括作者自己的 `mine=true`）；直接打開回 `status: "hidden"`、`body: null`、`title: "（已被站方隱藏的主題）"`、`symbols: []`（作者本人與站方管理員仍拿得到原本的標題、標記與內文）；回覆仍可讀、不能再回覆。
  隱藏的回覆留在原位、`body: null`。
- **刪除**：作者可刪自己的；群組範圍另外允許群組 owner／admin。刪主題連同回覆、表情、檢舉一起刪。站方管理員不刪公開內容，只隱藏。
- **表情**：和群組相同的六個（👍🎉🔥😮😢👀）；`reactions: [{"emoji","count","mine"}]`。
- **頻率限制**（每位使用者；超過回 429 `rate_limited`，帶 `retry_after_seconds`）：
  - 公開：主題 5 則／天；回覆 30 則／小時；任兩則公開發言至少間隔 10 秒。
  - 群組：主題 20 則／天；回覆 120 則／小時。
- **公開發言停權**：停權中發公開內容 → 403 `posting_suspended`（帶 `until`）；群組發言不受影響。
- **AI 不讀這些內容**：AI 工具不讀討論，也不替使用者發言。
- 錯誤代碼新增：`public_name_required`、`public_name_taken`、`public_name_cooldown`、`posting_suspended`、`rate_limited`（429）、`topic_hidden`（409）、`unknown_symbol`（422）。
  附帶欄位放在 `error` 物件裡、和 `code`／`message` 同一層：`rate_limited` → `error.retry_after_seconds`（另有 `Retry-After` 標頭）；`posting_suspended` → `error.until`；`public_name_cooldown` → `error.retry_after_days`（1–7）。
- **實作細節（後端 2026-11-13）**：
  - 這一節的時間是 UTC、結尾 `Z`、到秒（其他端點仍是 `+08:00`）。
  - 個人資料端點原本是 `GET /me`；`GET /users/me` 是同一個回應的別名，兩個都多了三個欄位。
  - 公開範圍的 `author` 只有 `name` 與 `is_you` 兩個鍵（沒有 `user_id`、`avatar_url`，不是 `null`）。群組範圍裡已離開群組的作者是 `{"name": "已離開的成員", "is_you": false, "user_id": null, "avatar_url": null}`。
  - 表情的 `PUT`／`DELETE` 回 204、沒有內容，前端自己更新或重新讀取。
  - `can_reply` 只表示「已登入而且主題沒被隱藏」；沒有公開暱稱或被停權時，送出才會收到 409／403。
  - 頻率限制用滾動的 24 小時／60 分鐘計算；刪掉貼文不會把額度還回來。檢舉也有限制：每人每小時 20 則新的檢舉（429）。
  - 沒登入用 id 打開群組主題回 404（不透露存在）；沒登入列 `scope=group`／`all` 或 `mine=true`、以及所有寫入回 401。
  - `scope=public` 卻帶 `group_id` → 422；清單的 `group_id` 只有 `scope=group` 時有效（而且必填）。內文裡的 Tab → 422。
  - `/admin/*`：沒登入 401、登入但不是管理員 404。停權的 `days` 必填，永久要明確傳 `null`；對已停權的人再停權是更新同一筆。
  - 管理員的檢舉清單依最近一次檢舉排序；`report_count`、`reasons`、`notes` 含已處理的；新的檢舉會把已處理的對象重新打開；主題的 `excerpt` 是「標題｜內文」。

### 討論主題與回覆

| 方法 | 路徑 | 誰 | 說明 |
|---|---|---|---|
| GET | `/discussions/topics?scope=public\|group\|all&group_id=&symbol=&mine=&sort=active\|new&limit=30&cursor=` | 公開：任何人；其餘登入 | `{"items": TopicSummary[], "next_cursor"}`。`scope=all`＝公開＋我所有群組的；`symbol` 只列標記那檔的；`mine=true` 只列我發的；`sort=active`（預設，依最後回覆時間）或 `new` |
| POST | `/discussions/topics` | 登入 | `{"scope", "group_id"?, "title", "body", "symbols"?: string[]}`（最多 5 檔，必須是商品主檔裡的代號）→ `Topic`（201） |
| GET | `/discussions/topics/{id}` | 同清單 | `Topic` |
| DELETE | `/discussions/topics/{id}` | 作者；群組 owner／admin | 204 |
| GET | `/discussions/topics/{id}/replies?limit=50&cursor=` | 同清單 | 舊到新，`{"items": Reply[], "next_cursor"}` |
| POST | `/discussions/topics/{id}/replies` | 登入（看得到這個主題） | `{"body"}` → `Reply`（201）。隱藏的主題不能回覆（409 `topic_hidden`） |
| DELETE | `/discussions/replies/{id}` | 作者；群組 owner／admin | 204 |
| PUT | `/discussions/reactions` | 登入 | `{"target": "topic:<id>"\|"reply:<id>", "emoji"}`（重複呼叫不重複計）→ 204 |
| DELETE | `/discussions/reactions?target=&emoji=` | 登入 | 收回自己的表情 → 204 |

```jsonc
// TopicSummary
{
  "id": "top_…", "scope": "public", "group": null,            // 群組範圍：{"id": "grp_…", "name": "家族投資"}
  "title": "0050 要不要改買 006208？", "excerpt": "內文前 120 字（去掉換行）",
  "symbols": [{"symbol": "0050.TW", "code": "0050", "name": "元大台灣50"}],
  "author": {"name": "阿土伯", "is_you": false},
  "created_at": "2026-11-13T02:10:00Z", "last_activity_at": "2026-11-13T04:31:00Z",
  "reply_count": 12, "status": "visible", "mine": false
}
// Topic = TopicSummary（沒有 excerpt）＋
{ "body": "…", "reactions": [{"emoji": "👍", "count": 3, "mine": true}], "can_delete": false, "can_report": true, "can_reply": true }
// Reply
{ "id": "rep_…", "topic_id": "top_…", "body": "…", "author": {…}, "created_at": "…", "status": "visible",
  "reactions": [], "mine": false, "can_delete": false, "can_report": true }
```

- `can_report`：公開範圍、登入、不是自己的內容才是 `true`。群組範圍沒有檢舉（由群組管理員刪除；站方看不到群組內容）。

### 檢舉與站方管理（只管公開內容）

| 方法 | 路徑 | 誰 | 說明 |
|---|---|---|---|
| POST | `/discussions/reports` | 登入 | `{"target": "topic:<id>"\|"reply:<id>", "reason": "spam"\|"solicitation"\|"abuse"\|"other", "note"?: ≤300 字}` → 204。同一人對同一則重複檢舉只算一次；不能檢舉自己的、不能檢舉群組範圍的（422） |
| GET | `/admin/discussions/reports?status=open\|resolved&limit=30&cursor=` | 站方管理員 | 依對象彙整：`{"items": [{"target", "kind", "excerpt", "author_name", "topic_id", "report_count", "reasons": {"spam": 2, …}, "notes": string[], "first_reported_at", "status", "hidden": bool}], "next_cursor"}` |
| POST | `/admin/discussions/moderation` | 站方管理員 | `{"target", "action": "hide"\|"unhide"\|"dismiss"}`：`hide` 隱藏並把檢舉標為已處理；`dismiss` 不隱藏、標為已處理 → 204 |
| GET | `/admin/discussions/suspensions` | 站方管理員 | 目前停權中的：`[{"id", "public_name", "until", "reason", "created_at"}]` |
| POST | `/admin/discussions/suspensions` | 站方管理員 | `{"target": 某一則公開內容, "days": 1\|7\|30\|null（永久）, "reason"?}` 停權那則內容的作者 → 201 |
| DELETE | `/admin/discussions/suspensions/{id}` | 站方管理員 | 解除 → 204 |

- 站方管理員：環境變數 `ADMIN_EMAILS`（逗號分隔的 email，不分大小寫）。不是管理員呼叫 `/admin/*` → 404 `not_found`。
- 管理端點不回傳 email、`user_id`；用「某一則內容」指定作者。
- 每個公開討論頁底部，前端固定一行：「使用者言論，不代表本站立場，也不是投資建議。」

### 管理後台：總覽與新聞下架（2026-11-14）

前端 `/admin`（總覽）、`/admin/discussions`（上面的檢舉與停權）、`/admin/news`（新聞下架）。權限和上面一樣：沒登入 401、不是站方管理員 404（在驗證本文之前）；
查看別人的資產（`X-Forliosa-View-As`）時讀取 403 `view_as_not_allowed`、寫入 403 `read_only`。不回傳 email、`user_id` 或金鑰。

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/admin/overview` | `{"users": {"total", "new_7d"}, "ai": {"month": "2026-11", "slots": [{"slot", "configured", "state", "retry_in_seconds", "workspace_id", "month_cost_usd", "month_calls", "monthly_budget_usd", "threads", "last_error"}]}, "datasets": [{"key", "name", "agency", "data_date", "fetched_at", "days_behind", "stale"}], "history_backfill": {"enabled", "rows", "pending", "symbols": {"done", "not_found", "mismatch", "no_overlap", "error"}}}` |
| GET | `/admin/news/blocked-domains` | `[{"domain", "reason", "created_at", "from_env"}]`：存在資料庫的（新的在前），再來是只寫在 `NEWS_BLOCKED_DOMAINS` 的（`created_at` null、`from_env` true） |
| POST | `/admin/news/blocked-domains` | `{"domain", "reason"?: ≤200 字}` → 201 `{"domain", "deleted_headlines"}`：網域正規化（小寫、網址只取主機、去掉 `www.`），封鎖它與子網域並刪掉已存的標題；不是網域 → 422 |
| DELETE | `/admin/news/blocked-domains/{domain}` | 解除 → 204；寫在 `NEWS_BLOCKED_DOMAINS` 的 → 409 `set_in_environment`；不在清單 → 404。刪掉的標題不會回來 |

- `ai.month` 是 UTC 月份（金鑰的預算以 UTC 月計）；`state` 和 `/ai/admin/keys` 相同，多一個 `not_configured`。
- `datasets` 是 `dataset_status` 的每一列，最久沒有新資料的在前；`stale`：最新資料落後今天 3 個交易日以上（沒有資料也算）；`days_behind` 是日曆天。

### 暫緩：線圖留言（彈幕）與指數頁（設計保留，未實作）

> 產品負責人 2026-11-13 決定先不做彈幕；指數頁原本是為了大盤彈幕才加的，一起暫緩。以下是當時談定的設計，之後要做時從這裡開始。
> 當時的決定：獨立的 30 字短句；股票、ETF、大盤與指數的線圖都有；即時（看線圖時別人剛發的會飛過，第一版用輪詢）；打開線圖時最近 30 天內最新的 20 則飛一輪就停；
> 開關「關｜群組｜全部」預設群組；線圖下方有清單（檢舉、刪除在這裡，減少動態效果時只看清單）；不做「播放」；檢舉對象多一種 `chart_comment:<id>`；
> 頻率限制：公開 1 則／10 秒且 60 則／天，群組 1 則／3 秒且 300 則／天。

#### 線圖留言（彈幕）

每一檔商品（股票、ETF、指數）一個房間，鍵是 `symbol`。一則是一句 1–30 字、一行、**不能含網址**（`http`、`www.`、`://` → 422）的短句，沒有標題、不能回覆、沒有表情。全部要登入。

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/chart-comments?symbol=&scope=groups\|all&after=&before=&limit=` | `{"items": ChartComment[], "cursor", "poll_after_seconds": 3}`。`scope=groups`＝我所有群組的；`all`＝再加公開的。三種用法：① 不帶 `after`／`before`：最近 30 天內最新的 `limit`（預設 20、最多 50）則，**舊到新**（打開線圖時飛一輪）；② `after=<cursor>`：這之後新發的（輪詢，沒有新的就回空陣列與同一個 `cursor`）；③ `before=<id>`：更舊的（線圖下方清單「看更多」，新到舊，不限 30 天） |
| POST | `/chart-comments` | `{"symbol", "body", "scope": "public"\|"group", "group_id"?}` → `ChartComment`（201） |
| DELETE | `/chart-comments/{id}` | 作者；群組 owner／admin → 204 |

```jsonc
// ChartComment
{ "id": "cc_…", "symbol": "2330.TW", "body": "法說會前先抱著", "scope": "group", "group": {"id": "grp_…", "name": "家族投資"},
  "author": {"name": "爸爸", "is_you": false, "user_id": "usr_…", "avatar_url": null},
  "created_at": "2026-11-13T04:31:02Z", "mine": false, "can_delete": false, "can_report": false }
```

- **即時**：第一版用輪詢——前端在線圖看得見、分頁在前景、彈幕開著時，每 `poll_after_seconds` 秒帶 `after` 問一次；之後流量大了再換 SSE，不改資料格式。
- `cursor` 是不透明字串（依建立時間＋id），前端原樣帶回。

#### 指數頁

- 商品主檔多兩檔 `type: "index"`：`^TAIEX`（發行量加權股價指數，`market: "TWSE"`）、`^TPEX`（櫃買指數，`market: "TPEx"`）；搜尋找得到（「大盤」「加權」「櫃買」也找得到）。
- `GET /instruments/{symbol}` 與 `GET /instruments/{symbol}/prices?range=` 對指數可用：收盤、漲跌點數與幅度、日線（來自已存檔的 MI_INDEX／tpex_index；存檔不足時照常回 `notes`「資料累積中…」）。
  沒有成交量、基本面、估值、籌碼、股利、新聞、法人觀點、相關股票（這些端點對指數回 404 `not_found` 或空清單，前端不顯示那些分頁）。
- 指數不能交易、不能加進持倉；可以加進觀察、可以當討論主題的標記、可以有線圖留言。
- 顯名聲明沿用 MI_INDEX／tpex_index 的資料集（`sources`）。

### 每日收盤簡報（2026-11-14）

開關是偏好 `daily_briefing`（`PATCH /me/preferences`，預設 `false`）。worker 在收盤資料存好之後，替打開的人每個交易日寫一則；`AI_DAILY_BRIEFING_ENABLED=false` 整個停掉。

```json
// Briefing
{
  "id": "brf_…",
  "date": "2026-11-12",              // 說的是哪一個交易日
  "created_at": "2026-11-12T22:20:31+08:00",
  "read": false,
  "facts": {                          // 規則算的，不經過模型；只用官方收盤價
    "market_value": 3707922, "day_change": 78015, "day_change_pct": 0.0215,
    "holdings": 9, "unpriced": 3,     // unpriced：沒有收盤價的持股（例如美股），不在當日的數字裡
    "gainers": [{"symbol": "2330.TW", "name": "台積電", "close": 1085, "change_pct": 0.0483}],
    "losers": [ … ], "watchlist": [ … ],   // 漲跌最多的持股各 2 檔；觀察清單裡漲跌 3% 以上的最多 3 檔
    "upcoming": [{"date": "2026-11-18", "type": "ex_dividend", "symbol": "00878.TW", "title": "00878 除息", "amount_estimate": 7293}],
    "is_demo": false
  },
  "points": [                         // AI 依報導補的，最多 3 點，可以是空的；格式同市場頁的收盤重點
    {"text": "…", "sources": [{"url": "https://…", "title": "…", "outlet": "…"}]}
  ]
}
```

## 取消「只記持股」、查某一天的收盤價（2026-11-14）

產品負責人決定（像 Google 財經：每一筆買進都有日期）：拿掉帳戶的「只記持股」追蹤模式；記一筆買進時選了日期，價格欄下顯示「那天收盤」，點一下填入。
實作細節見 [`apps/api/CONTRACT_NOTES.md`](../apps/api/CONTRACT_NOTES.md)「2026-11-14 取消「只記持股」、查某一天的收盤價」。

**帳戶**

- `Account` 沒有 `tracking_mode`；每個帳戶都是逐筆記交易。`GET`／`PUT /accounts/{id}/holdings` 移除（404）。
- `POST /accounts`、`PATCH /accounts/{id}` 的 body 仍容許 `tracking_mode`（舊分頁會送）：`"transactions"` 忽略；`"holdings"` 回 422
  `tracking_mode_removed`，`message`「「只記持股」已經取消，每一筆買進都要記日期。」；其他值照常是 422 `validation_error`。
- 舊資料（migration `0018`，只做一次、不能還原）：有快照的「只記持股」帳戶，快照日（含）以前的交易刪除（帳本本來就不算它們，快照已經反映），
  每一檔快照變成一筆**快照日的買進**：股數＝快照股數、`price`＝快照均價、手續費與稅 0、`source: "manual"`、`note`「由「只記持股」轉入」。
  持股、成本、已實現損益與自動入帳的股利都和轉換前一樣。
- **會變的**：績效以前從快照日的收盤市值開始算，現在那筆買進以均價成本投入，所以**快照日那天的報酬包含從均價到當天收盤的差距**；使用者把那筆
  買進改成真正的日期與價格（持倉展開後每一筆都能改日期）就會正確。這幾筆買進是一般交易：在群組的交易動態裡會以快照日的買進出現。

**某一天的收盤價**

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/instruments/{symbol}/close?date=YYYY-MM-DD` | `{"symbol", "date", "close": number \| null, "currency"}` |

- 只讀自建存檔的官方收盤（證交所／櫃買開放資料，依資料政策），**不讀 Yahoo Finance 的歷史回補**（那批只給走勢圖、技術指標、走勢小圖）、
  不即時向上游查。那一天沒有收盤列時 `close` 是 `null`、仍回 200：週末、休市日、存檔開始以前、還沒存檔的今天、美股。
- `symbol` 可以只給代號（`2330`），回應是完整代號；查不到商品 404 `not_found`。`date` 缺少、格式錯或晚於今天（台北）回 422。
- 要登入；查看別人資產（`X-Forliosa-View-As`）時忽略標頭（不讀使用者資料）。

## 2026-11-14 全站 review 的修正

實作細節見 [`apps/api/CONTRACT_NOTES.md`](../apps/api/CONTRACT_NOTES.md)「2026-11-14 全站 review 的修正」。

- **交易日期的範圍**：`POST /transactions` 與 `PATCH /transactions/{id}` 的 `trade_date` 只收 1990-01-01 到今天（台北），其他回 422（「日期太早（1990 年以前）」「日期不能在未來」）。定期定額的草稿（`POST /recurring/{id}/draft`）仍然可以是未來的扣款日，但要到那一天才能簽名入帳。
- **PATCH 不能清空必填欄位**：`account_id`、`type`、`trade_date`、`currency`、`is_day_trade`、`note`、`source` 送 `null` 回 422（原本 500）。數量、價格、金額等選填的數字仍可送 `null`。
- **買賣的金額**：`buy`／`sell` 的 `amount` 一律是 `quantity × price`（送來的 `amount` 不用）：帳本本來就這樣算，試算與持股不會對不起來。
- **減資的退還股款**：有每股退還股款（`price`）時，`amount` 照當時的持股算，每次修改都重算；帳本重播時也照重播當時的持股算。只給總金額（沒有 `price`）時照填的金額。
- **當沖**：當沖賣出（`is_day_trade: true`）配對**同一天、同帳戶、同一檔的買進**（不論那筆買進有沒有標當沖），剩下的當天買進在收盤後併進庫存。
- **同一天的買賣順序**：同一天的買進與一般賣出照記錄的先後算（先賣後買，賣出用原本的均價）；當沖賣出排在當天的買進之後。
- **減資或反分割後沒有股票**：剩下的成本記成已實現損失（`RealizedEvent` 的 `kind: "trade"`、股數 0），之後的買進是新的成本。美股分割保留零股。
- **績效基準的配股**：股票基準（例如 0050）遇到除權（配股 X 元）時，股數乘以 1 + X/10，不再算成一天大跌。
- **`GET /instruments/{symbol}/history` 收指數**：`^TAIEXTR`、`^TPEXTR` 回收盤的走勢（`o`＝`h`＝`l`＝`c`，`v` 是 0）；沒有資料時 `candles` 是空的，`notes` 寫「沒有 發行量加權股價報酬指數 的資料，不能比較」。原本回 404，個股頁的「比較：加權報酬指數」畫不出線。
- **5 日走勢**（`range=5D`）：往前找一個月，取最後 5 個交易日（過年後原本只有 0–4 天）。
- **AI 每天的提問次數**：`GET /ai/usage` 的 `messages_today` 改從 `ai_questions` 算（每問一題一列，刪掉對話也還在），刪除對話不會把當天的次數還回去。
- **中斷的 AI 呼叫也記用量**：串流到一半中斷（關掉頁面、上游出錯）時，已經用掉的 token 記一列 `ai_usage`（`stop_reason: "interrupted"`），算進每把金鑰與每個人的每月預算。
