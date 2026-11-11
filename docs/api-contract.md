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
