# @forliosa/web

Forliosa 的前端：Vite + React 19 + TypeScript（strict）、Tailwind CSS v4、shadcn/ui（Base UI 版）、TanStack Router／Query。部署為 Cloudflare Pages 的靜態網站（SPA）。

設計系統見 [`/DESIGN.md`](../../DESIGN.md)，產品脈絡見 [`/PRODUCT.md`](../../PRODUCT.md)，使用的函式庫見 [`docs/ui-libraries.md`](../../docs/ui-libraries.md)。

## 開發

需要 Node 22（≥ 22.12）與 pnpm 10。

```bash
# 在 repo 根目錄
pnpm install
pnpm dev:web            # 或在 apps/web 裡執行 pnpm dev，開在 http://localhost:5173
```

### 連真實後端（建議）

先依 `apps/api/README.md` 啟動後端（`http://localhost:8000`，並執行過 `python -m forliosa.seed`），再：

```bash
pnpm dev:api            # 或在 repo 根目錄 pnpm dev:web:api
```

`dev:api`（`vite --mode api`）讓前端呼叫同源的 `/api/v1`，由 Vite dev proxy 轉給 `http://localhost:8000`
（可用 `FORLIOSA_API_ORIGIN` 改位址），session cookie 是同源的，不需要 CORS。沒有 session 時會自動以
`demo@forliosa.local` 開發登入（後端必須是 `FORLIOSA_ENV=dev`）；開發登入失敗時顯示登入說明頁與開發登入表單。

### 只用 mock 示範資料

`pnpm dev` 且沒有設定 `VITE_API_BASE_URL` 時，前端使用瀏覽器內的 **mock adapter**（`src/api/mock/`）：資料依 `docs/api-contract.md` 的格式產生、彼此一致（持股、損益、股利、績效、出清紀錄都由同一份示範交易紀錄算出）。

mock 預設模擬後端的 `DATA_POLICY=commercial`（只用可商用資料）：沒有「示範資料」標記；自建存檔假設從 2026-06-01 開始，更早的日線、估值、籌碼、績效回空資料＋「資料累積中」；盤中走勢沒有點、上市股票沒有個股法人、美股沒有報價（以成本計值）、含美股時績效算不出來。網址加 `?policy=personal` 改回舊的示範資料（全部帶 `is_demo: true`，記在 sessionStorage；`?policy=commercial` 切回）。示範的「今天」是 2026-11-12，正好是 00878 定期定額的扣款日。

示範情境可以用網址切換（記在 sessionStorage）：

| 網址 | 情境 |
|---|---|
| `/?mock=default` | 一般示範資料（9 檔持股、兩個帳戶） |
| `/?mock=empty` | 首次使用：沒有帳戶、沒有交易 |
| `/?mock=stress` | 壓力測試：超長股名、上千億金額、大幅虧損 |
| `/?policy=personal` | 舊的示範資料（`is_demo: true`、有盤中走勢與媒體新聞） |
| `/discussions?auth=signed-out` | 還沒登入：公開討論的清單與主題頁讀得到（精簡的外殼），其他頁面導到登入頁；`?auth=signed-in` 切回 |
| `/discussions?discuss=named` | 討論：示範使用者已經有公開暱稱「示範小資」（預設沒有，發公開內容前要先選） |
| `/discussions?discuss=suspended` | 討論：有公開暱稱，公開發言被站方暫停 7 天 |
| `/discussions?discuss=member` | 討論：示範使用者不是站方管理員（預設是，頭像選單有「站方管理」）；`?discuss=default` 切回 |

mock 的討論資料在記憶體裡（重新載入就回到示範資料）：8 則公開主題、家族投資 3 則、大學同學 1 則，含一則被站方隱藏的回覆、兩則待處理的檢舉與一筆停權。
頻率限制和後端一樣照實際的時間算：連發兩則公開內容，第二則會被擋下並說幾秒後可以再送。

## 指令

| 指令 | 說明 |
|---|---|
| `pnpm dev` | 開發伺服器（port 5173），mock 示範資料 |
| `pnpm dev:api` | 開發伺服器，連本機後端（`/api` 轉給 `localhost:8000`） |
| `pnpm build` | 型別檢查＋正式版建置，輸出到 `dist/` |
| `pnpm typecheck` | 只做型別檢查 |
| `pnpm lint` | ESLint |
| `pnpm test` | Vitest 單元測試（格式化、張／股、萬／億、漲跌慣例、隱私遮罩、河流圖、稅費、元件） |
| `pnpm smoke` | Playwright 冒煙測試（需先 `pnpm dev`）：走過所有路由、記一筆交易、隱私模式、⌘K、出清紀錄、定期定額（設定與扣款日草稿）、公告、資料來源與授權 |
| `pnpm screenshots` | 產生 `docs/screenshots/v2/` 的截圖（mock 商用模式；帳本、AI 草稿、交易、已出清、定期定額草稿、個股總覽／估值／籌碼、過去的持有、設定的定期定額、資料來源與授權、紀錄、手機問 AI；桌面 1440×900 @2x 與 iPhone 15，淺色／深色，共 50 張） |
| `pnpm screenshots:real` | 產生 `docs/screenshots/real/` 的截圖（真實後端；需先啟動後端與 `pnpm dev:api`） |
| `pnpm design:detect` | Impeccable 偵測器掃描 `src/` |

Playwright 使用環境裡預先安裝的版本（`/opt/node-tools/node_modules/playwright`），不需要 `playwright install`。

## 環境變數

| 變數 | 說明 |
|---|---|
| `VITE_API_BASE_URL` | 後端位址，例如 `https://api.example.com`（會自動加上 `/api/v1`），也可以是同源路徑 `/api/v1`。不設定時：`pnpm dev:api` 用 `/api/v1`，其他情況使用 mock。 |
| `VITE_ENABLE_DEV_LOGIN` | `true` 時非開發建置也在 401 畫面顯示開發登入表單（只給連 `FORLIOSA_ENV=dev` 後端的 staging 用） |
| `VITE_DEV_LOGIN_EMAIL` | 開發模式自動登入的 Email，預設 `demo@forliosa.local` |

所有請求都帶 `credentials: "include"`（httpOnly session cookie `forliosa_session`，`SameSite=Lax`），所以正式環境前後端要放在同一個網站底下（例如 `app.example.com` 與 `api.example.com`），後端 `CORS_ORIGINS` 要列出前端網址。`*.pages.dev` 與 `*.up.railway.app` 是不同網站，cookie 不會送出。

**登入**：App 外層的 `AuthGate`（`src/app/AuthGate.tsx`）先確認 `GET /me`；401 時開發模式自動開發登入，其他情況顯示「請先登入」說明（正式登入 Email／Google 尚未實作，見程式內的 `TODO(auth)`）。任何請求在使用中收到 401（session 過期）都會回到這個畫面。

## 部署到 Cloudflare Pages

完整步驟（含網域、cookie 與後端設定）見 [`docs/deploy.md`](../../docs/deploy.md)。摘要：

| 設定 | 值 |
|---|---|
| Framework preset | None |
| Root directory | （空白，repo 根目錄；pnpm workspace 的 lockfile 在那裡） |
| Build command | `pnpm --filter @forliosa/web build` |
| Build output directory | `apps/web/dist` |
| 環境變數 | `NODE_VERSION=22`、`PNPM_VERSION=10.28.0`、`VITE_API_BASE_URL=https://api.<你的網域>` |

`public/_redirects`（`/* /index.html 200`）讓所有路由都回到 SPA，重新整理 `/stock/2330.TW` 不會 404。

## 程式結構

```
src/
  api/            型別（types.ts）、HTTP adapter、mock adapter、TanStack Query hooks
  ai/             AI（M4 前的規則版）：記帳指令解析、依頁面的建議問題與回答、草稿與簽名入帳、桌面面板、手機全螢幕
  app/            外殼：頂部列、手機標題列與浮動分頁、頭像選單、⌘K 搜尋、偏好同步
  components/     領域元件（金額、漲跌、張股、格線區塊、示範資料、迷你走勢、分段、圖表工具）
  components/ui/  shadcn/ui（style base-nova、Base UI primitives），已依設計系統改寫
  lib/            格式化（format.ts）、升降單位與漲跌停（tick.ts）、標籤、估值／圖表的純函式
  pages/          帳本（ledger：持倉・交易・股利・績效）、個股頁（stock：六個分頁）、群組、紀錄、設定
  stores/         zustand：顯示偏好
  styles/         globals.css（設計 token）
```

資料只透過 `src/api/index.ts` 匯出的 `api`（實作 `ForliosaApi` 介面）取得；換成真實後端只需要設定 `VITE_API_BASE_URL`，頁面程式不用改。

## 授權聲明

- 走勢圖使用 [TradingView Lightweight Charts™](https://github.com/tradingview/lightweight-charts)（Apache-2.0），圖下方附文字標示。
- `src/components/ui/` 改寫自 [shadcn/ui](https://github.com/shadcn-ui/ui)（MIT）；`globals.css` 的 data-* custom variants 取自 shadcn/ui 的 `tailwind.css`（MIT）。
- 字型：Noto Sans TC、霞鶩文楷 TC（LXGW WenKai TC）（皆為 SIL Open Font License 1.1），以 @fontsource 自架。
