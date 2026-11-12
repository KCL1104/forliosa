# Forliosa API（後端）

以台股為主的投資管理後端：帳本與稅費、績效（TWR／XIRR）、行情與個股資料。
技術：Python 3.13、FastAPI、SQLAlchemy 2、Alembic、Pydantic v2、httpx；以 `uv` 管理。

介面以 [`docs/api-contract.md`](../../docs/api-contract.md) 為準，執行後的 OpenAPI 在 `/api/v1/openapi.json`、
互動文件在 `/api/v1/docs`。與合約不同或合約沒寫清楚的地方記在 [`CONTRACT_NOTES.md`](CONTRACT_NOTES.md)。

## 本機開發

```bash
cd apps/api
uv sync                                   # 安裝相依套件（含 pytest、ruff）
cp .env.example .env                      # 需要時再修改；預設用 SQLite（var/forliosa.db）
uv run alembic upgrade head               # 建立資料表
uv run python -m forliosa.seed            # 建立示範使用者、兩年交易與自選（會先自動 migrate）
uv run python -m forliosa.archive run     # 選用：存一次官方開放資料（參考價、籌碼、事件、季報、集保）
uv run uvicorn forliosa.main:app --reload --port 8000
```

開發模式（`FORLIOSA_ENV=dev`）可以用開發登入取得 session cookie：

```bash
curl -c cookies.txt -X POST http://localhost:8000/api/v1/auth/dev-login \
  -H 'Content-Type: application/json' -d '{"email": "demo@forliosa.local"}'
curl -b cookies.txt http://localhost:8000/api/v1/portfolio/summary
```

前端用 `pnpm dev:web:api`（repo 根目錄）啟動時，Vite 會把 `/api` 轉給 `http://localhost:8000`（同源，不需要 CORS），
沒有 session 時自動以 `demo@forliosa.local` 開發登入。直接跨來源呼叫時，`http://localhost:5173` 已在 CORS 允許清單內，
請求要帶 `credentials: "include"`。

### 使用 PostgreSQL

```bash
DATABASE_URL=postgresql+psycopg://forliosa:forliosa@localhost:5432/forliosa uv run alembic upgrade head
```

Railway 提供的 `postgresql://…` 網址會自動換成 `postgresql+psycopg://`。金額欄位在 PostgreSQL 是
`NUMERIC(24, 8)`，在 SQLite 以文字保存（SQLite 沒有十進位型別），兩者都是精確的 `Decimal`。

### 測試與檢查

```bash
uv run pytest            # 單元測試＋API 測試（離線，只用示範資料，不連網）
uv run ruff check .      # lint
```

- `tests/domain/`：手續費、證交稅、二代健保、帳本（均價／FIFO、配股、分割、減資、當沖）、TWR／XIRR，
  每個案例都在註解寫出手算過程。
- `tests/marketdata/`：TWSE／TPEx／MIS／FinMind 解析器；fixture 是 2026-11-11 實際回應的精簡版；參考價與漲跌停。
- `tests/archive/`：官方資料集解析器與存檔工作（冪等）；fixture 是 2026-11-12 實際回應的精簡版。
- `tests/domain/test_ticks.py`：升降單位、漲跌停、除權息參考價（以證交所、櫃買公布值驗證）。
- `tests/api/`：所有端點、權限隔離（使用者只看得到自己的資料）、錯誤格式。

### 背景工作

```bash
uv run python -m forliosa.worker
```

排程（台北時間，交易日）：

| 時間 | 工作 |
|---|---|
| 09:00–13:30 每 60 秒 | 輪詢所有使用者的持股＋自選報價；`DATA_POLICY=personal` 時把盤中點存進 `intraday_points`（個股 1 日走勢、自選迷你圖） |
| 08:10、14:40 | 存檔：證交所、櫃買 OpenAPI（收盤、本益比、參考價與漲跌停、融資融券、除權息預告、注意／處置、重大訊息、股東會） |
| 21:40 | 同上，加上季報（`t187ap06`／`07`／`17`）與 personal 才有的證交所網站 T86、MI_QFIIS |
| 14:35、23:45 | 更新商品主檔，把持股與自選的真實收盤價寫入 `prices_daily` |
| 週六 10:00 | 集保股權分散表（只能下載當週，所以每週存） |

AI 相關工作在 M4 加入。

### 資料存檔與回補

證交所／櫃買 OpenAPI 只提供最新一天，所以我們每天存檔，歷史從開始存檔那天累積：

```bash
uv run python -m forliosa.archive run                      # 執行一次全部存檔（約 1 分鐘，請求間隔 ≥ 0.5 秒）
uv run python -m forliosa.archive run --only twse,tpex     # 只跑部分：twse、tpex、financials、tdcc、web
uv run python -m forliosa.archive backfill --days 90       # 回補（僅 DATA_POLICY=personal）
```

`backfill` 從證交所網站（T86 三大法人、MI_QFIIS 外資持股，每天一次請求、間隔 3 秒）與 FinMind（持股與自選逐檔：
三大法人、融資融券、外資持股；額度用完會停）回補，**不會覆蓋**官方資料列。`commercial` 沒有可回補的官方歷史來源。
每張存檔表都有 `source` 欄位，`commercial` 下查詢會略過非商用來源的資料列。

## 專案結構

```
src/forliosa/
  domain/        純計算，不碰資料庫與網路：fees.py（稅費）、ledger.py（帳本重播）、performance.py（績效）
  marketdata/    行情 provider：shioaji_data、twse（OpenAPI＋MIS）、tpex、finmind、archive_provider（自建存檔）、demo；
                 opendata.py 是官方資料集解析器，service.py 負責備援順序、合併與參考價
  archive.py     官方開放資料每日存檔與回補（CLI：python -m forliosa.archive）
  datapolicy.py  DATA_POLICY 與 sources 標示文字
  services/      交易（自動稅費＋帳本驗證）、投資組合（含本週事項）、個股資料、個股頁（stock.py）、自選
  api/           FastAPI 路由、schema、錯誤格式、session 驗證
  models.py      SQLAlchemy 資料表；alembic/ 為 migration
  seed.py        示範資料；worker.py 背景排程
```

## 計算規則（摘要）

| 項目 | 規則 |
|---|---|
| 漲跌與參考價 | 漲跌以參考價計算；除權息參考價 =（昨收 − 現金股利）÷（1 + 配股率）四捨五入到升降單位，漲跌停為未進位價 ±10% 往內取到升降單位；有官方值（TWT84U、櫃買 Next*）就用官方值 |
| 手續費（台股） | `floor(成交金額 × 0.1425% × 折扣)`；低於最低手續費以最低計（未滿 1,000 股用零股最低） |
| 證交稅（賣出） | 股票 0.3%、ETF 0.1%、當沖 0.15%（至 2027-12-31，之後回到 0.3%）、債券 ETF 停徵至 2026-12-31；元以下捨去 |
| 二代健保 | 單筆股利 ≥ NT$20,000 扣 2.11%（上限基數 1,000 萬），元以下四捨五入 |
| 美股 | 無證交稅；手續費依帳戶設定（預設 0）；股利預扣 30% |
| 配股 | 每 1 元配 0.1 股；不足 1 股以面額 10 元折付現金（計入股利） |
| 成本 | 含買進手續費；均價法（預設）或 FIFO；當沖賣出先對沖同日當沖買進 |
| TWR | `r_t = (V_t + O_t) / (V_{t-1} + I_t) − 1`，連乘；以未還原收盤價計值，股利以交易紀錄 |
| XIRR | 投資人觀點現金流＋期末市值，Newton 法，不收斂時改用二分法 |

## 資料來源與授權

**`DATA_POLICY`**（預設 `personal`）：

- `personal`：所有來源都可用；FinMind、證交所 MIS、證交所網站資料在回應的 `sources` 以「（非商用）」結尾。
- `commercial`：只用政府開放資料（證交所／櫃買 OpenAPI、集保開放資料、shioaji-data 官方檔）與自建存檔。不建立
  `twse_mis`、`finmind` provider，存檔裡的非商用資料列一律略過；新聞與盤中走勢回空資料並在 `notes` 說明。

兩種模式的主要來源都是「官方開放資料＋自建存檔」；FinMind 只做回補與備援。

`MARKET_DATA_PROVIDERS` 決定順序（預設 `twse_mis,archive,twse_openapi,tpex_openapi,shioaji_data,finmind,demo`），
前一個失敗就用下一個；失敗的來源會暫停一段時間再試。日線、本益比、股利會**合併**：存檔有的日期用存檔，缺的由下一個真實來源補；
只有完全沒有真實資料時才用示範資料。報價以最新交易日為準（例如存檔是昨天、OpenAPI 已有今天，就用今天）。
任何含模擬數據的回應都會帶 `"is_demo": true`。

| 來源 | 用途 | 授權與限制 |
|---|---|---|
| shioaji-data（GitHub raw） | 商品主檔（約 2,000 家上市櫃公司）、公司簡介、題材、每日收盤與市值、月營收、季 EPS／淨值 | 官方資料部分為政府資料開放授權條款第 1 版，**須標示來源**；AI 整理的簡介、產業鏈、題材授權「待定」，回應的 `data_sources` 會分開標示 |
| 證交所 MIS（mis.twse.com.tw） | 盤中與收盤報價 | ⚠️ **非官方 API**，偶爾回 502、可能被封鎖；**商業化前必須換成有授權的即時行情** |
| FinMind v4 | 日線（未還原）、本益比／淨值比／殖利率、股利、匯率、發行量加權股價報酬指數（績效基準 `^TAIEXTR`）、三大法人／融資融券／外資持股回補、新聞標題（personal） | ⚠️ 免費版**不可商用**（商用需 Sponsor Pro）；匿名額度很小，回應都快取在 `var/cache/finmind`，可設定 `FINMIND_TOKEN`。額度用完（402）或連線失敗時自行暫停呼叫 15／5 分鐘，期間只用磁碟快取（過期的也用），不會讓已快取的真實資料變成示範資料 |
| 證交所／櫃買中心 OpenAPI | 收盤行情、本益比、參考價與漲跌停、融資融券、除權息預告、注意／處置、重大訊息、股東會、季報；櫃買另有個股三大法人與外資持股（都只有最新一天，每天存檔） | 政府開放資料，可商用並標示來源 |
| 集保開放資料 | 股權分散表（只有當週，每週存檔） | 政府開放資料，可商用並標示來源 |
| 證交所網站（非 OpenAPI） | 上市個股三大法人（T86）、外資持股（MI_QFIIS），可指定日期 | ⚠️ 是否適用開放授權未確認，**只在 personal 使用**；請求間隔 3 秒，太快會回 HTTP 307 |
| Yahoo Finance | 未使用 | ⚠️ 條款禁止轉發，只能當個人備援，不可在本服務中提供給使用者 |
| 示範資料（demo） | 美股（AAPL、NVDA、VOO、QQQ）與所有缺資料時的備援 | 以固定種子產生的模擬走勢，`is_demo: true` |

快取放在 `var/cache/`（已列入 .gitignore）。部署時建議掛載 volume，避免每次重啟都重新抓資料、耗掉 FinMind 額度。

## 部署到 Railway

完整步驟（含 Cloudflare Pages、網域、cookie 與 CORS、第一次部署檢查清單）見 [`docs/deploy.md`](../../docs/deploy.md)。
一個 repo 建四個服務：**api**、**worker**、PostgreSQL、Redis（Redis 目前非必要）。

1. **api**：Root Directory 設 `apps/api`，Config File Path 設 `/apps/api/railway.toml`。
   Dockerfile 啟動時會先執行 `alembic upgrade head`，再以非 root 使用者在 `$PORT` 啟動 uvicorn；
   健康檢查 `/api/v1/health`。
2. **worker**：同一個 Root Directory，Config File Path 設 `/apps/api/railway.worker.toml`
   （同一個 image，啟動指令改為 `python -m forliosa.worker`；migration 只由 api 執行）。
3. 環境變數：`FORLIOSA_ENV=prod`、`DATABASE_URL`（引用 Railway Postgres）、`DATA_POLICY`（開放註冊前改 `commercial`）、
   `MARKET_DATA_PROVIDERS`、
   `FINMIND_TOKEN`（選填）；api 另需 `SESSION_SECRET`（必填，prod 沒設會拒絕啟動）、`CORS_ORIGINS`（前端網址，
   prod 不可為 `*`）、`COOKIE_DOMAIN`（選填，例如 `.example.com`；不設則是 host-only cookie）。
4. 建議為 api 與 worker 各自掛載 volume 到 `/app/var`（image 以非 root 執行，掛 volume 時設 `RAILWAY_RUN_UID=0`）。

> 注意：`FORLIOSA_ENV=prod` 時開發登入會關閉，而正式登入（Email、Google）尚未實作，
> 所以目前的正式環境還無法登入（見 CONTRACT_NOTES 的待決事項）。

## 已知限制

- 績效的日期軸取自持股實際有成交資料的日期；內建的台股休市日清單只用於示範資料與排程，
  之後由 worker 讀取證交所 `holidaySchedule`（解析器已完成）。
- 美股沒有真實資料源，全部是示範資料。
- 盤中報價目前存在 API 程序記憶體（30 秒快取）；多個 API 副本共用報價要等 Redis 版本。
- 盤中走勢點由 worker 寫入；只跑 API 不跑 worker 時 `/intraday` 沒有點。
- `commercial` 的歷史資料只能從開始存檔那天累積（見 CONTRACT_NOTES 待確認 12）。
- 只記持股帳戶在快照日期（含）之前的交易不計入；快照日以收盤市值作為期初投入，從那天開始追蹤報酬。
