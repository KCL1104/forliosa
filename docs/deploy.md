# 部署指南

Forliosa 由兩部分組成：

| 部分 | 平台 | 程式 | 網址（範例） |
|---|---|---|---|
| 前端（靜態 SPA） | Cloudflare Pages | `apps/web`（Vite + React） | `https://app.example.com` |
| 後端 API | Railway | `apps/api`（FastAPI，`Dockerfile`、`railway.toml`） | `https://api.example.com` |
| 背景工作 | Railway | 同一個 image，`railway.worker.toml` | （沒有對外網址） |
| 新聞元搜尋（SearXNG，只對內） | Railway | `deploy/searxng`（官方 image 釘版本＋我們的 `settings.yml`） | **沒有對外網址**：只走私有網路 `searxng.railway.internal:8080` |
| 資料庫 | Railway PostgreSQL | | |
| 快取／佇列 | Railway Redis（選用，目前程式還沒用到） | | |

以下用 `example.com` 代表你的網域，請換成實際的網域。

> 正式登入用 **Discord** 與 **Google**（Google 是選用的，第 2.4.1 節）。Discord：要先在 Discord Developer Portal 建立應用程式（第 2.4 節），把三個 `DISCORD_*` 變數與 `FRONTEND_URL`
> 設到 api 服務上。沒設 Discord 時 API 仍可啟動，但沒有人能登入（`FORLIOSA_ENV=prod` 時開發登入是關閉的）；`FRONTEND_URL` 則是必填。

## 0. 目前的正式環境（2026-11-13 建立，尚未對外公開）

| 部分 | 實際狀態 |
|---|---|
| 前端 | Cloudflare Pages 專案 `forliosa`（直接上傳型），自訂網域 **`https://forliosa.trade`**（不是 `app.` 子網域）。由 GitHub Actions 部署：`.github/workflows/deploy-web.yml`，`main` 有前端變更時建置並上傳 |
| API | Railway 專案 `forliosa`、環境 `production`、服務 `api`，**`https://api.forliosa.trade`**，新加坡（`asia-southeast1-eqsg3a`） |
| worker | 服務 `worker`，新加坡，一個副本，沒有網域 |
| 新聞元搜尋 | 服務 **`searxng-news`**（不是 `searxng`），新加坡，沒有公開網域；api 與 worker 的 `NEWS_SEARXNG_URL=http://searxng-news.railway.internal:8080` |
| 資料庫 | 服務 `Postgres`（官方 image＋volume），新加坡。**沒有備份**：Railway 的備份與排程只給 Pro 方案（2026-11-13 API 回覆），見第 6 節 |
| DNS（Cloudflare） | 根網域 CNAME → `forliosa.pages.dev`（Proxied）；`api` CNAME → Railway 給的目標（DNS only）；`_railway-verify.api` TXT |
| 信箱 | Cloudflare Email Routing：`support@forliosa.trade` 轉寄到產品負責人的信箱 |

和下面各節寫法不同的地方（下面是通用步驟，這裡是實際做法）：

- **設定直接寫在服務上，不用設定檔**。Railway 的 API 現在拒絕指定 `railway.toml`（回覆「Config as Code is deprecated」），
  所以 api 與 worker 的 Root Directory（`apps/api`）、Dockerfile 路徑、健康檢查（`/api/v1/health`，120 秒）、重啟策略、
  worker 的啟動指令（`python -m forliosa.worker`）、Watch Paths（`apps/api/**`）都是直接設在服務上。
  repo 裡的 `apps/api/railway.toml`、`railway.worker.toml` 留作對照，改它們**不會**改到線上設定。
- **區域要用環境修補設定**。用 API 建服務時指定的區域會被忽略（會落在美西）；要用 `environmentPatchCommit` 把
  `services.<id>.deploy.multiRegionConfig` 設成 `{"us-west2": null, "asia-southeast1-eqsg3a": {"numReplicas": 1}}`。
  資料庫要照這個順序建：先設區域 → 建 volume → 設變數 → 指定 image → 部署；順序錯了 volume 會建在美西。
- **引用其他服務的變數會記住服務本身**。`${{Postgres.DATABASE_URL}}` 設好之後如果把 `Postgres` 服務刪掉重建，
  引用會變成空字串（Alembic 報 `Could not parse SQLAlchemy URL`）；要重新設一次。
- **前端不能從開發沙盒直接上傳**。wrangler 上傳檔案那一步用的是另一個短期憑證，沙盒的代理會把它換掉；所以只走 GitHub Actions
  （repo secrets：`CLOUDFLARE_API_TOKEN`、`CLOUDFLARE_ACCOUNT_ID`）。
- api 的三個 `DISCORD_*` 要在 Railway 的 Raw Editor **一次貼上**再部署；只設一部分 API 會拒絕啟動（舊的部署會繼續服務，但新版本上不去）。
- 產品負責人先前建立的 `SearXNG`（第三方範本，有公開網址）與 `Redis`、兩個重建資料庫時留下的 volume、Redis 的 volume，
  程式都沒有使用，2026-11-13 經產品負責人確認後已刪除。專案裡現在只有 `Postgres`、`api`、`worker`、`searxng-news` 四個服務。
- **Google 登入**（2026-11-13 加上）：api 服務有 `GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`（產品負責人填的）與
  `GOOGLE_REDIRECT_URI=https://api.forliosa.trade/api/v1/auth/google/callback`。三個沒設齊時 Google 登入只是不出現，不會拒絕啟動。

2026-11-13 的驗證結果：api 部署記錄有 `Context impl PostgresqlImpl` 與 0001→0013 全部遷移；
`GET /api/v1/health` 200（`env: prod`、`data_policy: commercial`）；`https://forliosa.trade` 來源的 CORS 預檢通過；
未登入時 `/me` 401、公開討論清單 200；`/auth/providers` 回 `{"discord": false, "dev_login": false}`（Discord 變數還沒設）；
worker 記錄有 `worker started: …` 與 `close watch: TPEX has published the closes of 2026-11-13`。
第 5 節清單裡還沒做的：7、8 的前端第一次部署（等 repo secrets）、10、11、13（等 Discord 變數）、14、15 的 `searxng-check`。

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

## 2. Railway：API、worker、SearXNG、PostgreSQL、Redis

在同一個 Railway 專案裡建立這些服務：PostgreSQL（與選用的 Redis）、api、worker、searxng（後三個都連到這個 GitHub repo）。

### 2.1 PostgreSQL（與選用的 Redis）

1. **New → Database → PostgreSQL**，服務名稱保持 `Postgres`（下面的變數引用用到這個名字）。
2. （選用）**New → Database → Redis**。目前的程式不使用 Redis（報價快取在 API 程序記憶體內），之後多副本與
   SSE 共用報價時才需要；現在建立的話只要把 `REDIS_URL` 接上即可。

### 2.2 api 服務

| 設定（Service → Settings） | 值 |
|---|---|
| Source | 這個 repo，分支 `main` |
| Root Directory | `apps/api` |
| Config File Path（Config-as-code） | `/apps/api/railway.toml`（2026-11 起 Railway 的 API 不再接受設定檔，改成把下面幾項直接設在服務上，見第 0 節） |
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
| `SESSION_SECRET` | ✅ | 64 字以上的隨機字串 | `python -c "import secrets; print(secrets.token_urlsafe(48))"`；沒設會拒絕啟動。更換會讓所有人登出、群組頻道的 Discord webhook 要重設、交易動態的舊留言找不到對象（見 `apps/api/CONTRACT_NOTES.md`「金鑰與加密」） |
| `CORS_ORIGINS` | ✅ | `https://app.example.com` | 見第 1 節；也是寫入請求的 `Origin` 允許清單（CSRF） |
| `FRONTEND_URL` | ✅ | `https://app.example.com` | 前端網址：Discord 登入後導回這裡、邀請連結也用它。必須是 `CORS_ORIGINS` 之一、https，否則拒絕啟動 |
| `DISCORD_CLIENT_ID` | 登入用 | Discord 應用程式的 Client ID | 見 2.4 節；三個 `DISCORD_*` 要一起設，只設一部分會拒絕啟動 |
| `DISCORD_CLIENT_SECRET` | 登入用 | Discord 應用程式的 Client Secret | **機密**：只放在 Railway Variables，不要貼到聊天、issue 或程式碼；程式不會寫進 log |
| `DISCORD_REDIRECT_URI` | 登入用 | `https://api.example.com/api/v1/auth/discord/callback` | 必須和 Developer Portal 的 Redirect 一字不差，https |
| `GOOGLE_CLIENT_ID` | Google 登入用（選用） | Google Cloud 的 OAuth 用戶端 ID（`….apps.googleusercontent.com`） | 見 2.4.1 節。三個 `GOOGLE_*` 沒設齊時 Google 登入不出現（啟動時記一行警告），**不會**拒絕啟動 |
| `GOOGLE_CLIENT_SECRET` | Google 登入用（選用） | OAuth 用戶端密鑰（`GOCSPX-…`） | **機密**：只放在 Railway Variables；建立用戶端時只顯示一次 |
| `GOOGLE_REDIRECT_URI` | Google 登入用（選用） | `https://api.example.com/api/v1/auth/google/callback` | 必須和 Google Cloud Console「已授權的重新導向 URI」一字不差，https |
| `TELEGRAM_BOT_TOKEN` | Telegram 推播用 | BotFather 給的 token | 見 2.5 節；**機密**，只放在 Railway Variables。api 用它判斷 `telegram_available`，worker 用它收發訊息 |
| `TELEGRAM_BOT_USERNAME` | Telegram 推播用 | bot 的帳號（不含 `@`），例如 `ForliosaBot` | 兩個都設才會出現「連結 Telegram 群組」 |
| `ADMIN_EMAILS` | 公開討論管理用 | `you@example.com,other@example.com` | 站方管理員：逗號分隔的 email，不分大小寫，和登入帳號的 email（Discord 已驗證的信箱）比對。管理員可以看公開討論的檢舉、隱藏內容、暫停某人的公開發言（`/api/v1/admin/discussions/*`）；其他人呼叫一律 404。不設就沒有人能處理檢舉。管理員看不到群組內容。改了要重新部署才生效 |
| `TERMS_VERSION` | 條款定稿後 | 例如 `2026-11-13` | 服務條款與隱私權政策目前的版本（建議用生效日期）。設了之後：新帳號建立時記下這個版本；版本改了，舊帳號登入後會看到一行「服務條款與隱私權政策已更新」要按「知道了」。不設就不追蹤版本。兩份文件還是草稿時先不要設 |
| `TERMS_EFFECTIVE_DATE` | 選用 | `2026-12-01` | 新版條款從哪一天生效。設了之後，條款更新的那一行寫「12/1 起適用新版服務條款與隱私權政策」（服務條款承諾生效前 14 天公告）。沒設 `TERMS_VERSION` 時不看這個 |
| `TERMS_SUMMARY` | 選用 | `新增匯出資料與刪除帳號的說明` | 改了什麼的一句話（一行，最多 120 字），接在那一行後面 |
| `AI_MARKET_SUMMARY_ENABLED` | 選用（api 與 worker） | `true` | 市場頁的 AI 收盤重點（每個交易日一則、全站共用，約 US$0.05／天）；`false` 就不呼叫模型，頁面沒有這一塊 |
| `PRICE_HISTORY_SOURCE` | 選用（api 與 worker 都要設） | `yahoo` | 存檔開始以前的日線用 Yahoo Finance 回補（產品負責人 2026-11-13 決定；不是授權來源）。worker 每 10 分鐘回補一批（每檔一個請求，持有與觀察中的先做），全部問過一次就停，之後每天看一次有沒有新掛牌的；api 的走勢圖、技術指標、走勢小圖才會讀這些列。沒設＝不抓也不讀。看進度：`uv run python -m forliosa.history_backfill status`；整批刪除：`uv run python -m forliosa.history_backfill drop`（刪完把這個變數拿掉） |
| `PRICE_HISTORY_YEARS` | 選用 | `5` | 回補幾年（1–10，預設 5） |
| `CLAUDE_API_KEY_1`、`_2`、`_3` | AI 用 | Claude API 金鑰（三把，分屬三個 workspace） | **機密**：只放在 Railway Variables。「問 AI」、為什麼、法人觀點都在 api 服務執行，沒設時這些功能顯示「AI 暫時無法使用」。worker 也要設同樣三把（群組週報、新聞補缺、公司簡介）。建議同時在 Anthropic Console 替每個 workspace 設每月花費上限 |
| `SEC_CONTACT_EMAIL` | 美股基本面用 | 一個聯絡用 email | 只放在對 SEC EDGAR 請求的 User-Agent（SEC 要求自動化存取要留聯絡方式）；沒設時不抓美股基本面與申報。api 與 worker 都要設 |
| `COOKIE_DOMAIN` | | 留空或 `.example.com` | 見第 1 節 |
| `DATA_POLICY` | | `commercial`（預設） | 只用可合法商用的政府開放資料與自己的存檔；**不要改成 `personal`**（見 `docs/research/data-sources-licensing.md`） |
| `MARKET_DATA_PROVIDERS` | | 留空 | 用程式預設（開放資料與存檔）；商用模式下 FinMind、MIS 不會啟用 |
| `CACHE_DIR` | | `var/cache`（預設，即 `/app/var/cache`） | 行情快取；建議掛 volume，見下方 |
| `REDIS_URL` | | `${{Redis.REDIS_URL}}` | 目前未使用 |
| `STREAM_INTERVAL_SECONDS` | | `5` | SSE 報價推送間隔 |
| `NEWS_SEARXNG_URL` | | `http://searxng.railway.internal:8080` | 私有網路上的 SearXNG（2.6 節）；不設時 `FORLIOSA_ENV=prod` 就是這個值。也可寫 `http://${{searxng.RAILWAY_PRIVATE_DOMAIN}}:8080`。api 本身不查 SearXNG，設了是為了在 api 的 shell 也能跑 `searxng-check` |
| `RAILWAY_RUN_UID` | 掛 volume 時 | `0` | Railway 的 volume 由 root 擁有，而 image 以 uid 10001 執行，寫不進去；設 `0` 改以 root 執行 |

**Volume（建議）**：Service → Volumes → 新增，Mount Path `/app/var`。開放資料與 shioaji-data 的快取會
留在 volume 上，重新部署不會重抓。沒有 volume 也能運作：快取寫入失敗只會記一行警告，
每次部署後重新抓。Railway 的 volume 只能掛在一個服務上，api 與 worker 各自需要自己的 volume。

### 2.3 worker 服務

| 設定 | 值 |
|---|---|
| Source／Root Directory | 同 api（`apps/api`） |
| Config File Path | `/apps/api/railway.worker.toml`（同一個 image，啟動指令 `python -m forliosa.worker`） |
| Networking | 不需要網域 |

環境變數：

| 變數 | 必填 | 說明 |
|---|---|---|
| `FORLIOSA_ENV` | ✅ | `prod` |
| `DATABASE_URL` | ✅ | `${{Postgres.DATABASE_URL}}` |
| `SESSION_SECRET` | ✅ | **和 api 服務同一個值**（建議用 Railway 的共用變數或 `${{api.SESSION_SECRET}}` 引用）。群組推播要用它解開加密保存的 Discord webhook；`FORLIOSA_ENV=prod` 沒設會拒絕啟動。值不同的話所有 Discord 頻道會被判定「解不開」而停用 |
| `FRONTEND_URL` | 建議 | 和 api 相同；推播訊息裡的群組頁連結用它（沒設就不附連結） |
| `CLAUDE_API_KEY_1..3` | 週報用 | 群組 AI 週報（每週六 20:00）；沒設時週報只有數字、標成失敗。可用 `AI_DIGEST_ENABLED=false` 關掉 AI |
| `TELEGRAM_BOT_TOKEN`、`TELEGRAM_BOT_USERNAME` | Telegram 推播用 | 和 api 相同（見 2.5 節） |
| `NEWS_SEARXNG_URL` | 建議 | `http://searxng.railway.internal:8080`（見 2.6 節）。新聞 worker 用它查 SearXNG；不設時 prod 預設就是這個值，服務名稱不是 `searxng` 時一定要設。設成空字串或 `NEWS_SEARXNG_ENABLED=false` 會關掉 SearXNG |
| `DATA_POLICY` | | `commercial`（預設） |
| `RAILWAY_RUN_UID` | 掛 volume 時 | `0`，搭配自己的 volume |

worker 不處理 HTTP 請求，不需要 `CORS_ORIGINS`、`DISCORD_*`。資料表由 api 服務 migrate，worker 不跑 migration；第一次部署請先讓 api 啟動成功。
**worker 只能有一個副本**：Telegram 的 `getUpdates` 同時只能有一個程式在收，兩個副本會互相搶（也會重複送推播）。

> 現況：worker 負責開放資料存檔（含證期局〈證券投資信託基金每日淨值〉的 ETF 淨值，交易日 21:40 與 08:10；只下載 `www.sitca.org.tw` 上那一個 CSV）、收盤價、股利自動入帳、AI 保存期限、個股頁「新聞報導」（GDELT＋SearXNG，每 45 分鐘），以及**群組推播與群組 AI 週報**（M5）。
> **收盤價公布偵測**（`close_watch`）：交易所公布收盤價的時間不固定（觀察到當晚到隔天清晨），所以交易日 13:35 到隔天 08:30，worker 每 15 分鐘對證交所與櫃買 OpenAPI 的收盤檔各發一個很小的條件式請求（沒換檔就是 304）；一換成當天的就把那個市場存檔一次，網站上的收盤價隨即更新。不需要任何設定；worker 沒在跑的話，收盤價要等到 08:10、14:40、21:40 的固定排程。記錄裡會看到 `close watch: TWSE has published the closes of 2026-11-13`。
> 要用群組的 Discord／Telegram 推播或週報，就一定要部署 worker。

### 2.4 Discord 登入（Discord Developer Portal）

1. 用產品負責人的 Discord 帳號打開 <https://discord.com/developers/applications> → **New Application**，名稱填 `Forliosa`
   （使用者授權時會看到這個名稱與圖示）。
2. **OAuth2** 頁：
   - 複製 **Client ID** → Railway api 服務的 `DISCORD_CLIENT_ID`。
   - **Client Secret** 按 Reset Secret 後複製 → `DISCORD_CLIENT_SECRET`（只會顯示一次；外洩時回這裡重設，並更新 Railway）。
   - **Redirects** 加一筆 `https://api.example.com/api/v1/auth/discord/callback`（換成實際的 API 網域），同一個字串設成 `DISCORD_REDIRECT_URI`。
     本機開發另加 `http://localhost:8000/api/v1/auth/discord/callback`（開發環境可以用 http；正式環境必須 https）。
   - 不需要 bot、不需要 OAuth2 URL Generator：登入只用 `identify` 與 `email` 兩個 scope，由 API 自己組授權網址。
3. （選用）**General Information** 上傳圖示、填隱私權政策與服務條款網址（公開給其他人用之前建議補上）。
4. Railway api 服務設好 `FRONTEND_URL`、三個 `DISCORD_*` 後重新部署，確認：
   - `curl https://api.example.com/api/v1/auth/providers` 回 `{"discord": true, "google": false, "dev_login": false}`（設了 Google 之後 `google` 是 `true`）。
   - 打開 `https://app.example.com/login` 按「以 Discord 登入」→ Discord 授權頁 → 回到前端，`GET /api/v1/me` 是 200。
5. 登入規則（帳號對應、已驗證 email、失敗代碼 `oauth_*`）見 `docs/api-contract.md`「分享（M5）」→「登入」。

### 2.4.1 Google 登入（Google Cloud Console）

選用。設好之後登入頁多一顆「用 Google 登入」；同一個已驗證的 Email 用 Google 或 Discord 登入是同一個帳號。

1. <https://console.cloud.google.com/> 建立專案（名稱 `forliosa`）。
2. 「API 和服務」→「OAuth 同意畫面」（新版叫 Google Auth Platform）→ 開始：應用程式名稱 `Forliosa`、支援電子郵件、目標對象選「外部」。
3. 「品牌」：首頁 `https://app.example.com`、隱私權政策 `…/privacy`、服務條款 `…/terms`、已授權網域填前端的網域。
4. 「資料存取」：加入 `openid`、`userinfo.email`、`userinfo.profile` 三個範圍（都不是敏感範圍，不用送審）。
5. 「用戶端」→ 建立用戶端 → 網頁應用程式 → 「已授權的重新導向 URI」填 `https://api.example.com/api/v1/auth/google/callback`（「已授權的 JavaScript 來源」不用填）。
   用戶端 ID → `GOOGLE_CLIENT_ID`；用戶端密鑰（只顯示一次）→ `GOOGLE_CLIENT_SECRET`；同一個 callback 網址 → `GOOGLE_REDIRECT_URI`。
6. 「目標對象」→ 發布應用程式（預設「測試中」只有手動加的測試使用者能登入）。
7. 確認：`curl https://api.example.com/api/v1/auth/providers` 的 `google` 是 `true`；登入頁按「用 Google 登入」→ Google 的帳號選擇畫面 → 回到前端。
   Google 顯示「redirect_uri_mismatch」＝第 5 步的網址和 `GOOGLE_REDIRECT_URI` 不一樣；「存取權遭封鎖：這個應用程式尚未完成驗證／僅限測試使用者」＝第 6 步還沒發布。

### 2.5 Telegram bot（群組推播）

群組可以把動態與週報推播到 Telegram 群組；這需要一個屬於 Forliosa 的 bot。不設定也可以，畫面上就不會出現 Telegram 選項。

1. 在 Telegram 找 **@BotFather**，傳 `/newbot`：
   - 名稱（顯示用）：`Forliosa`。
   - 帳號（必須以 `bot` 結尾，例如 `ForliosaBot`）→ 這就是 `TELEGRAM_BOT_USERNAME`（不含 `@`）。
   - BotFather 回覆的 token（`123456789:AA…`）→ `TELEGRAM_BOT_TOKEN`。**這是機密**：只貼到 Railway Variables，不要貼到聊天、issue 或程式碼；
     外洩時對 BotFather 傳 `/revoke` 換一組，再更新 Railway（api 與 worker 兩個服務）。
2. 建議的 BotFather 設定：
   - `/setprivacy` → **Enable**（預設就是開）：bot 在群組裡只收到明確給它的指令（例如 `/link@ForliosaBot 連結碼`），看不到其他聊天內容。
   - `/setjoingroups` → Enable（預設）：才能把 bot 加進群組。
   - （選用）`/setcommands` → `link - 連結 Forliosa 群組`；`/setdescription` 寫一句用途說明。
   - **不要**設定 webhook（`setWebhook`）：worker 用 `getUpdates` 輪詢，設了 webhook 會讓輪詢失敗。
3. 把兩個變數設到 **api 與 worker** 兩個服務，重新部署。確認：
   - 群組頁的推播設定出現 Telegram（`GET /api/v1/groups/{id}/channels` 的 `telegram_available` 是 `true`）。
   - 群主按「連結 Telegram 群組」取得連結碼，把 bot 加進 Telegram 群組，在群組裡傳 `/link@ForliosaBot 連結碼`（10 分鐘內）；
     bot 回覆「已連結 Forliosa 群組「…」」，app 裡顯示那個 Telegram 群組的名稱。
4. Discord 群組頻道不需要設定伺服器：群主在 Discord 頻道設定 → 整合 → Webhook 建立後，把網址貼到 app（網址加密保存，畫面只顯示最後 4 碼）。

推播規則（只送開了「推播」的成員、15 分鐘後才送、重試與自動停用）見 `docs/api-contract.md`「分享（M5）」→「推播」。

### 2.6 SearXNG（新聞元搜尋，只對內）

產品負責人決定（`PRODUCT.md`「相關新聞」第三輪）：個股頁「新聞報導」除了 GDELT，也用我們自己架的 SearXNG 以中文公司名查新聞，**預設開啟**。
SearXNG 是元搜尋：它替我們去問 Bing News、DuckDuckGo News、Brave News（`deploy/searxng/settings.yml` 只開這三個新聞引擎）。

> **風險（產品負責人已接受）**：自動查詢上游搜尋引擎違反它們的使用條款（契約風險；被封鎖後這個來源就失效）。
> 我們的做法：只取標題、媒體、時間與連結；一次只查一個、間隔至少 10 秒；引擎回 CAPTCHA／429／拒絕存取就暫停它，全部引擎都停時整個 SearXNG 暫停；
> 不換 IP、不用代理。研究與條件見 `docs/research/news-and-external-sources.md` §10。

| 設定（Service → Settings） | 值 |
|---|---|
| 服務名稱 | `searxng`（私有網址就是 `searxng.railway.internal`；改名的話 api／worker 的 `NEWS_SEARXNG_URL` 要跟著改） |
| Source | 這個 repo，分支 `main` |
| Root Directory | `deploy/searxng` |
| Config File Path | `/deploy/searxng/railway.toml`（Dockerfile；健康檢查 `/healthz`） |
| Networking | **不要** Generate Domain、不要加 Custom Domain：只用 Private Networking。SearXNG 的 limiter 是關的，有公開網址就等於開放給任何人代查 |
| Volumes | 不需要（不要掛在 `/etc/searxng`，會蓋掉 image 裡的 `settings.yml`） |
| Replicas | 1 |

環境變數（searxng 服務）：

| 變數 | 必填 | 值 | 說明 |
|---|---|---|---|
| `SEARXNG_SECRET` | ✅ | 64 字以上的隨機字串 | `python -c "import secrets; print(secrets.token_urlsafe(48))"`；**機密**，只放在 Railway Variables。沒設的話 SearXNG 拒絕啟動（`settings.yml` 的 `secret_key` 只是佔位字）。api／worker 不需要它 |
| `PORT` | ✅ | `8080` | Railway 的健康檢查打 `PORT` 這個埠；SearXNG 固定聽 `[::]:8080`（IPv6＋IPv4），**不讀** `$PORT`。沒設的話 Railway 可能注入別的埠，`/healthz` 打不到、部署一直不健康。不要改成別的值（api／worker 的 `NEWS_SEARXNG_URL` 用 8080） |

不要設 `TZ`：SearXNG 回的發布時間沒有時區時，worker 當成 UTC（容器預設）。

第一次部署（以及每次升級或改 `settings.yml` 後）看 searxng 服務的 Deploy Logs：要看到 granian 的啟動訊息、服務維持 Active，**沒有** `Traceback`、`KeyError` 或
`Invalid settings.yml`。SearXNG 啟動失敗時 worker 只會把它當成連不上、默默暫停，不會有錯誤畫面，所以只能從這裡發現。
（2026-11-12 審查找到一個這樣的錯誤：`keep_only` 拿掉了 `brave` 引擎，但 `brave.news` 預設共用它的連線設定，啟動時 `KeyError: 'brave'`；
已在 `settings.yml` 的 `outgoing.networks` 補上 `brave: {}`，`apps/api/tests/news/test_searxng.py` 會對照釘住版本的預設引擎定義檢查。）

api 與 worker 的 `NEWS_SEARXNG_URL` 設成 `http://searxng.railway.internal:8080`（見 2.2、2.3 節；`FORLIOSA_ENV=prod` 不設時預設就是這個）。
SearXNG 連不上時（還沒部署、重啟中、私有網路沒開），worker 只會把它暫停 15 分鐘起、每次加倍到 4 小時，GDELT 與 AI 搜尋照常，使用者不會看到錯誤。

部署後檢查（在 worker 或 api 服務的 shell，例如 `railway ssh`）：

```
python -m forliosa.news searxng-check "台積電"
```

會印出健康檢查、結果數、各引擎的結果數與沒有回應的引擎（只印 SearXNG 的網址主機與埠，不印任何密鑰，也不寫資料庫）。
某個引擎顯示 `CAPTCHA`／`too many requests`／`access denied` 表示它擋了我們：worker 會自動暫停它，不要換 IP 或改 User-Agent 去繞。

升級 SearXNG：`deploy/searxng/Dockerfile` 釘的是一個已發布兩週以上的 tag（目前 `2026.10.28-c360868e5`）與它的 digest；
換新版時選一個至少兩週前發布的 tag、tag 與 digest 一起改、看一下該版 `searx/settings.yml` 有沒有改名的設定，
把該版保留引擎（與它們 `network:` 指到的引擎）的預設定義抄進 `apps/api/tests/news/fixtures/searxng_default_engines_<tag>.yml`（測試會要求），
部署後看 searxng 的記錄沒有 traceback，再跑一次 `searxng-check`。

本機開發：`cp deploy/searxng/.env.example deploy/searxng/.env`、填 `SEARXNG_SECRET`，`docker compose -f deploy/searxng/docker-compose.yml up -d --build`
（只綁 `127.0.0.1:8080`）；`docker compose -f deploy/searxng/docker-compose.yml logs searxng` 確認沒有 traceback；`FORLIOSA_ENV=dev` 的 API／worker 預設就用 `http://localhost:8080`。
compose 把 repo 裡的 `deploy/searxng/settings.yml` 唯讀掛進容器：官方 image 對 `/etc/searxng` 宣告了 `VOLUME`，不這樣掛的話重建的容器會沿用舊的匿名 volume、
繼續讀第一次建置時的 `settings.yml`。改了 `settings.yml` 之後 `docker compose -f deploy/searxng/docker-compose.yml restart searxng` 就會生效。

> **沒有在這個雲端沙盒測過**：沙盒連不到上游搜尋引擎（Bing、DuckDuckGo、Brave），也沒有 Docker，所以 image 沒有實際建置、
> 也沒有真的查過（只從 Docker Hub 確認了 tag、digest 與 image 設定：`/etc/searxng/settings.yml`、`[::]:8080`）；
> 啟動時的設定合併與網路參照只對照了該版原始碼（沙盒不能執行 SearXNG）。
> 程式的測試用依 SearXNG JSON 格式手寫的**合成**回應（`apps/api/tests/news/fixtures/searxng_*_synthetic.json`）。
> 第一次部署後請跑上面的 `searxng-check`，確認三個引擎都有結果、`unresponsive_engines` 是空的。

## 3. Cloudflare Pages：前端

> 實際環境用的是 GitHub Actions 上傳（`.github/workflows/deploy-web.yml`，見第 0 節），不是下面的 Git 整合；兩種做法擇一即可。

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
5. [ ] 確認 `DATA_POLICY` 是 `commercial`（預設），`GET /api/v1/meta/attributions` 列出資料來源與授權標示。
6. [ ] Railway api 加 Custom Domain `api.example.com`，DNS 設 CNAME（DNS only），等憑證簽發完成。
7. [ ] Cloudflare Pages：設定建置與 `NODE_VERSION`、`PNPM_VERSION`、`VITE_API_BASE_URL=https://api.example.com`，部署成功。
8. [ ] Pages 加自訂網域 `app.example.com`。
9. [ ] 確認 `CORS_ORIGINS` 剛好等於 `https://app.example.com`（大小寫、沒有路徑）。
10. [ ] 打開 `https://app.example.com`：未登入時看到登入頁，瀏覽器 DevTools 的
        `GET https://api.example.com/api/v1/me` 是 401、回應標頭有 `access-control-allow-origin: https://app.example.com`
        與 `access-control-allow-credentials: true`，沒有 CORS 錯誤。
11. [ ] 直接開 `https://app.example.com/stock/2330.TW` 不是 404（`_redirects` 生效）。
12. [ ] worker 服務部署（`SESSION_SECRET` 與 api 相同、只有一個副本），記錄中看到排程啟動（`worker started: …, group_push, telegram_poll,
        group_digests, …`）。
13. [ ] Discord 登入（第 2.4 節）：登入後 cookie 在 `Application → Cookies` 顯示 `forliosa_session` 有 `Secure`、`HttpOnly`、`SameSite=Lax`；
        授權過程中的 `__Host-forliosa_oauth` 在回到前端後就被刪除。
14. [ ] （選用）群組推播：建一個測試群組，貼上 Discord 測試頻道的 webhook（頻道收到「推播已連結」的測試訊息）；有設 Telegram bot 時照 2.5 節
        連結一個 Telegram 測試群組。開了「推播」與「交易動態」的成員記一筆今天的交易，約 15 分鐘後頻道收到訊息。
15. [ ] SearXNG（第 2.6 節）：searxng 服務部署成功、**沒有**任何公開網域；`SEARXNG_SECRET` 與 `PORT=8080` 已設；Deploy Logs 沒有 `Traceback`／`KeyError`、
        健康檢查通過；在 worker 的 shell 跑
        `python -m forliosa.news searxng-check "台積電"`，健康檢查 OK、三個引擎都有結果。約 45 分鐘後 worker 記錄出現
        `news refresh: … requests {'gdelt': …, 'searxng': …}`，個股頁「新聞報導」下方出現「另有 SearXNG 元搜尋」。

## 6. 還沒準備好上線的部分

| 項目 | 現況 | 上線前需要 |
|---|---|---|
| **登入** | Discord OAuth（M5，後端完成；開放任何 Discord 帳號註冊） | 建立 Discord 應用程式（2.4 節）；隱私權政策與服務條款 |
| **盤中行情** | 沒有授權來源，1 日走勢為空狀態（證交所網站與 MIS 依條款不得自動擷取） | 若需要：向證交所購買延遲行情（約每月 NT$30,000） |
| **上市個股三大法人、外資持股** | 開放資料沒有逐檔資料；上櫃股票有 | 已決定（2026-11-12）：不寄信、不購買；個股頁顯示空狀態並可直接問 AI。日後要用：Data E-Shop「三大法人買賣超檔」（約每月 NT$3,000）或書面同意 |
| **美股** | 商用模式下沒有報價與績效（價格為空）；基本面可用 SEC EDGAR（需聯絡信箱） | 決定美股價格來源（使用者自備 Tiingo key 或購買商用授權） |
| **shioaji-data AI 研究資料** | 公司簡介、產業鏈、題材的授權「待定」，商用模式下不顯示 | 確認授權 |
| **多副本** | 報價快取在 API 程序記憶體；SSE 每個副本各自輪詢 | Redis 共用報價後才能開多個 api 副本 |
| **CSRF** | `SameSite=Lax`＋CORS 白名單，另外所有寫入請求檢查 `Origin` 必須在 `CORS_ORIGINS` 內（M5） | 同網域其他子網域也算同網站：不要把不受信任的服務放在同一個網域底下 |
| **群組週報與頻道推播** | 後端完成（M5 第二批）：worker 每分鐘推播、每週六 20:00 產生週報；前端的週報與頻道設定畫面還沒接 | 部署 worker（`SESSION_SECRET` 與 api 相同、單一副本、Claude 金鑰）；要用 Telegram 時建立 bot（2.5 節） |
| **帳戶刪除 UI、只記持股快照輸入畫面** | API 已有，前端還沒有畫面 | 見 `apps/web/OPEN_QUESTIONS.md` |
| **SearXNG 新聞元搜尋** | 預設開啟（2.6 節）；只用合成回應測過，沒有實際建置或查詢過 | 第一次部署後跑 `searxng-check`；SearXNG 送給上游搜尋引擎的是瀏覽器樣式的請求（SearXNG 本身的做法），要產品負責人確認可以接受（見 `apps/api/CONTRACT_NOTES.md`「2026-11-12 新聞報導」待確認） |
| **資料備份、監控** | 未設定。Railway 的 volume 備份只給 Pro 方案（目前的方案不能開） | 正式開放前擇一：升級 Railway Pro 用內建備份，或加一個每天 `pg_dump` 到 Cloudflare R2 的工作；錯誤追蹤（例如 Sentry）、uptime 監控 |
| **個資法** | 資料匯出／刪除帳號（M5） | 上線前的隱私權政策與服務條款 |
