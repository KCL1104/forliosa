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

沒有設定 `VITE_API_BASE_URL` 時，前端使用瀏覽器內的 **mock adapter**（`src/api/mock/`）：資料依 `docs/api-contract.md` 的格式產生、彼此一致（持股、損益、股利、績效都由同一份示範交易紀錄算出），而且全部帶 `is_demo: true`，畫面上會出現「示範資料」章。

示範情境可以用網址切換（記在 sessionStorage）：

| 網址 | 情境 |
|---|---|
| `/?mock=default` | 一般示範資料（9 檔持股、兩個帳戶） |
| `/?mock=empty` | 首次使用：沒有帳戶、沒有交易 |
| `/?mock=stress` | 壓力測試：超長股名、上千億金額、大幅虧損 |

## 指令

| 指令 | 說明 |
|---|---|
| `pnpm dev` | 開發伺服器（port 5173） |
| `pnpm build` | 型別檢查＋正式版建置，輸出到 `dist/` |
| `pnpm typecheck` | 只做型別檢查 |
| `pnpm lint` | ESLint |
| `pnpm test` | Vitest 單元測試（格式化、張／股、萬／億、漲跌慣例、隱私遮罩、河流圖、稅費、元件） |
| `pnpm smoke` | Playwright 冒煙測試（需先 `pnpm dev`）：走過所有路由、記一筆交易、隱私模式、⌘K |
| `pnpm screenshots` | 產生 `docs/screenshots/` 的截圖（桌面 1440×900 @2x 與 iPhone 15，淺色／深色） |
| `pnpm design:detect` | Impeccable 偵測器掃描 `src/` |

Playwright 使用環境裡預先安裝的版本（`/opt/node-tools/node_modules/playwright`），不需要 `playwright install`。

## 環境變數

| 變數 | 說明 |
|---|---|
| `VITE_API_BASE_URL` | 後端位址，例如 `https://api.forliosa.app`（會自動加上 `/api/v1`）。不設定則使用 mock。 |

所有請求都帶 `credentials: "include"`（httpOnly session cookie `forliosa_session`），所以前後端要放在同一個主網域下（例如 `app.` 與 `api.`），後端 CORS 要允許前端網域並開啟 `allow_credentials`。

## 部署到 Cloudflare Pages

| 設定 | 值 |
|---|---|
| Framework preset | None（或 Vite） |
| Root directory | `apps/web` |
| Build command | `pnpm install --frozen-lockfile && pnpm build` |
| Build output directory | `dist` |
| 環境變數 | `NODE_VERSION=22`、`VITE_API_BASE_URL=https://api.<你的網域>` |

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
