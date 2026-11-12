# API 介面合約（v1 草稿）

前端（`apps/web`）與後端（`apps/api`）共用的介面定義。M1、M2 的端點在此定義；M3–M5（匯入、AI、分享）之後補上。
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
- 認證：httpOnly session cookie（`forliosa_session`）。開發環境提供 `POST /auth/dev-login`。
- 錯誤格式：HTTP 4xx/5xx，body 為 `{"error": {"code": "not_found", "message": "找不到商品"}}`。
- 分頁：`?limit=50&cursor=...`，回應 `{"items": [...], "next_cursor": "..." | null}`。
- 示範資料：任何含有模擬數據的回應都帶 `"is_demo": true`，前端必須顯示「示範資料」標示。

## 認證與使用者

| 方法 | 路徑 | 說明 |
|---|---|---|
| POST | `/auth/dev-login` | body `{"email": "...", "display_name": "..."}`；僅在 `FORLIOSA_ENV=dev` 時啟用；設定 cookie，回傳 `User` |
| POST | `/auth/logout` | 清除 session |
| GET | `/me` | 回傳 `User`；未登入回 401 |
| PATCH | `/me/preferences` | body 為 `Preferences` 的部分欄位 |

```json
// User
{
  "id": "usr_01J...",
  "email": "demo@forliosa.local",
  "display_name": "示範使用者",
  "preferences": {
    "color_convention": "tw",       // "tw" 紅漲綠跌 | "us" 綠漲紅跌
    "theme": "system",              // "light" | "dark" | "system"
    "quantity_unit": "lot",         // "lot" 以張顯示（X 張＋Y 股）| "share" 以股顯示
    "privacy_mode": false,          // true 時前端遮蔽金額與股數
    "cost_method": "average",       // "average" 移動平均 | "fifo"
    "benchmark": "0050.TW"          // 任何商品代號，或 "^TAIEXTR"（發行量加權股價報酬指數）
  }
}
```

## 券商帳戶

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/accounts` | `Account[]` |
| POST | `/accounts` | 建立 |
| PATCH | `/accounts/{id}` | 更新 |
| DELETE | `/accounts/{id}` | 刪除（連同交易） |
| PUT | `/accounts/{id}/holdings` | 「只記持股」模式：以快照覆蓋，body `{"as_of": "2026-11-11", "holdings": [{"symbol": "2330.TW", "quantity": 1500, "avg_cost": 612.5}]}` |

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
  "tracking_mode": "transactions",  // "transactions" | "holdings"
  "created_at": "2026-11-11T10:00:00+08:00"
}
```

## 商品與行情

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/instruments/search?q=台積` | 用代號或中文名稱搜尋，回傳 `Instrument[]`（最多 20 筆） |
| GET | `/instruments/{symbol}` | `InstrumentDetail` |
| GET | `/instruments/{symbol}/quote` | `Quote` |
| GET | `/quotes?symbols=2330.TW,0050.TW` | `Quote[]`（批次） |
| GET | `/instruments/{symbol}/history?range=1M` | `range`：`5D`、`1M`、`6M`、`YTD`、`1Y`、`5Y`、`MAX`；回傳 `History` |
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
  "industry": "半導體業"
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

// DividendRecord
{"year": 2026, "period": "2026Q2", "cash_dividend": 5.0, "stock_dividend": 0, "ex_dividend_date": "2026-12-11", "payment_date": "2027-01-08"}
```

## 交易

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/transactions?account_id=&symbol=&type=&from=&to=&limit=&cursor=` | 分頁，由新到舊 |
| POST | `/transactions` | 建立；`fee`、`tax`、`health_insurance` 未提供時自動計算 |
| PATCH | `/transactions/{id}` | 更新 |
| DELETE | `/transactions/{id}` | 刪除 |
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
  "source": "manual",             // "manual" | "import"
  "created_at": "2026-11-10T14:00:00+08:00"
}

// TradePreview
{"gross": 1070000, "fee": 426, "tax": 0, "health_insurance": 0, "net_cash": -1070426, "rules": ["手續費 0.1425% × 2.8 折", "證交稅：買進免稅"]}
```

## 投資組合

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/portfolio/summary?account_id=` | `PortfolioSummary`（不帶 `account_id` 為全部帳戶） |
| GET | `/portfolio/holdings?account_id=` | `Holding[]` |
| GET | `/portfolio/performance?range=1Y&benchmark=0050.TW&account_id=` | `Performance`；`range`：`1D`、`5D`、`1M`、`3M`、`6M`、`YTD`、`1Y`、`ALL`（`1D`／`5D` 以交易日計，第一點是基準收盤）；`benchmark` 省略時用使用者偏好，可為任何商品或 `^TAIEXTR` |

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
- 每日報酬：`r_t = (V_t + O_t) / (V_{t-1} + I_t) - 1`
  - `I_t`（流入，視為開盤前發生）：當日買進成本（含手續費）。
  - `O_t`（流出，視為收盤後發生）：當日賣出淨收入（扣手續費與證交稅）、收到的現金股利（扣二代健保）。
  - 分母為 0 時 `r_t = 0`。
- TWR：`∏(1 + r_t) - 1`。
- XIRR：投資人觀點的現金流（買進為負、賣出與股利為正，期末市值為正），以年化內部報酬率求解。
- 最大回撤：以 `twr_index` 計算。
- 價格一律用**未還原**收盤價；股利以交易記錄，避免重複計算。

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
| GET | `/instruments/{symbol}/overview` | `{open, high, low, prev_close, reference_price, limit_up, limit_down, volume, avg_volume_3m, market_cap, pe, pb, dividend_yield, last_cash_dividend, ex_dividend_date, eps_ttm, high_52w, low_52w, shares_outstanding, status: {attention, disposition, note}, as_of, sources, is_demo}`；欄位缺資料時為 `null` |
| GET | `/instruments/{symbol}/intraday` | `{symbol, date, prev_close, reference_price, points: [{t: "09:01", price, volume}], is_partial, sources}`；只有持股與自選會累積盤中點（每 30–60 秒輪詢），其他回 `points: []` |
| GET | `/instruments/{symbol}/chips?range=3M` | `{institutional: [{t, foreign, trust, dealer, total}]（單位：張）, margin: [{t, margin_balance, short_balance}]（張）, foreign_holding_pct: [{t, pct}], major_holders: {as_of, buckets: [{level, holders, shares, pct}]} \| null, sources}` |
| GET | `/instruments/{symbol}/financials?period=quarterly\|annual` | `{periods: ["2026Q2", …], income: {revenue, gross_profit, operating_income, net_income, eps}, balance: {total_assets, total_liabilities, equity}, cashflow: {operating, investing, financing, free_cash_flow}, margins: {gross, operating, net}, sources}`；每個欄位是與 `periods` 等長的陣列，金額單位新台幣千元 |
| GET | `/instruments/{symbol}/events?mine=false` | `[{date, type, title, detail, url, mine, amount_estimate}]`；`type`：`ex_dividend`、`dividend_payment`、`earnings`、`revenue_release`、`material_info`、`attention`、`disposition`、`shareholder_meeting` |
| GET | `/instruments/{symbol}/news` | `[{published_at, title, source, url}]`（只有標題、來源、連結） |
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
| POST | `/recurring/{id}/draft?date=` | `{plan_id, scheduled_date, date, name, amount, price_as_of, transaction: {account_id, symbol, type: "buy", trade_date, quantity, price, note, source: "ai_draft"}, preview: TradePreview, is_demo, sources}`；股數 = floor(金額 ÷ 最近收盤價)（含零股），手續費另計；**不建立交易**，使用者簽名後 `POST /transactions` |
| GET | `/meta/attributions` | `{policy, notice: [授權條款第 2、3 點], datasets: [{key, agency, dataset, url, used_for, year, license, license_url, commercial, attribution}], not_used: [...]}`（不需登入） |

- `/portfolio/upcoming` 的 `type: "recurring"`：扣款日遇非交易日順延（證交所休市日），多 `plan_id`、`account_id`、`scheduled_date`；`amount_estimate` 為扣款金額。
- `/instruments/{symbol}/events`：每筆多 `estimated`、`period`；`type` 多 `investor_conference`（法說會，日期是開會當天）。`earnings`／`revenue_release` 用實際日期（重大訊息、月營收資料集第一次出現的日期），查不到才用法定期限並標 `estimated: true`。
- `/instruments/{symbol}/news`：官方公告（重大訊息、證交所新聞），每筆多 `category: "material_info" | "exchange_news" | "media"`，官方公告的 `source` 是 `"公告"`。
- `POST /transactions` 的 `source` 可為 `"ai_draft"`。

## AI（M4）

後端用 Anthropic Claude（預設 `claude-haiku-5-5`）＋我們自己的工具回答；細節與待決事項見 [`apps/api/CONTRACT_NOTES.md`](../apps/api/CONTRACT_NOTES.md)「AI（M4）」。
規則：AI 只讀**目前登入者**自己的資料（工具由伺服器帶入使用者，模型無法指定別人）；只回答投資理財、台美股、使用者的持股與 Forliosa 用法，其他要求一句話婉拒；數字與事實只來自工具結果或附引用的網路來源；**AI 從不寫入帳本**，記帳一律先產生草稿，使用者簽名後前端才 `POST /transactions`（`source: "ai_draft"`）；**免責聲明由前端固定顯示**在每則 AI 回答下方（文字取 `done.disclaimer` 或 `GET /ai/usage` 的 `disclaimer`，模型不會自己寫）；引用來源必須顯示給使用者，`grounding` 標出的句子要標「無來源」。對話、訊息與草稿在最後活動 30 天後刪除（`AI_RETENTION_DAYS`）；用量紀錄保留但不含內容。

| 方法 | 路徑 | 說明 |
|---|---|---|
| POST | `/ai/chat` | SSE 串流（`text/event-stream`）。body `{"thread_id": "thr_…" \| null, "message": "買 0050 2 張 52.4", "page": {"route": "/stock/2330.TW", "symbol": "2330.TW" \| null}, "privacy": false}`；`thread_id` 省略＝開新對話 |
| GET | `/ai/threads?limit=30&cursor=` | `{"items": [ThreadSummary], "next_cursor"}`，最近更新的在前 |
| GET | `/ai/threads/{id}` | `ThreadDetail`（別人的對話回 404） |
| DELETE | `/ai/threads/{id}` | 204；草稿保留 |
| GET | `/ai/drafts?status=pending` | `DraftCard[]`；`status`：`pending`（預設）、`signed`、`discarded`、`all` |
| PATCH | `/ai/drafts/{id}` | body `{"status": "signed", "transaction_id": "txn_…"}`、`{"status": "discarded"}`，或復原後 `{"status": "pending"}`；回 `DraftCard` |
| GET | `/ai/suggestions?route=/stock/2330.TW&symbol=2330.TW` | `Suggestions`（規則產生，不呼叫模型） |
| GET | `/ai/usage` | `Usage`（含固定的 `disclaimer`） |
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
| `grounding` | `{"items": [GroundingItem]}` | 只在這一輪用了 `web_search`／`web_fetch` 時、最後一個 `text` 之後送：沒有引用又像新聞敘述的句子，前端在該句標「無來源」（同一份也存在 `ThreadMessage.grounding`） |
| `error` | `{"code": "…", "message": "zh-TW 說明"}` | `refusal`（模型拒答；前端應**丟棄這一輪已串流的文字**，改顯示 message）、`ai_busy`、`ai_unavailable`、`ai_unreachable`、`ai_error`、`too_many_steps`、`max_tokens`、`truncated`（文字太長被截斷，已顯示的部分保留）、`internal_error` |
| `done` | `{"thread_id", "turn_id", "model": "claude-haiku-5-5", "stop_reason": "end_turn", "usage": {"input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "web_search_requests", "web_fetch_requests"}, "disclaimer": "AI 回答僅供參考，非投資建議。"}` | `usage` 是這一輪所有模型呼叫的合計；`disclaimer` 由前端固定顯示在回答下方。`stop_reason: "off_topic"`＝明顯離題、沒有呼叫模型就婉拒（`usage` 全為 0，算一則提問） |

串流開始前的錯誤用一般 JSON 錯誤格式：401；422（body 格式）；404 `not_found`（別人的或不存在的 `thread_id`）；409 `thread_too_long`（對話太長，請開新對話）；429 `ai_daily_limit`（今天的提問數已達上限，每天 50 題）／`ai_monthly_budget`（本月用量已達上限，每月 300 萬計費 token）；503 `ai_unavailable`（沒有設定 API 金鑰，或所有金鑰都失效／額度用完）。

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

// ThreadDetail（messages 依時間排序；一問一答）
{"id": "thr_…", "title": "…", "model": "claude-haiku-5-5", "created_at": "…", "updated_at": "…",
 "messages": [
   {"id": "12", "turn_id": "trn_…", "role": "user", "text": "台積電今天為什麼漲？", "citations": [], "drafts": [], "tools": [], "error": null, "at": "…"},
   {"id": "15", "turn_id": "trn_…", "role": "ai", "text": "…", "citations": [{"url", "title", "cited_text"}],
    "drafts": [DraftCard], "tools": [{"name": "web_search", "label": "搜尋網路：台積電"}],
    "grounding": [GroundingItem], "error": null, "at": "…"}
 ]}

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

// Usage（上限為 null 表示不限制）
{"date": "2026-11-12", "month": "2026-11", "messages_today": 3, "daily_message_limit": 50, "messages_remaining": 47,
 "tokens_month": 41200, "monthly_token_budget": 3000000, "tokens_remaining": 2958800, "cost_usd_month": 0.0123,
 "model": "claude-haiku-5-5", "available": true, "disclaimer": "AI 回答僅供參考，非投資建議。"}

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

`kind`（建議問題）：帳本 `onboard`、`drag`、`lift`、`dividends_next`、`concentration`；個股 `why_move`、`next_dividend`、`cost_on_river`、`add_one_lot`、`is_expensive`、`if_hold_dividend`；群組 `group_share`（與前端離線規則相同）。
