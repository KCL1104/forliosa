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
uv run python -m forliosa.archive run     # 建議：存一次官方開放資料（收盤、參考價、籌碼、事件、營收、季報、指數、股利決議、公司資料、期交所、集保、休市日、ETF 淨值）
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
| 08:10、14:40 | 存檔：證交所、櫃買 OpenAPI（收盤、本益比、參考價與漲跌停、融資融券、上櫃三大法人與外資持股、除權息預告、注意／處置、重大訊息、股東會、月營收、證交所新聞、ETF 基本資料、休市日、指數與報酬指數、上櫃除權息計算結果、富櫃五十成分股；08:10 與 21:40 另存證交所外資持股前 20 名 `MI_QFIIS_sort_20`，白天略過，因為它沒有日期欄位）；08:10 另讀一次**證期局 ETF 淨值**（群組 `nav`：檔案只有最新一筆，21:40 之後才公布的淨值靠這次補上） |
| 21:40 | 同上，加上季報（`t187ap06`／`07`／`17`）、公司基本資料與股利決議（`t187ap03`、`t187ap45_L`），以及**期交所** OpenAPI（期貨／選擇權行情、三大法人、大額交易人、Put/Call 比、外幣參考匯率、保證金〔變動才存〕）、**中央銀行**〈銀行間新臺幣對美元收盤匯率〉（群組 `cbc`；第一次執行回補 2008 年起的全部歷史）與**證期局 ETF 淨值**〈證券投資信託基金每日淨值〉（群組 `nav`，排在收盤存檔之後；只存上市櫃 ETF 的列）。夜盤算在下一個交易日，所以不必清晨另跑 |
| 14:35、23:45 | 更新商品主檔，把持股與自選的真實收盤價寫入 `prices_daily` |
| 13:45–23:59，最多每 10 分鐘（`TWSE_OPENDATA_CLOSE`，預設開） | **上市當天收盤** `twse_sameday_close`（`forliosa.closes`）：證交所在政府資料開放平臺登記的兩個下載網址（個股日成交資訊、大盤統計），收盤後約 13:50 就有。只抓這兩個完整網址、不帶日期參數，拿到當天的就停；被擋（轉址、403、429）當天不再抓；上次請求的時間記在 `dataset_status`，重啟也不會提早。資料日期看檔案裡每一列的「日期」和檔名，不看時鐘。存成 `twse-opendata`（官方資料，帳本市值與績效照用），隔天清晨 OpenAPI 的檔案整列取代 |
| 20:30 到隔天 02:00，每 15 分鐘（`SHIOAJI_EVENING_CLOSE`，預設開） | **晚上的暫時收盤價** `evening_closes`：shioaji-data 的 `daily.json`（多半 20:20–23:40 更新）先讀前 512 bytes 看 `as_of`，官方收盤還沒進來的市場才下載整個檔，存成只有收盤價的 `shioaji-data` 列（暫時資料），官方檔案進來後取代 |
| 13:35 到下一個交易日 08:30，每 15 分鐘 | `close_watch`：問兩個 OpenAPI 的收盤檔換成那一天了沒（條件式請求前 1 KB）；換了就跑那個市場的存檔。櫃買約 23:30、證交所約隔天 05:20。週五的收盤一路看到週一 08:30（以前到週六 08:30 就停）；已經存進來的市場不再問。兩個市場的官方收盤都進來後馬上寫每日收盤簡報 |
| 06:45（`MARKET_REPORT_PREMARKET_ARCHIVE`，預設開） | `premarket_archive`：證交所、櫃買、期交所再存一次（證交所 05:2x 的 OpenAPI 整批進來以後），讓 07:00 的盤前重點讀得到前一個交易日的官方收盤、FMTQIK 與加權指數開高低 |
| 每分鐘，自己的迴圈（`MARKET_REPORTS_ENABLED`，預設關） | **市場報告** `market_reports`（`forliosa.reports.pipeline.tick`）：盤前重點（06:15 蒐集、06:55 資料版、07:00 撰寫、07:30 推播、08:15 改推資料版、08:40 截止）、盤後重點（14:10 資料版、15:40 蒐集、15:50 撰寫、16:00 推播、17:30 截止、23:45 與隔天 06:40 補表）、市場週報（週日 16:30 資料版與蒐集、16:50 撰寫、18:00 推播、21:00 截止）。模型呼叫在四個執行緒的池子裡跑，不卡排程；跑了 20 分鐘沒有動靜的視為放棄。每一份都對所有登入的人公開，照頻道的四個開關推播（盲測 2026-11-18 拿掉了）。狀態：`uv run python -m forliosa.reports status` |
| 每天 04:40 | 市場報告保存 `MARKET_REPORT_RETENTION_DAYS`（730）天，依報告日期刪除（連同版本、產生紀錄、蒐集、投票與推播紀錄） |
| 週六 10:00 | 集保股權分散表（只能下載當週，所以每週存）、期交所最後結算價與股票期貨／選擇權標的、停更端點檢查（`twtazu_od`、`t187ap09_L`） |
| 每天 04:20 | 刪除最後活動超過 `AI_RETENTION_DAYS`（30）天的 AI 對話、訊息與草稿（見下方「AI」） |
| 每分鐘、每 20 秒 | 群組推播：排入並送出到期的交易動態推播（Discord webhook／Telegram）；有設 Telegram bot 時以 `getUpdates` 處理 `/link` 連結 |
| 週六 20:00（週日補做）、每 5 分鐘 | 群組 AI 週報：建立上週一到週五的週報並以 Message Batches 送出；收結果、推播 |
| 每天 04:35 | 群組推播紀錄 30 天、Telegram 連結碼、26 週前的週報 |
| 每月 10、25 日 10:20 | 群組 `monthly`：董監事持股餘額明細（只留公司擔任法人董事或大股東的列，給「相關股票」的關係企業）、集保股東戶數（2-22／2-23）、ESG 產品類別 |
| 每小時 :35 | 「關於」公司簡介：追蹤中的股票先用 Wikidata 找中文維基百科條目並節錄（每月一次、一次一個請求、429 就停 6 小時），沒有條目才用 AI 依官方資料寫 2–3 句（資料變了才重寫）。`uv run python -m forliosa.services.company refresh [代號…]` |
| 每 45 分鐘 | 新聞報導：追蹤中的股票（持有、自選、最近 3 天有人看過）。台股用 **GDELT 每 15 分鐘的整批檔**（GKG；翻譯串流保留中文原標題，一次下載給所有股票用，只取台灣網站、標題點名公司的；每次最多讀 `NEWS_GDELT_BULK_MAX_FILES` 份，兩份間隔 ≥ 2 秒，被拒就暫停），美股與市場頁的美股新聞（`^US`）2026-11-17 起也用同一份**英文整批檔**（不多下載；只取美國、英國新聞媒體白名單、標題點名公司的，見 `CONTRACT_NOTES.md`「2026-11-17 美股新聞改讀 GDELT 英文整批檔」）；整批檔超過 2 小時沒更新時才改回一檔一檔問 GDELT 查詢 API（每次間隔 ≥ 6 秒，429 就暫停）；免費來源 7 天內少於 3 則才用 AI 搜尋補（找 14 天內，14 天內完全沒有就找 30 天；GDELT 或 SearXNG 暫停時照樣補；每月上限 US$30）。機器人快訊（鉅亨「盤中速報」「營收速報」）、報價頁、論壇、AI 寫的頁面不收也不顯示。只存標題、媒體、時間、連結，30 天後刪除。`uv run python -m forliosa.news refresh` 可立即執行，`gdelt-bulk-check --symbol 2330 --symbol NVDA` 看最新一份整批檔（不寫資料庫），`block <網域>` 處理下架（見 `CONTRACT_NOTES.md`「2026-11-12 新聞報導」）。美股市場新聞存在 `^US`（市場頁；`NEWS_US_MARKET`），英文整批檔停住時才每次多問 GDELT 查詢 API 一次 |
| 每 5 分鐘（`NEWS_TAGGING_MINUTES`；`NEWS_TAGGING_ENABLED=false` 關掉） | **新聞標籤** `news_tagging`（`forliosa.news.tagging`，產品負責人 2026-11-17）：最近 7 天還沒貼過的新聞標題（同一個網址一次），最舊的先，每次最多 4 個請求、每個 50 則，交給 Haiku（effort low、結構化輸出）貼主題、類股、相關股票；只送標題、媒體與歸在哪幾檔。新標題不到 20 則（`NEWS_TAGGING_MIN_BATCH`）時先累積，最舊的一則存進來 30 分鐘（`NEWS_TAGGING_MAX_WAIT_MINUTES`）後才送；系統提示快取 1 小時、沿用上一次的金鑰槽。回答不能用（拒答、截斷）的那批對半切開立刻再送，只有單獨送還失敗的那一則算嘗試（15 分鐘起再試、最多 3 次；單獨被拒就直接放棄）；模型名稱或參數錯（404、400）、金鑰忙碌都只是這次先停、不算嘗試（設定錯的 WARNING 每小時最多一次）。這個 UTC 月份花到 `NEWS_TAGGING_MONTHLY_BUDGET_USD`（US$3）就停到下個月（log 寫一次）。新聞刪除時標籤一起刪。`uv run python -m forliosa.news.tagging run`／`status`／`retry-failed`（放棄的重新給嘗試次數）。估計一天 500 則約 US$1.7–2.5／月、1,000 則約 US$2.7–4.1／月（`CONTRACT_NOTES.md`「2026-11-17 新聞標籤」） |
| 每 10 分鐘看一次（只在 `NEWS_LANGSEARCH_ENABLED=true`；正式環境 worker） | **LangSearch 台股新聞** `news_langsearch`（`forliosa.news.langsearch`，產品負責人 2026-11-17 決定，`CLAUDE.md` 的例外）：交易日 16:00 起查大盤 3 個主題（存在 `^TW`，每個 UTC 日一次）；18:30 起查追蹤中的台股，依分級大型股每天、中型股每 2 天、小型股每 4 天、連 4 次 0 則的每 7 天（錯過的隔天 08:00 起補，第一次的隨時、每天最多 100 檔）。查詢是簡稱加引號（`"台積電"`），每次帶 `contents.text.max_characters=1`（約 40 token）、不篩網域；只存標題、媒體、時間、網址，過 `tw_match` 比對、只收台灣網站、去重，30 天後刪除，之後照常貼標籤。每個 UTC 日最多 250 次請求、5 萬 token；單次超過 1,000 token 當天停用；429／401／403／轉址停到下一個 00:00 UTC（台北 08:00），5xx／逾時連 2 次（跨輪計算）從失敗那一刻起暫停 15 分鐘、之後加倍；不換帳號、不偽裝。超過保存期限（30 天）的標題不存。美股不用。`uv run python -m forliosa.news langsearch-refresh`（照排程跑一次）、`langsearch-status`、`langsearch-smoke`（照 worker 的規則送一次：關閉、暫停中、到上限、worker 正在跑時不送，算進當天用量，被擋時 worker 也停；見 `CONTRACT_NOTES.md`「2026-11-17 LangSearch 台股新聞」） |
| 美股收盤後一小時起（紐約 17:00＝台北冬令 06:00、夏令 05:00），每小時到那天存進來為止；不看台股交易日 | 美股收盤價 `us_closes`（`US_PRICE_SOURCE=databento`＋`DATABENTO_API_KEY` 才有）：Databento 有新的一天才買，重讀最後 5 天；美國放假那天 20 小時後不再等 |
| 每 10 分鐘 | 美股回補 `us_backfill`（同上）：新出現在帳本或觀察清單的美股（和 SPY、DIA、ONEQ、VOO）補 2024-07-01 以來的日線，每 100 檔一個請求。Databento 拒絕（401／402／403）時兩個美股工作暫停 30 分鐘起、最長 6 小時 |

盤中沒有輪詢：證交所 MIS 的條款不允許程式下載，即時／延遲行情要付費授權，所以 `/intraday` 目前一律沒有點。
每次存檔後 worker 會重新載入證交所公布的休市日（`market_holidays`），交易日判斷與定期定額順延都以它為準。

### 即時更新（2026-11-17）

`GET /api/v1/events`（Server-Sent Events）：資料一改，打開的頁面就收到「什麼變了」的小訊號（種類＋id，不含資料），自己重抓
（合約見 `docs/api-contract.md`「即時更新」，實作見 `src/forliosa/realtime/`）。

- 每個資料庫寫入都會被看到（`realtime.capture`：SQLAlchemy session 的 flush／commit 事件；Core 的大量刪改由服務自己 `realtime.emit`），
  收件人在**同一個交易裡**算好（群組成員、授權範圍），commit 時送出。
- **PostgreSQL**（正式環境）：寫入交易裡 `pg_notify('forliosa_rt_v1', …)`，commit 了才送、照 commit 順序；api 程序用一條自己的連線
  `LISTEN`（不佔連線池；`pg_stat_activity` 裡的 `application_name` 是 `forliosa-realtime`）。worker 寫的資料（收盤價、股利自動入帳、
  週報、日報、市場報告）也是這條路。連線斷掉會自己重連，並叫所有頁面全部重抓一次。
- **SQLite**（本機、測試）：只有同一個程序聽得到；本機另外跑的 worker 寫的東西（收盤價、簡報、週報、Telegram `/link`）不會通知瀏覽器，
  而串流連著時頁面不再定時重讀這些（重新整理或換頁才看得到）。本機要測 worker 時可以設 `REALTIME_ENABLED=false`，頁面照舊定時重讀。
- 手動送一個市場事件（需要 PostgreSQL）：`uv run python -m forliosa.realtime notify market.closes --market TWSE`。
- 設定（預設就適合正式環境，不用設）：`REALTIME_ENABLED`（`true`；`false` 時 `/events` 回 503 `realtime_off`、寫入不送事件）、
  `REALTIME_MAX_STREAMS_PER_USER`（6）、`REALTIME_MAX_STREAMS`（2000）、`REALTIME_HEARTBEAT_SECONDS`（20）、`REALTIME_STREAM_MAX_SECONDS`（600）、
  `REALTIME_REPLAY_EVENTS`（4096）、`REALTIME_REPLAY_SECONDS`（300）、`REALTIME_CONNECTS_PER_MINUTE`（30）。
- 部署（SIGTERM）：訊號一到所有串流馬上收到 `bye{rotate}`（`api.app.close_streams_on_signal` 串上 uvicorn 自己的處理），瀏覽器在 0–1 秒內
  重連到新的程序；Dockerfile 的 `--timeout-graceful-shutdown 10` 只剩一般請求在用。
- LISTEN 連線默默死掉（不回應也不斷線）時，閒置探測 10 秒沒回就換一條連線並叫所有頁面重抓（`realtime/pg.py`）。
- 日誌只有數字（每 10 分鐘：幾條串流、幾個人、送了幾個事件），不記 payload、使用者 id 或 session。
- 連線池（和 API 速度工作一起）：開著的串流不佔請求的連線池（5＋10）也不佔存檔的連線池（5＋10），LISTEN 是第三種、自己的一條；
  部署後所有分頁同時重抓時兩個池子都撐得住（`tests/realtime/test_merge_batch4.py`）。慢請求記錄的 `inflight` 不算開著的串流。
  **（合併後審查更正：原本並不是每次都撐得住——請求在兩次 threadpool 呼叫之間拿著連線，高峰時 40 個 token 和 15 條連線互等到連線池逾時。
  現在登入檢查與每個同步端點做完就把只讀的交易結束、連線還回去（`forliosa.db.release_connection`、`api.routing.Router`），
  同時 500 個請求也撐得住；`inflight` 只不算 `GET /events`，AI 對話與報價串流照算。）**
- 測試：`tests/realtime/`；PostgreSQL 的部分要一個可以清空的資料庫：`FORLIOSA_TEST_PG_URL=postgresql+psycopg://…/rt_test uv run pytest tests/realtime`。

### 市場報告（2026-11-17）

盤前重點、盤後重點、市場週報（`forliosa.reports`；合約與差異見 `CONTRACT_NOTES.md`「2026-11-17 市場報告」）。`MARKET_REPORTS_ENABLED=true` 才排程；
每一份報告對所有登入的人公開，用預設的撰寫設定寫一次（`AI_MREPORT_WRITE_MODEL`＝Opus 5.5、`AI_MREPORT_WRITE_EFFORT`／`_WEEKLY`＝high；
管理後台可以每種報告另外選），照頻道的四個開關推一般的公開推播。**盲測拿掉了**（產品負責人 2026-11-18：「盲測的部分就直接拔掉吧」）：沒有試跑模式、
A／B／C、投票、揭曉；`MARKET_REPORTS_INITIAL_MODE` 預設 `public`（`trial` 還接受，當成 public）；migration `0028_remove_blind_test` 把已經做的
盲測報告改成一般公開的一份（留 Opus 5.5 high 寫的那個版本，沒有就留 A；還沒推播的只留 Opus 5.5 high 的，否則照一般流程寫），部署後跑一次
`reports tables --promoted` 把盲測過的盤後重點表格重建成最新的。站方月上限 `AI_MREPORT_MONTHLY_BUDGET_USD`（US$80；70%／90%／100% 依序降級，0＝只發資料版）。
有 `CLAUDE_API_KEY_4`（而且還有別把 key）時報告只用 4 號 key。

```bash
uv run python -m forliosa.reports status                       # 模式、本月花費與層級、最近的產生紀錄（不印金鑰）
uv run python -m forliosa.reports seed                         # 美股休市表等手動表的初始資料（worker 啟動時表是空的也會自動跑）
uv run python -m forliosa.reports pack --kind close --date 2026-11-16      # 只建資料包，不呼叫模型
uv run python -m forliosa.reports data --kind close --date 2026-11-16      # 建資料版（過去的日期是回補，只有管理員看得到）
uv run python -m forliosa.reports run --kind close --date 2026-11-16 --writer sonnet-high --yes   # 一次完整的 AI 流程（沒有 --yes 只印預估）
uv run python -m forliosa.reports tables --promoted            # 盲測過的盤後重點重建一次表格（拿掉盲測的部署後跑一次；不推播、不呼叫模型）
uv run python -m forliosa.reports tables --date 2026-11-17     # 某一天的盤後重點重建表格（留 AI 的字）
uv run python -m forliosa.reports probe-dates                  # 晚上的融資、外資前 20、期交所檔案是哪一天的
```

### 資料存檔

證交所／櫃買 OpenAPI 只提供最新一天，所以我們每天存檔，歷史從開始存檔那天累積：

```bash
uv run python -m forliosa.archive run                      # 執行一次全部存檔（約 4 分鐘；證交所每 3 秒、櫃買、集保與期交所每 2 秒一次）
uv run python -m forliosa.archive run --only twse,tpex     # 只跑部分：twse、tpex、companies、financials、taifex、cbc、nav、tdcc、weekly、monthly、sec
```

只會連線到白名單內的網址（`marketdata/http.py` 的 `ALLOWED_URL_PREFIXES` 與 `ALLOWED_EXACT_URLS`）：`openapi.twse.com.tw`、
證交所在政府資料開放平臺登記的兩個下載網址（只有 `https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=open_data` 與
`…/MI_INDEX?response=open_data` 這兩個完整網址，多一個參數都不行）、
`www.tpex.org.tw/openapi`、`opendata.tdcc.com.tw`、`openapi.taifex.com.tw/v1`、投信投顧公會主機上的證期局淨值檔
（只有 `www.sitca.org.tw/MemberK0000/F/03/nav.csv` 這一個檔案，網站其他頁面不在內）、shioaji-data 的 GitHub 檔案，以及 personal 明確開啟時的 FinMind。
美股收盤價的 `hist.databento.com/v0/` 不在共用白名單裡，只有帶著金鑰的 Databento 抓取器（`marketdata/databento.py`）連得到。
期交所的資料端點在 Cloudflare 後面，同一個端點可能回 JSON 也可能回 CSV（快取存什麼回什麼），解析器兩種都接受（`marketdata/taifex.py`）。
User-Agent 誠實標示（不偽裝瀏覽器），遇到重新導向（例如證交所防火牆的 307）、403、429 就停，不重試到成功。
**證交所／櫃買／MIS／公開資訊觀測站的網站一律不爬**（網站條款禁止未經同意以程式下載，見
[`docs/research/data-sources-licensing.md`](../../docs/research/data-sources-licensing.md)）；原本的 T86、MI_QFIIS 網站回補與
MIS 盤中輪詢已移除，舊資料庫裡來源是 `twse-web`、`twse-mis` 的資料列在任何模式都不會被讀出。
唯一的例外是上面白名單裡證交所的兩個下載網址（產品負責人 2026-11-16，CLAUDE.md；見下方「資料來源與授權」）：它們是 data.gov.tw 登記的資料集檔案，
證交所公開回覆過可以用程式下載。櫃買網站在 data.gov.tw 登記的下載網址（例如 11370 上櫃股票行情）**不在**例外裡，沒有抓。

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
| `AI_DAILY_MESSAGE_LIMIT`、`AI_MONTHLY_TOKEN_BUDGET`、`AI_MONTHLY_COST_BUDGET_USD` | 3、3,000,000、1 | 免費帳號每天提問數、每月計費 token、每月估計花費（美元）（0＝不限；產品負責人 2026-11-15） |
| `AI_MEMBER_DAILY_MESSAGE_LIMIT`、`AI_MEMBER_MONTHLY_COST_BUDGET_USD`、`AI_MEMBER_MONTHLY_TOKEN_BUDGET` | 30、8、0 | 會員（站方在 `/admin/members` 開通；站方管理員也算；每月約 US$8 是 2026-11-16 起，以前 US$3）。會員和免費帳號只差這些題數與額度，以及每日收盤簡報（產品負責人 2026-11-17） |
| `AI_FREE_DEEP_SEARCH`、`AI_FREE_DAILY_BRIEFING` | `true`、`false` | 免費帳號能不能用深度搜尋／收盤簡報。深度搜尋預設所有帳號都有（2026-11-17；算自己的題數），`false` 改回只給會員；收盤簡報只給會員，`true` 開給所有人（個人部署用） |
| `AI_ECONOMY_CAP_MULTIPLIER`、`AI_MEMBER_ECONOMY_CAP_MULTIPLIER` | 2、1.25 | 花費上限用完後的省錢模式（不上網搜尋）一直到花了上限的幾倍才停（前一個是免費帳號的，後一個是會員的，2026-11-16）；1＝到上限就停 |
| `AI_WEB_SEARCH`、`AI_WEB_SEARCH_MAX_USES`、`AI_WEB_SEARCH_ALLOWED_DOMAINS` | `true`、5、空 | 預設不限網域，由模型判斷何時搜尋、用哪些來源（只限財經資訊） |
| `AI_DEEP_SEARCH_COST`、`AI_DEEP_SEARCH_MAX_USES`、`AI_DEEP_MAX_TOOL_ROUNDS` | 3（不超過每天的題數）、12、16 | 深度搜尋（`POST /ai/chat` 的 `mode: "deep"`）：一次算幾題、最多搜尋幾次、迴圈最多幾輪 |
| `AI_WEB_FETCH_ALLOWED_DOMAINS` | （空，不限） | 產品負責人 2026-11-12 決定開放，由 AI 自行判斷；可設 `official` 只讀官方網域 |
| `AI_WHY_ENABLED` | `true` | 個股頁「為什麼漲跌」的 AI 一句話（每檔每個交易日最多一次，失敗時用規則句） |
| `AI_SCOPE_PRECHECK` | `true` | 明顯離題又沒有財經字詞的提問不呼叫模型，直接婉拒 |
| `AI_RETENTION_DAYS` | 30 | 對話、訊息、草稿在最後活動後保存幾天（0＝永久） |
| `AI_MARKET_SUMMARY_ENABLED` | `true` | 市場頁的 AI 收盤重點：每個交易日一則、全站共用（worker 15:05、18:05、22:05；收盤後第一次開頁面也會觸發）；不計入任何人的額度 |
| `AI_DIGEST_ENABLED`、`AI_MODEL_DIGEST` | `true`、空 | 群組 AI 週報（worker 每週六 20:00，Message Batches；不計入任何成員的額度）；模型預設同 `AI_MODEL` |
| `GROUP_FREE_MEMBER_CAP`、`GROUP_BOOSTED_MEMBER_CAP` | 5、50 | 群組加值包（產品負責人 2026-11-16）：免費群組最多幾位成員、加值的群組最多幾位；0023 部署當時已有的群組維持 50（`groups.grandfathered_member_cap`）。滿了只擋加入，不移除人。api 與 worker 設一樣的值 |
| `GROUP_DAILY_ENABLED`、`AI_GROUP_DAILY_MONTHLY_BUDGET_USD` | `true`、5 | 群組 AI 日報（只給加值的群組，每個交易日一則；不計入任何成員的額度）；全部群組合計每月的花費上限（美元，0＝不限） |
| `AI_KEY_STICKY_WAIT_SECONDS`、`AI_KEY_COOLDOWN_SECONDS` | 5、60 | 見上 |
| `IMPORT_STATEMENTS` | `all` | 匯入對帳單（`POST /imports/statement`；產品負責人 2026-11-16）與匯入庫存（`POST /imports/positions`；2026-11-17）誰能用：`all` 所有登入的人（免費與會員一樣；2026-11-17 起是預設）、`admins` 只有站方管理員（`ADMIN_EMAILS`；第一版）、`off` 沒有人。`GET /me` 的 `plan.statement_import` 照它算 |
| `AI_MODEL_IMPORT`、`AI_EFFORT_IMPORT` | 空（＝`AI_MODEL`，`claude-haiku-5-5`）、`medium` | 讀對帳單與庫存截圖的模型與 effort（結構化 JSON、沒有工具、一次最多 5 頁） |
| `AI_MODEL_IMPORT_RETRY` | `claude-sonnet-5-5` | 驗算沒過、合計對不上、有沒讀清楚的地方或模型拒答時，那幾頁用這個模型再讀一次（effort low，一份約 US$0.08）；省錢模式不重讀；設成空字串＝不重讀 |
| `IMPORT_DAILY_LIMIT` | 10 | 每人每天最多讀幾次，對帳單與庫存合計（0＝不限）；不算每天的提問數，費用算進每月額度（`/ai/usage` 的 `imports_today`、`import_daily_limit`） |
| `IMPORT_MAX_PAGES`、`IMPORT_MAX_BODY_MB` | 20、15 | 一次最多幾頁（圖片）、request body 最大幾 MB；超過回 413 |
| `AI_IMPORT_MAX_TOKENS` | 16000 | 每次呼叫的 `max_tokens`（不串流；約 50 列）；答不完時把頁數切半重讀 |
| `AI_ADMIN_EMAILS` | 空 | 正式環境可看金鑰槽狀態的帳號（逗號分隔） |
| `TWSE_OPENDATA_CLOSE` | `true` | worker 在交易日下午抓證交所的兩個下載網址，上市收盤當天約 14:00 進來（見排程）；證交所表示不同意就設 `false`。api 用它算 `market-status` 的預計時間（`tw.closes`），所以**api 與 worker 都要設** |
| `SHIOAJI_EVENING_CLOSE` | `true` | worker 晚上用 shioaji-data 先放暫時收盤價（見排程）；同上，api 與 worker 都要設 |
| ~~`MREPORT_TRIAL_AUDIENCE`~~、~~`AI_MREPORT_TRIAL_BUDGET_USD`~~、~~`AI_MREPORT_TRIAL_DAYS`~~ | — | **已拿掉**（產品負責人 2026-11-18：拿掉盲測）。程式不再讀；Railway 上還留著也不會讓啟動失敗（未知的變數忽略），可以刪掉。`MARKET_REPORTS_INITIAL_MODE` 預設改成 `public`（`trial` 當成 public） |

**範圍**：助理只協助投資理財、台股與美股、使用者自己的持股與交易，以及 Forliosa 的用法；寫程式、一般常識、作業、翻譯、寫作、角色扮演等要求，
用一句繁體中文婉拒並把話題帶回投資。明顯的情況（例如「幫我寫 Python 爬蟲」）在伺服器端就婉拒、不花模型費用；只要提到任何財經字詞或股票代號就交給模型判斷。

**有根據才寫**：數字與事實只能來自工具結果或附引用的網路來源；用了網路搜尋的回答中，沒有引用又像新聞敘述的句子會在 `grounding` 事件列出，
前端標「無來源」。**免責聲明**「AI 只替你整理資訊，可能有錯；Forliosa 不是投資顧問，不提供投資建議。」（全站的字在 `forliosa/disclaimer.py`，和前端 `apps/web/src/lib/disclaimer.ts` 相同）由前端固定顯示（`done.disclaimer`、`/ai/usage.disclaimer`），模型不寫。

**保存期限**：對話與訊息（含網路搜尋的加密內容）、草稿在最後活動 30 天後由 worker 每天刪除；`ai_usage`（token、槽號、估計費用，不含內容）保留做帳。

**AI 從不寫入帳本**：記帳一律先產生草稿，使用者在畫面上確認後前端才 `POST /transactions`（`source: "ai_draft"`）。
匯入也一樣：AI 只讀對帳單或庫存截圖、伺服器逐列檢查，使用者在確認表上按下寫入，前端才 `POST /transactions/batch`（對帳單）或 `POST /imports/positions/commit`（庫存：每一檔一筆買進；`account_id` 必填、不退回第一個帳戶；「以券商為準」在同一個交易裡先刪掉那個帳戶那一檔的舊紀錄，股利與賣出也在內），兩種都能用 `DELETE /transactions/batches/{id}` 整批復原（換掉的舊紀錄不會回來）。

## 專案結構

```
src/forliosa/
  domain/        純計算，不碰資料庫與網路：fees.py（稅費）、ledger.py（帳本重播）、rounds.py（出清回合）、performance.py（績效）
  marketdata/    行情 provider：shioaji_data、twse（OpenAPI）、tpex（OpenAPI）、finmind（personal 明確開啟才用）、
                 archive_provider（自建存檔）、demo；
                 opendata.py 是證交所／櫃買／集保資料集解析器、taifex.py 是期交所解析器，service.py 負責備援順序、合併與參考價
  archive.py     官方開放資料每日存檔與回補（CLI：python -m forliosa.archive）
  us_prices.py   美股收盤價（Databento EQUS.SUMMARY；marketdata/databento.py 是用戶端）：回補與每天更新，worker 的 us_backfill、us_closes
  datapolicy.py  DATA_POLICY、資料集清單與 sources 顯名聲明（GET /meta/attributions）
  market_calendar.py  把存檔的證交所休市日套用到交易日計算
  services/      交易（自動稅費＋帳本驗證）、投資組合（含本週事項、出清紀錄）、個股資料、個股頁（stock.py）、期貨盤勢（derivatives.py）、自選、
                 定期定額（recurring.py）、重大訊息判讀（announcements.py）、「資料累積中」（coverage.py）；
                 M5 分享：分享投影（sharing.py，讀別人資料的唯一入口）、群組（groups.py）、授權（delegations.py）、
                 Discord 與 Google 登入（discord_oauth.py、google_oauth.py）、群組週報（digests.py）、推播頻道（channels.py、notifications.py、pushers.py）
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

- `commercial`（預設）：只用可合法商用的資料——政府開放資料（證交所／櫃買／期交所 OpenAPI、證交所在 data.gov.tw 登記的兩個下載網址、集保開放資料、中央銀行匯率）、shioaji-data 官方檔，
  以及由它們建立的自建存檔。期交所資料集中**授權「有條件」**的（期貨／選擇權每日交易行情、每日外幣參考匯率、選擇權大額交易人、
  最後結算價、保證金、股票期貨／選擇權標的：data.gov.tw 找不到對應的開放授權資料集）照常存檔，但**不顯示**，直到產品負責人取得
  期交所書面確認並設定 `TAIFEX_CONDITIONAL_CONFIRMED=true`（預設 `false`；詢問信見 [`docs/outreach/taifex-licence-inquiry.md`](../../docs/outreach/taifex-licence-inquiry.md)）。**從不使用示範資料**：存檔還不夠時回空資料並在 `notes` 說明「資料累積中：自 YYYY-MM-DD 起存檔」。
  shioaji-data 由 AI 整理的公司簡介、產業鏈、題材（授權待定）不顯示。
  兩個由產品負責人決定、知道授權風險的例外：存檔以前的日線用 Yahoo Finance 回補（`PRICE_HISTORY_SOURCE=yahoo`，只給圖表）；
  美股收盤價用 Databento（`US_PRICE_SOURCE=databento`，2026-11-15，見下方「美股收盤價」）。
- `personal`：只給開發者本人明確開啟。示範資料補缺；把 `finmind` 加進 `MARKET_DATA_PROVIDERS` 才會用 FinMind
  （回應的 `sources` 以「（非商用）」結尾）。

**任何模式都不使用**：證交所網站（`www.twse.com.tw` 的 T86、MI_QFIIS 等）、基本市況報導 MIS（`mis.twse.com.tw`）、
櫃買網站（如 `peQryDate`）、公開資訊觀測站網站——這些網站的條款禁止未經書面同意以程式下載。
唯一的例外（產品負責人 2026-11-16，CLAUDE.md）：證交所在政府資料開放平臺登記的兩個下載網址（data.gov.tw 11549、11555；
證交所 2025-09-17 在平臺上回覆「本資料集可以使用自動程式進行下載」），見上方排程的 `twse_sameday_close`。櫃買網站的下載網址不在例外裡。

**顯名聲明**：政府資料開放授權條款第 1 版要求標示提供機關、資料集名稱與年份，沒有標示視為自始未取得授權。
每個回應的 `sources` 都是這個格式，例如「臺灣證券交易所〈上市個股日本益比、殖利率及股價淨值比〉（2026），依政府資料開放授權條款第 1 版」；
`GET /api/v1/meta/attributions`（不需登入）列出所有使用中的資料集與授權條款第 2、3 點的固定文字，前端「資料來源與授權」頁直接使用。

`MARKET_DATA_PROVIDERS` 決定順序（預設 `archive,twse_openapi,tpex_openapi,shioaji_data,demo`），前一個失敗就用下一個；
失敗的來源會暫停一段時間再試。日線、本益比、股利會**合併**：存檔有的日期用存檔，缺的由下一個真實來源補。

| 來源 | 用途 | 授權與限制 |
|---|---|---|
| 證交所／櫃買中心 OpenAPI | 收盤行情、本益比、參考價與漲跌停、融資融券、除權息預告、注意／處置、重大訊息、股東會、月營收、季報、休市日、證交所新聞、ETF 基本資料、**指數與報酬指數**（`MI_INDEX`、`MFI94U`、`tpex_index`、`tpex_reward_index` → 基準 `^TAIEXTR`、`^TPEXTR`）、**上市股利決議**（`t187ap45_L`：盈餘／法定公積／資本公積分列）、**公司基本資料**（`t187ap03_L`、`mopsfin_t187ap03_O`：已發行股數 → 市值、產業、上市日）、**上櫃除權息計算結果**（`tpex_exright_daily`：官方參考價）；櫃買另有個股三大法人與外資持股（都只有最新一天，每天存檔） | 政府資料開放授權條款第 1 版，可商用，**須顯名** |
| 證交所在政府資料開放平臺登記的下載網址（`www.twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=open_data`、`…/MI_INDEX?response=open_data`；只有這兩個完整網址，2026-11-16 起） | **上市當天的收盤**：個股日成交資訊（開高低收、成交量）與大盤統計（加權指數、類股指數），收盤後約 13:50 就有；worker `twse_sameday_close` 交易日 13:45 起最多每 10 分鐘抓，拿到當天的就停（`TWSE_OPENDATA_CLOSE`）。`prices_daily`／`index_daily` 的 `source = 'twse-opendata'`，帳本市值與績效照用；隔天清晨 OpenAPI 的檔整列取代。下午那份的成交量可能還沒算盤後、零股、鉅額（未證實） | 政府資料開放授權條款第 1 版（data.gov.tw 11549、11555），可商用，**須顯名**。證交所 2025-09-17 在平臺回覆「本資料集可以使用自動程式進行下載」；網站條款第 6 條（依同意之方式不在此限）、第 8 條（平臺授權的資料除外）。產品負責人的窄例外（CLAUDE.md）：不帶日期參數、被擋（轉址、403、429）當天就停、不偽裝瀏覽器；證交所表示不同意就關掉。研究：[`docs/research/same-day-close.md`](../../docs/research/same-day-close.md) |
| 期交所 OpenAPI | 三大法人（5 個依日期資料集）、期貨大額交易人、臺指選擇權 Put/Call 比 → `/derivatives/overview`、AI 工具 `get_derivatives_overview` | 同上（data.gov.tw 11592–11600、11337／11338、11322） |
| 期交所 OpenAPI（有條件） | 期貨／選擇權每日交易行情（含夜盤）、每日外幣參考匯率（只存檔：USD/TWD 改用中央銀行）、選擇權大額交易人、最後結算價、保證金、股票期貨／選擇權標的 | 推定 OGDL，但 data.gov.tw 沒有個別資料集：**存檔但不顯示**，`TAIFEX_CONDITIONAL_CONFIRMED=true` 後才顯示 |
| 集保開放資料 | 股權分散表（只有當週，每週存檔） | 同上 |
| 中央銀行開放資料（`cpx.cbc.gov.tw/api/OpenData/FTDOpenData_Day`） | 〈銀行間新臺幣對美元收盤匯率〉：USD/TWD（美股換算新台幣；2008-01-02 起每個營業日） | 同上（data.gov.tw 7232） |
| 金融監督管理委員會證券期貨局〈證券投資信託基金每日淨值〉（`www.sitca.org.tw/MemberK0000/F/03/nav.csv`，檔案放在投信投顧公會主機；只抓這一個檔案、每 2 秒最多一次） | ETF 淨值與盤後折溢價（個股頁「淨值與折溢價」、AI `get_stock_overview`）；檔案只有每檔最新一筆，每天存檔累積 | 政府資料開放授權條款第 1 版（data.gov.tw 11109），須顯名 |
| shioaji-data（GitHub raw） | 商品主檔、每日收盤與市值、月營收、季 EPS／淨值；**晚上的暫時收盤價**（2026-11-16 起，worker `evening_closes`，`SHIOAJI_EVENING_CLOSE`）：`v1/tw/market/daily.json` 大多當天 20:20–23:40 更新（19 天裡 3 天拖到隔天 00:05–01:29），官方收盤還沒進來的市場先存只有收盤價的列（`source = 'shioaji-data'`，開高低與成交量是 null；`dataset_status` `shioaji-data/interim_twse`、`…_tpex`）。官方的檔（證交所下載檔或 OpenAPI、櫃買 OpenAPI）進來後整列取代，暫時的列從不蓋掉官方的列；每日收盤簡報與市場頁排行不用它 | 官方資料部分為政府資料開放授權條款第 1 版（它本身是從證交所、櫃買在 data.gov.tw 登記的網址轉存的）；沒有保證更新時間；AI 整理的簡介、產業鏈、題材授權「待定」，commercial 不顯示 |
| FinMind v4 | personal 明確開啟時：回補、新聞標題、匯率、`^TAIEXTR` | ⚠️ 不可商用（付費版也不包含原機關授權），預設不建立 |
| Databento 歷史 API（`hist.databento.com`，資料集 `EQUS.SUMMARY`） | 美股收盤價（`US_PRICE_SOURCE=databento` 時）：Nasdaq NLS Plus 的官方合併收盤，日線、未還原分割與股利，2024-07-01 起；只抓帳本或觀察清單裡的美股與 SPY、DIA、ONEQ、VOO → 報價、走勢、帳本市值、`/close`、市場頁美股、AI。`prices_daily.source = 'databento-equs'` | 付費、按量計費（先用註冊送的 US$125 額度）；顯名「Databento〈US Equities Summary（EQUS.SUMMARY，Nasdaq NLS Plus 官方合併收盤）〉（2026），資料由 Databento 提供」。產品負責人沒有先確認能不能顯示給會員（2026-11-15，知道風險）；分割與股利資料不能轉載，沒有用 |
| GDELT 整批檔（GKG 2.1，`storage.googleapis.com/data.gdeltproject.org/gdeltv2/`） | 台股與美股的「新聞報導」、市場頁的美股新聞：每 15 分鐘一份（翻譯串流 4–13 MB、英文 2–7 MB 壓縮檔；兩種合計每天約 1 GB 下載，不收費），台股只取台灣網站、美股只取美國與英國新聞媒體白名單，標題點名公司的原標題、媒體、時間、連結 | 同 GDELT：免費、可商用，須引用 GDELT 並連到 gdeltproject.org |
| GDELT DOC 2.0（`api.gdeltproject.org`） | 只在整批檔超過 2 小時沒更新時當備用（台股看翻譯檔、美股與市場新聞看英文檔）：媒體原標題、媒體、時間、原文連結（不存內文與圖片） | 免費、可商用，須引用 GDELT 並連到 gdeltproject.org |
| AI 網路搜尋（Claude `web_search`） | 新聞報導補缺（免費來源 7 天內少於 3 則時，找 14–30 天）；標題與連結取自搜尋結果；封鎖報價頁、論壇、AI 寫的頁面 | 系統付費，每次約 US$0.023，每月上限 `NEWS_AI_BUDGET_USD`（30） |
| SearXNG（自架） | 新聞報導的備用來源，**預設關**（`NEWS_SEARXNG_URL`） | 自動查詢上游搜尋引擎違反它們的條款，由營運者承擔 |
| LangSearch 網路搜尋（`api.langsearch.com/v1/web-search`） | 台股的「新聞報導」與台股大盤（`^TW`）：只取標題、媒體、時間、網址（`NEWS_LANGSEARCH_ENABLED`，預設關，只在正式環境 worker 開） | 條款沒寫清楚能不能保存結果、經營者不明，產品負責人 2026-11-17 決定採用（`CLAUDE.md`）；在免費每日額度內、被擋就停到隔天 |
| Yahoo股市 RSS | personal 明確開啟時：新聞報導 | ⚠️ 條款限個人、非商業使用；保留「Yahoo股市」與原始媒體 |
| 示範資料（demo） | personal 的缺資料備援；commercial 只提供商品名稱清單 | 模擬資料，`is_demo: true` |
| ~~證交所 MIS、證交所網站 T86／MI_QFIIS、櫃買網站 peQryDate~~ | 已移除（2026-11-12） | 網站條款禁止程式下載 |

### commercial 下目前沒有的資料（前端請顯示誠實的空狀態）

| 資料 | 回應 | 原因／取得方式 |
|---|---|---|
| 盤中走勢 `/intraday` | `points: []`＋`notes` | 即時／延遲行情需付費授權（證交所延遲行情約 NT$30,000／月起） |
| 上市股票個股三大法人、外資持股 | `chips.institutional`／`foreign_holding_pct` 空＋`notes` | 證交所 OpenAPI 沒有；Data E-Shop 付費（約 NT$3,000／月起）或書面同意。上櫃股票有（櫃買 OpenAPI） |
| 開始存檔前的歷史（日線、本益比、法人、融資） | 只回已存檔的部分，`notes`「資料累積中：自 … 起存檔」 | 官方 OpenAPI 只給最新一天；網站回補要同意 |
| 績效 `/portfolio/performance` | 持股期間沒有每天的真實收盤價時 `series: []`＋`notes`；之後從第一個完整存檔日開始計算 | 同上 |
| ~~美股價格、美股績效~~ | 已有（2026-11-15，`US_PRICE_SOURCE=databento` 時）：Databento 的收盤價，2024-07-01 起。關著時照舊 `price: null`（以成本計值，`is_demo: false`）、績效空＋`notes`「…：美股沒有報價，含美股的績效算不出來」 | — |
| 剛加入、還沒抓到收盤價的美股 | `/quote` 404、`Holding.price: null`（以成本計值）、績效空＋`notes`「MSFT：還沒有收盤價，績效算不出來」 | worker 每 10 分鐘回補一次，約 10 分鐘內補上 |
| 美股 2024-07-01 以前的日線 | 走勢從 2024-07-01（或上市日）開始，`notes`「資料從 2024/07/01 開始」 | EQUS.SUMMARY 從那天開始 |
| 美股股利、美股估值（本益比河流圖）、籌碼、相關股票、美股指數點數 | `/dividends` 空、估值序列沒有本益比、`chips`／`related` 空＋`notes`；市場頁只有 SPY、DIA、ONEQ 三檔 ETF | 沒有來源；指數點數要向指數公司取得授權 |
| 期貨行情（台指期、夜盤） | `/derivatives/overview.futures: []`、`/derivatives/futures/{code}/history` 空＋`notes` | 同上（期交所〈期貨每日交易行情〉授權待確認） |
| 基準指數 `^TAIEXTR`、`^TPEXTR` 的早期歷史 | 只有 2026-11-02 之後 | 報酬指數 OpenAPI 只給當月；更早要 FinMind（personal）或購買 |
| 上櫃公司的股利決議 | 上櫃股票只有除權息預告後才出現在 `/dividends` | 櫃買 `mopsfin_t187ap39_O` 停在 2021-08 |
| ~~媒體新聞~~ | 已有（2026-11-12）：`/news` 在官方公告後列出新聞報導（GDELT、AI 搜尋補缺；只有標題、媒體、時間、連結） | — |
| 開始存檔前已公布的月營收、季報的實際公布日 | 事件列成已公布、日期放在法定期限（`estimated: false`，`detail` 寫「實際公布日不明，日期是法定期限」）；手上沒有那一期資料的過去期限不列 | 只能從存檔第一次看到的日期判斷（月營收、2026-11-17 起的季報）；新上市、轉上市公司的第一期也一樣不知道 |

### 美股收盤價（Databento，2026-11-15）

產品負責人決定用 Databento 的 `EQUS.SUMMARY`（研究：[`docs/research/us-market-data.md`](../../docs/research/us-market-data.md)；細節：`CONTRACT_NOTES.md`「2026-11-15 美股收盤價（Databento）」）。

| 變數 | 放在哪裡 | 預設 | 說明 |
|---|---|---|---|
| `US_PRICE_SOURCE` | **api 與 worker** | 空 | `databento`：api 讀已存的美股收盤並列出顯名（不需要金鑰）；worker 有金鑰時才抓。空：不抓也不讀，已存的列留著但不讀、不列來源，美股回到「美股沒有報價」 |
| `DATABENTO_API_KEY` | **只放 worker** | 空 | Databento 的金鑰（HTTP Basic：金鑰當使用者名稱、密碼空白）。按量計費；不會寫進 log |
| `NEWS_US_MARKET` | worker | `true` | 市場頁的美股新聞（`^US`）：從英文整批檔比對；整批檔停住時每次整理新聞多問 GDELT 查詢 API 一次 |
| `NEWS_GDELT_BULK` | worker | `true` | 台股、美股與市場頁美股新聞用 GDELT 每 15 分鐘的整批檔（`false`：回到一檔一檔問查詢 API） |
| `NEWS_GDELT_BULK_FEEDS` | worker | `translation,english` | 讀哪幾種整批檔：`translation`（中文等非英文網站，台灣新聞幾乎都在這裡）、`english`（美股與市場頁美股新聞；拿掉時美股改回查詢 API） |
| `NEWS_GDELT_BULK_MAX_FILES` | worker | `8` | 每種整批檔每次最多讀幾份（8 份＝2 小時）；停機太久時更早的會略過 |
| `NEWS_TAGGING_ENABLED`、`NEWS_TAGGING_MINUTES` | worker | `true`、`5` | 新聞標籤（主題、類股、相關股票；2026-11-17）：關掉就沒有這個工作，已貼的標籤留著 |
| `NEWS_TAGGING_MIN_BATCH`、`NEWS_TAGGING_MAX_WAIT_MINUTES` | worker | `20`、`30` | 新標題不到這麼多則時先累積，最舊的一則等到這麼久才送（每個請求有固定成本：系統提示與 thinking）；等待最多 55 分鐘（快取 1 小時） |
| `NEWS_TAGGING_MONTHLY_BUDGET_USD` | worker | `3` | 新聞標籤每個 UTC 月份的上限（`ai_usage.feature = 'news_tagging'`，不算任何人的額度）；0＝不貼 |
| `NEWS_TAGGING_BATCH_SIZE`、`NEWS_TAGGING_MAX_BATCHES`、`NEWS_TAGGING_DAYS`、`AI_MODEL_NEWS_TAGGING` | worker | `50`、`4`、`7`、空 | 一個請求幾則（最多 50）、每次最多幾個請求、只貼最近幾天的（最多 90）、模型（空＝`AI_MODEL`） |
| `NEWS_LANGSEARCH_ENABLED` | **只放 worker** | `false` | LangSearch 台股新聞（2026-11-17）：只在正式環境 Railway worker 設成 `true`；關著時沒有這個工作，什麼都不送 |
| `LANGSEARCH_API_KEY` | worker；開 `AI_LANGSEARCH_ENABLED` 時 API 也要 | 空 | LangSearch 的金鑰（`Authorization: Bearer`）；沒有就不跑；不會寫進 log。雲端沙盒手動測試時設成 `proxy-injected`（proxy 代入真正的憑證） |
| `AI_LANGSEARCH_ENABLED` | **只放 API**（對話、法人卡片、為什麼漲跌都在 API 服務產生） | `false` | AI 先查 LangSearch（2026-11-17 產品負責人決定）：對話的 `tw_news_search`（台股新聞、為什麼漲跌、法人目標價、法說會、營收、配息、大盤）、個股頁的法人觀點卡片（至少 2 家具名機構才用）與「為什麼漲跌」一句話；沒有可用的結果才用 Claude 的網路搜尋。內文只在當次交給 Claude，不存、不顯示（引用只帶「媒體，日期：標題」；卡片只存整理後的欄位與連結）。只在正式環境 Railway 打開；關著或沒有金鑰時和以前一樣 |
| `AI_LANGSEARCH_MAX_REQUESTS_PER_DAY`、`AI_LANGSEARCH_MAX_TOKENS_PER_DAY` | API | `300`、`3000000` | AI 每個 UTC 日的請求數與 token 上限（對話、法人卡片、為什麼漲跌合用；和新聞排程的上限分開算）。到了以後對話的工具叫模型改用網路搜尋，卡片與為什麼漲跌直接用網路搜尋 |
| `AI_LANGSEARCH_MAX_REQUESTS_PER_TURN`、`AI_LANGSEARCH_IN_ECONOMY`、`AI_LANGSEARCH_TOKEN_GUARD` | API | `3`、`true`、`20000` | 每一題最多幾次請求（慢的空結果重送不算）；省錢模式保留工具；單次回應超過幾個 token 就當天停用 AI 的部分（新聞排程照常） |
| `AI_LANGSEARCH_DEADLINE_SECONDS` | API | `12` | AI 每一次查 LangSearch（對話的 `tw_news_search`、法人卡片、為什麼漲跌）的總時限，從排隊等間隔開始算，包含連線與讀取（2026-11-17 實測：一次請求約 37 秒）。超過就當作查不到，改用 Claude 的網路搜尋；算進每天上限。一次呼叫在時限內一個回答都沒有算一次連線失敗，連 2 次（中間沒有回答）就和 5xx／逾時一樣暫停 LangSearch（新聞排程也停）；只有一次慢的不會。時限過後才到的回應在下一次 AI 請求開始時記帳（token、429／403／轉址照樣停到隔天）。慢的空結果重送要這個值至少 12.5 才會發生，預設 12 等於關掉。新聞排程的請求不受時限影響（它只有 `NEWS_LANGSEARCH_TIMEOUT_SECONDS`） |
| `NEWS_LANGSEARCH_MAX_REQUESTS_PER_DAY`、`NEWS_LANGSEARCH_MAX_TOKENS_PER_DAY`、`NEWS_LANGSEARCH_MAX_FIRST_FILL_PER_DAY`、`NEWS_LANGSEARCH_TOKEN_GUARD` | worker | `250`、`50000`、`100`、`1000` | 每個 UTC 日的請求數、token、第一次查的檔數上限；單次回應超過 `TOKEN_GUARD` 個 output token 就當天停用 |
| `NEWS_LANGSEARCH_TOPICS_AT`、`NEWS_LANGSEARCH_STOCKS_AFTER`、`NEWS_LANGSEARCH_TOPICS` | worker | `16:00`、`18:30`、`台股 盤後,外資 買賣超,台股 大盤` | 台北時間：交易日查大盤的時間、每天查個股的開始時間；大盤的查詢句（不加引號） |
| `NEWS_LANGSEARCH_EVERY_DAYS`、`NEWS_LANGSEARCH_QUIET_AFTER_EMPTY` | worker | `large=1,mid=2,small=4,quiet=7`、`4` | 各分級幾天查一次；小型股連續幾次 0 則改成安靜（每 7 天） |
| `NEWS_LANGSEARCH_COUNT_LARGE`、`NEWS_LANGSEARCH_COUNT`、`NEWS_LANGSEARCH_LARGE_RANK`、`NEWS_LANGSEARCH_LARGE_MIN_AVG`、`NEWS_LANGSEARCH_MID_MIN_AVG` | worker | `50`、`20`、`50`、`5`、`1` | 大型股與其他（含大盤）每次要幾筆；市值前幾名起始為大型股；每週重分時平均每次入庫幾則算大型、中型 |
| `NEWS_LANGSEARCH_INTERVAL_SECONDS`、`NEWS_LANGSEARCH_TIMEOUT_SECONDS`、`NEWS_LANGSEARCH_URL`、`NEWS_LANGSEARCH_JUNK_DOMAINS` | worker | `1.5`、`20`、`https://api.langsearch.com/v1/web-search`、四個台灣垃圾站 | 兩次請求的間隔（最少 1.2，跨程序也算）、逾時、網址（只能是 api.langsearch.com）、不收的台灣網站（逗號分隔） |

- 進度：管理後台總覽的「美股收盤價」（`GET /admin/overview` 的 `us_prices`）：存到紐約的哪一天、日線筆數、還沒回補與找不到的檔數。
- 收盤價沒有還原分割與股利；Databento 的分割、股利資料不能轉載，所以沒有用。帳本照使用者記的分割；走勢圖從開盤價偵測分割並換算。
- 關掉：把 api 與 worker 的 `US_PRICE_SOURCE` 拿掉（已存的列留在 `prices_daily`，`source = 'databento-equs'`）。

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
   prod 不可為 `*`）、`FRONTEND_URL`（必填，前端網址，必須是 `CORS_ORIGINS` 之一）、`DISCORD_CLIENT_ID`／`DISCORD_CLIENT_SECRET`／
   `DISCORD_REDIRECT_URI`（Discord 登入，見 `docs/deploy.md` 2.4 節）、`COOKIE_DOMAIN`（選填，例如 `.example.com`；不設則是 host-only cookie）。
   群組推播與週報在 worker：worker 另需和 api **相同**的 `SESSION_SECRET`（prod 沒設會拒絕啟動）、`FRONTEND_URL`、Claude 金鑰，
   要用 Telegram 時 api 與 worker 都設 `TELEGRAM_BOT_TOKEN`／`TELEGRAM_BOT_USERNAME`（見 `docs/deploy.md` 2.5 節）；worker 只能一個副本。
   美股收盤價：api 與 worker 都設 `US_PRICE_SOURCE=databento`，`DATABENTO_API_KEY` 只設在 worker（見上方「美股收盤價」）。
4. 建議為 api 與 worker 各自掛載 volume 到 `/app/var`（image 以非 root 執行，掛 volume 時設 `RAILWAY_RUN_UID=0`）。

> 注意：`FORLIOSA_ENV=prod` 時開發登入會關閉，正式登入用 Discord（M5）與 Google（選用，`GOOGLE_*`，見 `docs/deploy.md` 2.4.1 節）：沒設三個 `DISCORD_*` 時正式環境沒有人能登入。

## 已知限制

- 績效的日期軸取自持股實際有成交資料的日期；交易日判斷用存檔的證交所 `holidaySchedule`（只有當年度），
  其他年份用內建清單（2027 為估計）。
- 美股：`US_PRICE_SOURCE=databento` 時有 Databento 的收盤價（2024-07-01 起、只有帳本或觀察清單裡的代號）；沒開時 commercial 下沒有價格，personal 下是示範資料。
  美股股利仍沒有來源。收盤價沒有還原分割：走勢圖從開盤價偵測分割並換算，帳本照使用者記的分割。
- 盤中報價目前存在 API 程序記憶體（30 秒快取）；多個 API 副本共用報價要等 Redis 版本。
- 沒有授權的盤中來源，`/intraday` 一律沒有點；`intraday_points` 資料表保留給之後的授權來源。
- 歷史資料只能從開始存檔那天累積（commercial 不用示範資料補）。
- 「只記持股」已取消（2026-11-14）：migration `0018` 把舊的快照轉成快照日的買進（以均價成本），所以轉換過的帳戶在快照日的報酬
  包含從均價到當天收盤的差距，直到使用者把那幾筆買進改成真正的日期與價格。
