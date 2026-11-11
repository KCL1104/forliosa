# 部署指南

Forliosa 由兩部分組成：

| 部分 | 平台 | 程式 | 網址（範例） |
|---|---|---|---|
| 前端（靜態 SPA） | Cloudflare Pages | `apps/web`（Vite + React） | `https://app.example.com` |
| 後端 API | Railway | `apps/api`（FastAPI，`Dockerfile`、`railway.toml`） | `https://api.example.com` |
| 背景工作 | Railway | 同一個 image，`railway.worker.toml` | （沒有對外網址） |
| 資料庫 | Railway PostgreSQL | | |
| 快取／佇列 | Railway Redis（選用，目前程式還沒用到） | | |

以下用 `example.com` 代表你的網域，請換成實際的網域。

> ⚠️ **目前的正式環境還不能登入**：正式登入（Email、Google）尚未實作，而 `FORLIOSA_ENV=prod` 時開發登入是關閉的。
> 部署可以先驗證網路、資料庫、cookie 與 CORS 設定，但使用者會看到「請先登入」說明頁。詳見文末「還沒準備好上線的部分」。

## 1. 網域與 cookie：一定要在同一個網站底下

登入狀態是 API 設定的 httpOnly cookie（`forliosa_session`，`SameSite=Lax`）。瀏覽器只會在**同一個網站**
（同一個可註冊網域，例如 `example.com`）的請求帶上這種 cookie，所以：

- ✅ `app.example.com`（Pages）＋ `api.example.com`（Railway）：同一個網站，可以登入。
- ❌ `forliosa.pages.dev` ＋ `forliosa-api.up.railway.app`：`pages.dev` 與 `up.railway.app` 都在 Public Suffix List，
  兩者是不同網站，cookie 不會送出，登入後所有請求仍是 401。Pages 的預覽網址（`<hash>.forliosa.pages.dev`）也一樣。

| 後端設定 | 值 | 說明 |
|---|---|---|
| `CORS_ORIGINS` | `https://app.example.com` | 前端的完整 origin，多個用逗號分隔；結尾 `/` 會自動去掉。正式環境不可用 `*`（會拒絕啟動） |
| `COOKIE_DOMAIN` | 留空，或 `.example.com` | 留空＝只屬於 `api.example.com` 的 cookie，已經夠用；要讓其他子網域也讀得到才設 |
| `COOKIE_SECURE` | 不用設 | `FORLIOSA_ENV=prod` 時自動加 `Secure`（cookie 只走 HTTPS） |

這些設定有自動測試（`apps/api/tests/api/test_deploy_config.py`）：cookie 屬性、CORS 預檢、帶 cookie 的跨子網域請求、
登出時刪除同網域的 cookie、`*` 與預設 `SESSION_SECRET` 會拒絕啟動。

## 2. Railway：API、worker、PostgreSQL、Redis

在同一個 Railway 專案裡建立四個服務，都連到這個 GitHub repo。

### 2.1 PostgreSQL（與選用的 Redis）

1. **New → Database → PostgreSQL**，服務名稱保持 `Postgres`（下面的變數引用用到這個名字）。
2. （選用）**New → Database → Redis**。目前的程式不使用 Redis（報價快取在 API 程序記憶體內），之後多副本與
   SSE 共用報價時才需要；現在建立的話只要把 `REDIS_URL` 接上即可。

### 2.2 api 服務

| 設定（Service → Settings） | 值 |
|---|---|
| Source | 這個 repo，分支 `main` |
| Root Directory | `apps/api` |
| Config File Path（Config-as-code） | `/apps/api/railway.toml` |
| Builder | Dockerfile（`railway.toml` 已指定 `apps/api/Dockerfile`） |
| Healthcheck Path | `/api/v1/health`（`railway.toml` 已設定，逾時 120 秒） |
| Networking | Generate Domain（先測試用），再加 Custom Domain `api.example.com` |

啟動時 `Dockerfile` 會先執行 `alembic upgrade head`（建立／更新資料表），再以非 root 使用者在 `$PORT` 啟動
uvicorn（已開 `--proxy-headers`，Railway 的 HTTPS 終止在代理）。

環境變數（Service → Variables）：

| 變數 | 必填 | 值 | 說明 |
|---|---|---|---|
| `FORLIOSA_ENV` | ✅ | `prod` | image 預設已是 `prod`；開發登入關閉、cookie 加 `Secure` |
| `DATABASE_URL` | ✅ | `${{Postgres.DATABASE_URL}}` | Railway 的 `postgresql://` 會自動換成 `postgresql+psycopg://` |
| `SESSION_SECRET` | ✅ | 64 字以上的隨機字串 | `python -c "import secrets; print(secrets.token_urlsafe(48))"`；沒設會拒絕啟動。更換會讓所有人登出 |
| `CORS_ORIGINS` | ✅ | `https://app.example.com` | 見第 1 節 |
| `COOKIE_DOMAIN` | | 留空或 `.example.com` | 見第 1 節 |
| `MARKET_DATA_PROVIDERS` | | `twse_mis,shioaji_data,finmind,demo` | 預設值；順序即備援順序 |
| `FINMIND_TOKEN` | 建議 | FinMind 帳號的 token | 匿名額度很小且與同一個出口 IP 共用；免費版**不可商用** |
| `CACHE_DIR` | | `var/cache`（預設，即 `/app/var/cache`） | 行情快取；建議掛 volume，見下方 |
| `REDIS_URL` | | `${{Redis.REDIS_URL}}` | 目前未使用 |
| `STREAM_INTERVAL_SECONDS` | | `5` | SSE 報價推送間隔 |
| `RAILWAY_RUN_UID` | 掛 volume 時 | `0` | Railway 的 volume 由 root 擁有，而 image 以 uid 10001 執行，寫不進去；設 `0` 改以 root 執行 |

**Volume（建議）**：Service → Volumes → 新增，Mount Path `/app/var`。行情快取（FinMind、shioaji-data 的回應）會
留在 volume 上，重新部署不會重抓、不會耗掉 FinMind 額度。沒有 volume 也能運作：快取寫入失敗只會記一行警告，
每次部署後重新抓。Railway 的 volume 只能掛在一個服務上，api 與 worker 各自需要自己的 volume。

### 2.3 worker 服務

| 設定 | 值 |
|---|---|
| Source／Root Directory | 同 api（`apps/api`） |
| Config File Path | `/apps/api/railway.worker.toml`（同一個 image，啟動指令 `python -m forliosa.worker`） |
| Networking | 不需要網域 |

環境變數：`FORLIOSA_ENV=prod`、`DATABASE_URL=${{Postgres.DATABASE_URL}}`、`MARKET_DATA_PROVIDERS`、`FINMIND_TOKEN`、
（選用）`RAILWAY_RUN_UID=0` 與自己的 volume。worker 不處理 HTTP 請求，不需要 `SESSION_SECRET`、`CORS_ORIGINS`。
資料表由 api 服務 migrate，worker 不跑 migration；第一次部署請先讓 api 啟動成功。

> 現況：worker 會在交易日盤中輪詢持股報價、收盤後把真實收盤價寫進 `prices_daily`。但 API 目前**還不讀**
> `prices_daily`，而且盤中報價快取在各自的程序記憶體（要等 Redis 版本才共用），所以 worker 現在可以先不部署；
> 部署它的好處是開始累積每日收盤價存檔。

## 3. Cloudflare Pages：前端

**Workers & Pages → Create → Pages → Connect to Git**，選這個 repo。這是 pnpm workspace（lockfile 在 repo 根目錄），
所以 Root directory 用 repo 根目錄，Pages 才會偵測到 `pnpm-lock.yaml` 並用 pnpm 安裝相依套件。

| 設定 | 值 |
|---|---|
| Production branch | `main` |
| Framework preset | None |
| Root directory | （空白，repo 根目錄） |
| Build command | `pnpm --filter @forliosa/web build` |
| Build output directory | `apps/web/dist` |
| Build watch paths（選用） | Include：`apps/web/*`、`package.json`、`pnpm-lock.yaml`、`pnpm-workspace.yaml` |

環境變數（Settings → Variables and Secrets，**Production 與 Preview 分開設定**；都是建置時寫進程式，改了要重新部署）：

| 變數 | 值 | 說明 |
|---|---|---|
| `NODE_VERSION` | `22` | 需要 Node ≥ 22.12 |
| `PNPM_VERSION` | `10.28.0` | 與根目錄 `package.json` 的 `packageManager` 一致 |
| `VITE_API_BASE_URL` | `https://api.example.com` | 會自動加上 `/api/v1`。**不設的話前端會用內建的示範資料（mock）**，不會連後端 |
| `VITE_ENABLE_DEV_LOGIN` | （不要設） | 只給連到 `FORLIOSA_ENV=dev` 後端的 staging 用：401 畫面顯示開發登入表單 |

**SPA 路由**：`apps/web/public/_redirects`（`/* /index.html 200`）會被複製到 `dist/`，重新整理 `/stock/2330.TW` 不會 404。

**自訂網域**：Pages 專案 → Custom domains → `app.example.com`。

> 也可以把 Root directory 設成 `apps/web`、Build command 設 `pnpm install --frozen-lockfile && pnpm build`、
> 輸出目錄 `dist`；但這樣 Pages 在子目錄找不到 lockfile，需另外設 `SKIP_DEPENDENCY_INSTALL=1` 避免它先用 npm 安裝。
> 用 repo 根目錄比較單純。

## 4. DNS（網域在 Cloudflare 時）

| 名稱 | 類型 | 目標 | Proxy |
|---|---|---|---|
| `app` | （Pages 加自訂網域時自動建立） | `<專案>.pages.dev` | Proxied |
| `api` | CNAME | Railway Custom Domain 畫面給的目標（`*.up.railway.app`） | **DNS only**（灰雲） |

`api` 先用 DNS only，讓 Railway 自己簽發憑證；之後若要經過 Cloudflare 代理，SSL/TLS 模式要設 Full (strict)，
並確認 SSE（`/api/v1/stream/quotes`）不會被緩衝。

## 5. 第一次部署檢查清單

1. [ ] Railway：建立 Postgres；api 服務設好 Root Directory、Config File Path 與上面的必填變數（`SESSION_SECRET`、
       `DATABASE_URL`、`CORS_ORIGINS`）。
2. [ ] api 部署成功、健康檢查通過：`curl https://<railway 網域>/api/v1/health` 回 `{"status":"ok","env":"prod",...}`，
       `providers` 裡各資料源的 `available`。
3. [ ] 部署記錄裡看到 `alembic upgrade head` 執行完成（資料表已建立）。
4. [ ] （選用）api 掛 volume `/app/var` 並設 `RAILWAY_RUN_UID=0`，重新部署後記錄中沒有 `cache write failed`。
5. [ ] 設定 `FINMIND_TOKEN`（建議）。
6. [ ] Railway api 加 Custom Domain `api.example.com`，DNS 設 CNAME（DNS only），等憑證簽發完成。
7. [ ] Cloudflare Pages：設定建置與 `NODE_VERSION`、`PNPM_VERSION`、`VITE_API_BASE_URL=https://api.example.com`，部署成功。
8. [ ] Pages 加自訂網域 `app.example.com`。
9. [ ] 確認 `CORS_ORIGINS` 剛好等於 `https://app.example.com`（大小寫、沒有路徑）。
10. [ ] 打開 `https://app.example.com`：應該看到「請先登入」說明頁（正式登入尚未推出），瀏覽器 DevTools 的
        `GET https://api.example.com/api/v1/me` 是 401、回應標頭有 `access-control-allow-origin: https://app.example.com`
        與 `access-control-allow-credentials: true`，沒有 CORS 錯誤。
11. [ ] 直接開 `https://app.example.com/stock/2330.TW` 不是 404（`_redirects` 生效）。
12. [ ] （選用）worker 服務部署，記錄中看到排程啟動。
13. [ ] 正式登入完成後再補：登入流程、cookie 在 `Application → Cookies` 顯示 `Secure`、`HttpOnly`、`SameSite=Lax`。

## 6. 還沒準備好上線的部分

| 項目 | 現況 | 上線前需要 |
|---|---|---|
| **登入** | 只有開發登入（`POST /auth/dev-login`，`FORLIOSA_ENV=dev` 才開放）；正式環境無法登入 | Email magic link 或 Google OAuth；帳號建立流程 |
| **即時行情授權** | 盤中報價來自證交所 MIS 的**非官方**端點（偶爾 502、可能被封鎖） | 商業化前改用有授權的即時行情 |
| **FinMind** | 日線、本益比、股利、匯率、加權報酬指數；免費版**不可商用**、匿名額度小 | 申請 token；商業化需 Sponsor Pro 或改用證交所／櫃買 OpenAPI（解析器已完成） |
| **美股** | 全部是示範（模擬）資料，畫面會標「示範資料」 | 決定有授權的美股資料源（Yahoo 條款禁止轉發） |
| **shioaji-data AI 研究資料** | 公司簡介、產業鏈、題材的授權「待定」，目前照樣顯示並標示來源 | 確認授權 |
| **多副本** | 報價快取在 API 程序記憶體；SSE 每個副本各自輪詢 | Redis 共用報價後才能開多個 api 副本 |
| **CSRF** | 依賴 `SameSite=Lax`＋CORS 白名單（JSON 請求需預檢） | 正式登入時一併評估 CSRF token；同網域其他子網域也算同網站 |
| **帳戶刪除 UI、只記持股快照輸入畫面** | API 已有，前端還沒有畫面 | 見 `apps/web/OPEN_QUESTIONS.md` |
| **資料備份、監控** | 未設定 | Railway Postgres 備份、錯誤追蹤（例如 Sentry）、uptime 監控 |
| **個資法** | 資料匯出／刪除帳號（M5） | 上線前的隱私權政策與服務條款 |
