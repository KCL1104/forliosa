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

`pnpm dev` 且沒有設定 `VITE_API_BASE_URL` 時，前端使用瀏覽器內的 **mock adapter**（`src/api/mock/`）：資料依 `docs/api-contract.md` 的格式產生、彼此一致（持股、損益、股利、績效都由同一份示範交易紀錄算出），而且全部帶 `is_demo: true`，畫面上會出現「示範資料」章。

示範情境可以用網址切換（記在 sessionStorage）：

| 網址 | 情境 |
|---|---|
| `/?mock=default` | 一般示範資料（9 檔持股、兩個帳戶） |
| `/?mock=empty` | 首次使用：沒有帳戶、沒有交易 |
| `/?mock=stress` | 壓力測試：超長股名、上千億金額、大幅虧損 |

## 指令

| 指令 | 說明 |
|---|---|
| `pnpm dev` | 開發伺服器（port 5173），mock 示範資料 |
| `pnpm dev:api` | 開發伺服器，連本機後端（`/api` 轉給 `localhost:8000`） |
| `pnpm build` | 型別檢查＋正式版建置，輸出到 `dist/` |
| `pnpm typecheck` | 只做型別檢查 |
| `pnpm lint` | ESLint |
| `pnpm test` | Vitest 單元測試（格式化、張／股、萬／億、漲跌慣例、隱私遮罩、河流圖、稅費、元件） |
| `pnpm smoke` | Playwright 冒煙測試（需先 `pnpm dev`）：走過所有路由、記一筆交易、隱私模式、⌘K |
| `pnpm screenshots` | 產生 `docs/screenshots/` 的截圖（mock 資料；桌面 1440×900 @2x 與 iPhone 15，淺色／深色） |
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
  app/            外殼：側欄、頂部列、手機底部分頁、⌘K 搜尋、偏好同步
  components/     領域元件（金額、漲跌、張股、章、Panel、圖表工具）
  components/ui/  shadcn/ui（style base-nova、Base UI primitives），已依設計系統改寫
  lib/            格式化（format.ts）、標籤、估值／K 線／配置的純函式
  pages/          各頁面
  stores/         zustand：顯示偏好、自選
  styles/         globals.css（設計 token）
```

資料只透過 `src/api/index.ts` 匯出的 `api`（實作 `ForliosaApi` 介面）取得；換成真實後端只需要設定 `VITE_API_BASE_URL`，頁面程式不用改。

## 授權聲明

- K 線圖使用 [TradingView Lightweight Charts™](https://github.com/tradingview/lightweight-charts)（Apache-2.0），圖上保留 TradingView 標誌，K 線分頁附文字說明。
- `src/components/ui/` 改寫自 [shadcn/ui](https://github.com/shadcn-ui/ui)（MIT）；`globals.css` 的 data-* custom variants 取自 shadcn/ui 的 `tailwind.css`（MIT）。
- 字型：Source Sans 3、Noto Sans TC（SIL Open Font License 1.1），以 @fontsource 自架。
