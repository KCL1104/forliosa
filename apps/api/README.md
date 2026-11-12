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
uv run python -m forliosa.archive run     # 建議：存一次官方開放資料（收盤、參考價、籌碼、事件、營收、季報、指數、股利決議、公司資料、期交所、集保、休市日）
uv run python -m forliosa.seed            # 建立示範使用者、兩年交易、一筆出清紀錄、定期定額與自選（會先自動 migrate）
uv run uvicorn forliosa.main:app --reload --port 8000
```

預設 `DATA_POLICY=commercial`（只用可合法商用的資料，見下方「資料來源與授權」）。示範使用者的交易價格是虛構的帳本輸入；
行情只用官方開放資料與自建存檔，存檔還不夠的地方回空資料並在 `notes` 寫「資料累積中：自 YYYY-MM-DD 起存檔」。

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
- `tests/api/test_closed_rounds.py`：出清紀錄（買進 → 部分賣出 → 股利 → 全部賣出 → 再買進），數字手算。
- `tests/api/test_recurring.py`：定期定額 CRUD、官方休市日順延、本週事項、交易草稿（零股股數與手續費手算）。
- `tests/api/test_release_dates.py`：重大訊息／月營收資料集判斷實際財報、營收、法說會日期（2026-11-12 實際回應）。
- `tests/api/test_commercial_policy.py`：commercial 不出現示範資料、「資料累積中」、AI 研究欄位隱藏、seed 可用。
- `tests/marketdata/`：TWSE／TPEx OpenAPI 與 FinMind 解析器；fixture 是 2026-11-11 實際回應的精簡版；參考價與漲跌停。
- `tests/archive/`：官方資料集解析器與存檔工作（冪等）；fixture 是 2026-11-12 實際回應的精簡版。`test_taifex_parsers.py` 涵蓋期交所的
  解析陷阱（JSON／CSV 兩種回應、`NULL`／`-`、西元日期、999912／666666、夜盤、中文商品名稱）；`test_open_data_jobs.py` 涵蓋指數、
  股利決議、公司資料、除權息計算結果、期交所存檔（多日回應 upsert、保證金只在變動時新增、財報空白列不覆蓋）。
- `tests/api/test_open_data_api.py`：`/derivatives/*`（含有條件授權的開關）、`^TAIEXTR` 基準、股利決議、官方股數市值、匯率開關、`/meta/attributions`。
- `tests/domain/test_ticks.py`：升降單位、漲跌停、除權息參考價（以證交所、櫃買公布值驗證）。
- `tests/api/`：所有端點、權限隔離（使用者只看得到自己的資料）、錯誤格式。
- `tests/ai/`：以假的 Messages API（`tests/ai/fake_anthropic.py`，經由真正的 `anthropic` SDK）測 AI：SSE 事件、工具迴圈、
  金鑰槽的黏著／選槽／換槽與純文字摘要（`test_routing.py`）、範圍與婉拒（`test_scope.py`）、無來源標記（`test_grounding.py`）、
  保存期限（`test_retention.py`）、為什麼漲跌。測試永遠不會用到真的金鑰。

### 背景工作

```bash
uv run python -m forliosa.worker
```

排程（台北時間，交易日）：

| 時間 | 工作 |
|---|---|
| 08:10、14:40 | 存檔：證交所、櫃買 OpenAPI（收盤、本益比、參考價與漲跌停、融資融券、上櫃三大法人與外資持股、除權息預告、注意／處置、重大訊息、股東會、月營收、證交所新聞、ETF 基本資料、休市日、指數與報酬指數、上櫃除權息計算結果） |
| 21:40 | 同上，加上季報（`t187ap06`／`07`／`17`）、公司基本資料與股利決議（`t187ap03`、`t187ap45_L`），以及**期交所** OpenAPI（期貨／選擇權行情、三大法人、大額交易人、Put/Call 比、外幣參考匯率、保證金〔變動才存〕）與**中央銀行**〈銀行間新臺幣對美元收盤匯率〉（群組 `cbc`；第一次執行回補 2008 年起的全部歷史）。夜盤算在下一個交易日，所以不必清晨另跑 |
| 14:35、23:45 | 更新商品主檔，把持股與自選的真實收盤價寫入 `prices_daily` |
| 週六 10:00 | 集保股權分散表（只能下載當週，所以每週存）、期交所最後結算價與股票期貨／選擇權標的、停更端點檢查（`twtazu_od`、`t187ap09_L`） |
| 每天 04:20 | 刪除最後活動超過 `AI_RETENTION_DAYS`（30）天的 AI 對話、訊息與草稿（見下方「AI」） |

盤中沒有輪詢：證交所 MIS 的條款不允許程式下載，即時／延遲行情要付費授權，所以 `/intraday` 目前一律沒有點。
每次存檔後 worker 會重新載入證交所公布的休市日（`market_holidays`），交易日判斷與定期定額順延都以它為準。

### 資料存檔

證交所／櫃買 OpenAPI 只提供最新一天，所以我們每天存檔，歷史從開始存檔那天累積：

```bash
uv run python -m forliosa.archive run                      # 執行一次全部存檔（約 4 分鐘；證交所每 3 秒、櫃買、集保與期交所每 2 秒一次）
uv run python -m forliosa.archive run --only twse,tpex     # 只跑部分：twse、tpex、companies、financials、taifex、cbc、tdcc、weekly
```

只會連線到白名單內的網址（`marketdata/http.py` 的 `ALLOWED_URL_PREFIXES`）：`openapi.twse.com.tw`、
`www.tpex.org.tw/openapi`、`opendata.tdcc.com.tw`、`openapi.taifex.com.tw/v1`、shioaji-data 的 GitHub 檔案，以及 personal 明確開啟時的 FinMind。
期交所的資料端點在 Cloudflare 後面，同一個端點可能回 JSON 也可能回 CSV（快取存什麼回什麼），解析器兩種都接受（`marketdata/taifex.py`）。
User-Agent 誠實標示（不偽裝瀏覽器），遇到重新導向（例如證交所防火牆的 307）、403、429 就停，不重試到成功。
**證交所／櫃買／MIS／公開資訊觀測站的網站一律不爬**（網站條款禁止未經同意以程式下載，見
[`docs/research/data-sources-licensing.md`](../../docs/research/data-sources-licensing.md)）；原本的 T86、MI_QFIIS 網站回補與
MIS 盤中輪詢已移除，舊資料庫裡來源是 `twse-web`、`twse-mis` 的資料列在任何模式都不會被讀出。

`backfill` 只剩 FinMind（非商用），而且只有 `DATA_POLICY=personal` 並在 `MARKET_DATA_PROVIDERS` 明確列出 `finmind` 時才會執行：

```bash
DATA_POLICY=personal MARKET_DATA_PROVIDERS=archive,twse_openapi,tpex_openapi,shioaji_data,finmind,demo \
  uv run python -m forliosa.archive backfill --days 90
```

每張存檔表都有 `source` 欄位；回補資料不會覆蓋官方資料列，`commercial` 下查詢會略過非商用來源的資料列。

## AI（M4）

AI 助理用 Anthropic Claude（預設 `claude-haiku-5-5`）＋我們自己的工具；端點與事件見
[`docs/api-contract.md`](../../docs/api-contract.md)「AI（M4）」，設計細節與實測費用見 [`CONTRACT_NOTES.md`](CONTRACT_NOTES.md)「AI（M4）」。

```bash
uv run python -m forliosa.ai.smoke                 # 用真的金鑰跑兩題（持股、台積電新聞），印出用量、費用與每個金鑰槽的狀態
uv run python -m forliosa.ai.retention --dry-run   # 看看保存期限會刪掉多少；不加 --dry-run 就刪除
```

**金鑰與金鑰槽**：`CLAUDE_API_KEY_1`、`CLAUDE_API_KEY_2`、`CLAUDE_API_KEY_3`（大小寫不拘，例如 `Claude_API_KEY_1`；編號就是槽號），
每把放在各自的 Anthropic workspace，各有自己的速率限制與花費上限。只有一把時也可以用 `ANTHROPIC_API_KEY`。金鑰只從環境變數或 `.env`
讀取，不會進資料庫、日誌或任何回應（只看得到槽號 `#1`）。

- 每段對話固定用同一個槽（提示快取、thinking 區塊、網路搜尋的加密內容都只在同一個 workspace 有效）；新對話與背景工作選「餘裕」最多的槽
  （回應的 `anthropic-ratelimit-*` 標頭、本月估計花費與預算）。
- 槽遇到 401／403 會停用到重啟，429／529／5xx 會冷卻，達到花費上限會停到下個月；對話釘住的槽在 `AI_KEY_STICKY_WAIT_SECONDS`（5 秒）內
  恢復就等，否則換槽並以純文字摘要接續（不帶 thinking 與加密內容）。
- `AI_KEY_<n>_MONTHLY_BUDGET_USD`（例如 `AI_KEY_1_MONTHLY_BUDGET_USD=50`）：第 n 槽每個 UTC 月的估計花費上限（不設＝不限）。
  建議 Console 的 workspace 花費上限當硬上限，這裡設低一點，讓對話提早換到別的槽。
- 狀態：`GET /api/v1/ai/admin/keys`（dev 模式所有登入者；正式環境只有 `AI_ADMIN_EMAILS` 列出的帳號），列出每槽的狀態、本月花費、預算、
  速率標頭與被 API 拒絕而停用的伺服器工具。

**其他設定**（完整表格見 CONTRACT_NOTES）：

| 變數 | 預設 | 說明 |
|---|---|---|
| `AI_MODEL` | `claude-haiku-5-5` | `AI_MODEL_CHAT`／`AI_MODEL_WHY` 可個別覆寫 |
| `AI_DAILY_MESSAGE_LIMIT`、`AI_MONTHLY_TOKEN_BUDGET` | 50、3,000,000 | 每人每天提問數、每月計費 token（0＝不限） |
| `AI_WEB_SEARCH`、`AI_WEB_SEARCH_MAX_USES`、`AI_WEB_SEARCH_ALLOWED_DOMAINS` | `true`、3、空 | 預設不限網域，由模型判斷何時搜尋、用哪些來源（只限財經資訊） |
| `AI_WEB_FETCH_ALLOWED_DOMAINS` | （空，不限） | 產品負責人 2026-11-12 決定開放，由 AI 自行判斷；可設 `official` 只讀官方網域 |
| `AI_WHY_ENABLED` | `true` | 個股頁「為什麼漲跌」的 AI 一句話（每檔每個交易日最多一次，失敗時用規則句） |
| `AI_SCOPE_PRECHECK` | `true` | 明顯離題又沒有財經字詞的提問不呼叫模型，直接婉拒 |
| `AI_RETENTION_DAYS` | 30 | 對話、訊息、草稿在最後活動後保存幾天（0＝永久） |
| `AI_KEY_STICKY_WAIT_SECONDS`、`AI_KEY_COOLDOWN_SECONDS` | 5、60 | 見上 |
| `AI_ADMIN_EMAILS` | 空 | 正式環境可看金鑰槽狀態的帳號（逗號分隔） |

**範圍**：助理只協助投資理財、台股與美股、使用者自己的持股與交易，以及 Forliosa 的用法；寫程式、一般常識、作業、翻譯、寫作、角色扮演等要求，
用一句繁體中文婉拒並把話題帶回投資。明顯的情況（例如「幫我寫 Python 爬蟲」）在伺服器端就婉拒、不花模型費用；只要提到任何財經字詞或股票代號就交給模型判斷。

**有根據才寫**：數字與事實只能來自工具結果或附引用的網路來源；用了網路搜尋的回答中，沒有引用又像新聞敘述的句子會在 `grounding` 事件列出，
前端標「無來源」。**免責聲明**「AI 回答僅供參考，非投資建議。」由前端固定顯示（`done.disclaimer`、`/ai/usage.disclaimer`），模型不寫。

**保存期限**：對話與訊息（含網路搜尋的加密內容）、草稿在最後活動 30 天後由 worker 每天刪除；`ai_usage`（token、槽號、估計費用，不含內容）保留做帳。

**AI 從不寫入帳本**：記帳一律先產生草稿，使用者在畫面上確認後前端才 `POST /transactions`（`source: "ai_draft"`）。

## 專案結構

```
src/forliosa/
  domain/        純計算，不碰資料庫與網路：fees.py（稅費）、ledger.py（帳本重播）、rounds.py（出清回合）、performance.py（績效）
  marketdata/    行情 provider：shioaji_data、twse（OpenAPI）、tpex（OpenAPI）、finmind（personal 明確開啟才用）、
                 archive_provider（自建存檔）、demo；
                 opendata.py 是證交所／櫃買／集保資料集解析器、taifex.py 是期交所解析器，service.py 負責備援順序、合併與參考價
  archive.py     官方開放資料每日存檔與回補（CLI：python -m forliosa.archive）
  datapolicy.py  DATA_POLICY、資料集清單與 sources 顯名聲明（GET /meta/attributions）
  market_calendar.py  把存檔的證交所休市日套用到交易日計算
  services/      交易（自動稅費＋帳本驗證）、投資組合（含本週事項、出清紀錄）、個股資料、個股頁（stock.py）、期貨盤勢（derivatives.py）、自選、
                 定期定額（recurring.py）、重大訊息判讀（announcements.py）、「資料累積中」（coverage.py）
  api/           FastAPI 路由、schema、錯誤格式、session 驗證
  ai/            AI 助理：keypool（金鑰槽）、chat（工具迴圈與 SSE）、tools、prompts、scope（離題預先檢查）、grounding（無來源標記）、
                 store（對話、草稿、用量）、retention（保存期限）、why、suggestions、smoke
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

**`DATA_POLICY`**（預設 `commercial`）：

- `commercial`（預設）：只用可合法商用的資料——政府開放資料（證交所／櫃買／期交所 OpenAPI、集保開放資料、中央銀行匯率）、shioaji-data 官方檔，
  以及由它們建立的自建存檔。期交所資料集中**授權「有條件」**的（期貨／選擇權每日交易行情、每日外幣參考匯率、選擇權大額交易人、
  最後結算價、保證金、股票期貨／選擇權標的：data.gov.tw 找不到對應的開放授權資料集）照常存檔，但**不顯示**，直到產品負責人取得
  期交所書面確認並設定 `TAIFEX_CONDITIONAL_CONFIRMED=true`（預設 `false`；詢問信見 [`docs/outreach/taifex-licence-inquiry.md`](../../docs/outreach/taifex-licence-inquiry.md)）。**從不使用示範資料**：存檔還不夠時回空資料並在 `notes` 說明「資料累積中：自 YYYY-MM-DD 起存檔」。
  shioaji-data 由 AI 整理的公司簡介、產業鏈、題材（授權待定）不顯示。
- `personal`：只給開發者本人明確開啟。示範資料補缺；把 `finmind` 加進 `MARKET_DATA_PROVIDERS` 才會用 FinMind
  （回應的 `sources` 以「（非商用）」結尾）。

**任何模式都不使用**：證交所網站（`www.twse.com.tw` 的 T86、MI_QFIIS 等）、基本市況報導 MIS（`mis.twse.com.tw`）、
櫃買網站（如 `peQryDate`）、公開資訊觀測站網站——這些網站的條款禁止未經書面同意以程式下載。

**顯名聲明**：政府資料開放授權條款第 1 版要求標示提供機關、資料集名稱與年份，沒有標示視為自始未取得授權。
每個回應的 `sources` 都是這個格式，例如「臺灣證券交易所〈上市個股日本益比、殖利率及股價淨值比〉（2026），依政府資料開放授權條款第 1 版」；
`GET /api/v1/meta/attributions`（不需登入）列出所有使用中的資料集與授權條款第 2、3 點的固定文字，前端「資料來源與授權」頁直接使用。

`MARKET_DATA_PROVIDERS` 決定順序（預設 `archive,twse_openapi,tpex_openapi,shioaji_data,demo`），前一個失敗就用下一個；
失敗的來源會暫停一段時間再試。日線、本益比、股利會**合併**：存檔有的日期用存檔，缺的由下一個真實來源補。

| 來源 | 用途 | 授權與限制 |
|---|---|---|
| 證交所／櫃買中心 OpenAPI | 收盤行情、本益比、參考價與漲跌停、融資融券、除權息預告、注意／處置、重大訊息、股東會、月營收、季報、休市日、證交所新聞、ETF 基本資料、**指數與報酬指數**（`MI_INDEX`、`MFI94U`、`tpex_index`、`tpex_reward_index` → 基準 `^TAIEXTR`、`^TPEXTR`）、**上市股利決議**（`t187ap45_L`：盈餘／法定公積／資本公積分列）、**公司基本資料**（`t187ap03_L`、`mopsfin_t187ap03_O`：已發行股數 → 市值、產業、上市日）、**上櫃除權息計算結果**（`tpex_exright_daily`：官方參考價）；櫃買另有個股三大法人與外資持股（都只有最新一天，每天存檔） | 政府資料開放授權條款第 1 版，可商用，**須顯名** |
| 期交所 OpenAPI | 三大法人（5 個依日期資料集）、期貨大額交易人、臺指選擇權 Put/Call 比 → `/derivatives/overview`、AI 工具 `get_derivatives_overview` | 同上（data.gov.tw 11592–11600、11337／11338、11322） |
| 期交所 OpenAPI（有條件） | 期貨／選擇權每日交易行情（含夜盤）、每日外幣參考匯率（只存檔：USD/TWD 改用中央銀行）、選擇權大額交易人、最後結算價、保證金、股票期貨／選擇權標的 | 推定 OGDL，但 data.gov.tw 沒有個別資料集：**存檔但不顯示**，`TAIFEX_CONDITIONAL_CONFIRMED=true` 後才顯示 |
| 集保開放資料 | 股權分散表（只有當週，每週存檔） | 同上 |
| 中央銀行開放資料（`cpx.cbc.gov.tw/api/OpenData/FTDOpenData_Day`） | 〈銀行間新臺幣對美元收盤匯率〉：USD/TWD（美股換算新台幣；2008-01-02 起每個營業日） | 同上（data.gov.tw 7232） |
| shioaji-data（GitHub raw） | 商品主檔、每日收盤與市值、月營收、季 EPS／淨值 | 官方資料部分為政府資料開放授權條款第 1 版；AI 整理的簡介、產業鏈、題材授權「待定」，commercial 不顯示 |
| FinMind v4 | personal 明確開啟時：回補、新聞標題、匯率、`^TAIEXTR` | ⚠️ 不可商用（付費版也不包含原機關授權），預設不建立 |
| 示範資料（demo） | personal 的缺資料備援；commercial 只提供商品名稱清單 | 模擬資料，`is_demo: true` |
| ~~證交所 MIS、證交所網站 T86／MI_QFIIS、櫃買網站 peQryDate~~ | 已移除（2026-11-12） | 網站條款禁止程式下載 |

### commercial 下目前沒有的資料（前端請顯示誠實的空狀態）

| 資料 | 回應 | 原因／取得方式 |
|---|---|---|
| 盤中走勢 `/intraday` | `points: []`＋`notes` | 即時／延遲行情需付費授權（證交所延遲行情約 NT$30,000／月起） |
| 上市股票個股三大法人、外資持股 | `chips.institutional`／`foreign_holding_pct` 空＋`notes` | 證交所 OpenAPI 沒有；Data E-Shop 付費（約 NT$3,000／月起）或書面同意。上櫃股票有（櫃買 OpenAPI） |
| 開始存檔前的歷史（日線、本益比、法人、融資） | 只回已存檔的部分，`notes`「資料累積中：自 … 起存檔」 | 官方 OpenAPI 只給最新一天；網站回補要同意 |
| 績效 `/portfolio/performance` | 持股期間沒有每天的真實收盤價時 `series: []`＋`notes`；之後從第一個完整存檔日開始計算 | 同上 |
| 美股價格、美股績效 | `price: null`（以成本計值，`is_demo: false`）、績效空＋`notes` | 沒有可商用的美股行情來源（SEC EDGAR 基本面待實作） |
| 期貨行情（台指期、夜盤） | `/derivatives/overview.futures: []`、`/derivatives/futures/{code}/history` 空＋`notes` | 同上（期交所〈期貨每日交易行情〉授權待確認） |
| 基準指數 `^TAIEXTR`、`^TPEXTR` 的早期歷史 | 只有 2026-11-02 之後 | 報酬指數 OpenAPI 只給當月；更早要 FinMind（personal）或購買 |
| 上櫃公司的股利決議 | 上櫃股票只有除權息預告後才出現在 `/dividends` | 櫃買 `mopsfin_t187ap39_O` 停在 2021-08 |
| 媒體新聞 | `/news` 只有官方公告（重大訊息、證交所新聞，`source: "公告"`） | 媒體新聞需授權 |
| 開始存檔前已公布的月營收日期 | 事件用法定期限，`estimated: true` | 只能從存檔第一次看到的日期判斷 |

快取放在 `var/cache/`（已列入 .gitignore）。部署時建議掛載 volume，避免每次重啟都重新下載 shioaji-data 檔案。

## 部署到 Railway

完整步驟（含 Cloudflare Pages、網域、cookie 與 CORS、第一次部署檢查清單）見 [`docs/deploy.md`](../../docs/deploy.md)。
一個 repo 建四個服務：**api**、**worker**、PostgreSQL、Redis（Redis 目前非必要）。

1. **api**：Root Directory 設 `apps/api`，Config File Path 設 `/apps/api/railway.toml`。
   Dockerfile 啟動時會先執行 `alembic upgrade head`，再以非 root 使用者在 `$PORT` 啟動 uvicorn；
   健康檢查 `/api/v1/health`。
2. **worker**：同一個 Root Directory，Config File Path 設 `/apps/api/railway.worker.toml`
   （同一個 image，啟動指令改為 `python -m forliosa.worker`；migration 只由 api 執行）。
3. 環境變數：`FORLIOSA_ENV=prod`、`DATABASE_URL`（引用 Railway Postgres）；`DATA_POLICY` 不用設（預設 `commercial`，
   給別人用的部署**不要**設成 `personal`）、`MARKET_DATA_PROVIDERS` 用預設即可；api 另需 `SESSION_SECRET`（必填，prod 沒設會拒絕啟動）、`CORS_ORIGINS`（前端網址，
   prod 不可為 `*`）、`COOKIE_DOMAIN`（選填，例如 `.example.com`；不設則是 host-only cookie）。
4. 建議為 api 與 worker 各自掛載 volume 到 `/app/var`（image 以非 root 執行，掛 volume 時設 `RAILWAY_RUN_UID=0`）。

> 注意：`FORLIOSA_ENV=prod` 時開發登入會關閉，而正式登入（Email、Google）尚未實作，
> 所以目前的正式環境還無法登入（見 CONTRACT_NOTES 的待決事項）。

## 已知限制

- 績效的日期軸取自持股實際有成交資料的日期；交易日判斷用存檔的證交所 `holidaySchedule`（只有當年度），
  其他年份用內建清單（2027 為估計）。
- 美股沒有可商用的資料源：commercial 下沒有價格，personal 下是示範資料。
- 盤中報價目前存在 API 程序記憶體（30 秒快取）；多個 API 副本共用報價要等 Redis 版本。
- 沒有授權的盤中來源，`/intraday` 一律沒有點；`intraday_points` 資料表保留給之後的授權來源。
- 歷史資料只能從開始存檔那天累積（commercial 不用示範資料補）。
- 只記持股帳戶在快照日期（含）之前的交易不計入；快照日以收盤市值作為期初投入，從那天開始追蹤報酬。
