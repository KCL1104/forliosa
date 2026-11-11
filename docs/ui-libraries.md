# 前端 UI 函式庫紀錄

依 [產品規格 §6「UI 函式庫分工」](product-spec.md) 與 Emil Kowalski 的 `pick-ui-library` skill 選擇：每種需求只用一個函式庫。這份文件記錄實際用了什麼、為什麼、在哪裡，以及看過但沒採用的參考。

> 參考網站的瀏覽狀況（2026-11-11）：ui.shadcn.com、base-ui.com、magicui.design、ui.aceternity.com、21st.dev、rareui.in、beautifului.dev、number-flow.barvian.me 在開發環境都被網路政策擋下（HTTP 403）。可以連到 npm registry 與 raw.githubusercontent.com，因此 shadcn/ui 的 Base UI 元件原始碼是直接從 GitHub（`shadcn-ui/ui` 的 `apps/v4/registry/bases/base/ui/*` 與 `styles/style-nova.css`）取得，並用和 shadcn CLI 相同的方式把 `cn-*` 樣式類別展開。

## 採用

| 需求 | 函式庫（版本） | 用在哪裡 | 理由與注意事項 |
|---|---|---|---|
| 元件骨架 | shadcn/ui（style `base-nova`，見 `apps/web/components.json`） | `src/components/ui/*`：button、dialog、alert-dialog、tabs、select、switch、tooltip、popover、dropdown-menu、input、kbd、skeleton… | 元件複製進專案、可改。依設計系統改寫：移除 nova 預設的玻璃模糊（`backdrop-blur`）、半透明選單，overlay 改成墨色遮罩 `--scrim`，按鈕與輸入框加大觸控尺寸（44px）、16px 輸入字級 |
| 無樣式基礎元件 | Base UI `@base-ui/react` 1.9 | 上述 shadcn 元件的 primitives | pick-ui-library 首選；處理焦點、鍵盤、ARIA |
| Base UI 沒有的元件 | Radix | **沒有用到** | 這次需要的元件 Base UI 都有 |
| 通知 | Sonner 2.0 | `components/ui/sonner.tsx`；記一筆、更新、刪除（含「復原」）、設定同步失敗 | 依 ask-sonner：一個 Toaster、位置 top-center 並加 safe-area offset；主題跟本專案的 zustand 偏好（不依賴 next-themes）；「已入帳」章在 toast 裡「蓋下」 |
| 手機底部抽屜 | Vaul 1.1.2（shadcn Radix 版 Drawer） | 手機的記一筆／編輯交易表單、交易篩選 | ⚠️ Vaul 已標示不再維護（2024-12）。**發現**：Base UI 1.x 已內建 `Drawer`，shadcn 的 base 版 drawer 就是用它；之後可評估替換（見 OPEN_QUESTIONS） |
| ⌘K 搜尋 | cmdk 1.1 | `app/CommandSearch.tsx`（全域搜尋＋跳頁＋常用動作）、交易表單的代號選擇 | 使用 `shouldFilter={false}`，由 API 依代號或中文名稱搜尋；依 emil-design-eng，每天用上百次的面板不做開關動畫 |
| 數字動畫 | NumberFlow `@number-flow/react` 0.6 | 總資產、今日損益、總損益、個股現價 | 自行處理 U+2212 負號與 NT$／US$ 前綴（Intl 的 TWD 會顯示 `$`）；隱私模式時改成固定寬度遮罩 |
| 一般動畫 | motion | **沒有用到（已移除依賴）** | 規格寫「簡單淡入淡出用 CSS 即可」：按下回饋、蓋章、對話框都用 CSS／tw-animate-css 就夠 |
| 一般圖表 | recharts 3.10 | 報酬走勢、配置圓環、河流圖、殖利率、月營收、績效各圖 | 不用雙 Y 軸（dataviz）；分類色已用 dataviz `validate_palette.js` 驗證淺色與深色 |
| K 線圖 | lightweight-charts 5.3 | `pages/stock/tabs/KlineTab.tsx` | 保留 `attributionLogo: true`（TradingView 標誌）並附文字說明，符合 Apache-2.0 與 TradingView 的標示要求；顏色在執行時從 CSS token 轉成 rgba |
| 長清單 | react-virtuoso 4.18 | 交易紀錄（`GroupedVirtuoso`、月份分組、捲到底載入下一頁） | pick-ui-library 的虛擬化首選 |
| 狀態 | zustand 5 | 顯示偏好（漲跌慣例、主題、張／股、萬億縮寫、隱私預設、成本法、基準；存 localStorage）、自選、UI 暫存狀態 | 伺服器資料用 TanStack Query |
| 伺服器資料 | TanStack Query 5、TanStack Router 1 | 全部 API 呼叫；路由與 search params（分頁、篩選） | 規格 §7 |
| className | clsx、class-variance-authority、tailwind-merge | `cn()`、`Chop` 等元件變體 | shadcn 內建 |
| 動畫工具 | tw-animate-css | shadcn 元件的 data-open／closed 動畫 | shadcn v4 預設 |
| 圖示 | lucide-react | 全站 | shadcn 預設圖示庫；一致的 1.5–2px 線條 |
| 字型 | `@fontsource-variable/source-sans-3`、`@fontsource-variable/noto-sans-tc` | 全站 | Source Sans 3（拉丁與等寬數字）＋ Noto Sans TC（思源黑體）同一設計血統；自架、依 unicode-range 分片載入 |
| 主題切換 | 自寫（`hooks/use-theme.ts`＋ `index.html` 內聯腳本） | 淺色／深色／跟隨系統 | pick-ui-library 建議 next-themes，但它是為 SSR 設計；Vite SPA 用一段內聯腳本即可避免閃爍，少一個依賴 |

## 參考但沒有採用的展示性元件

規格允許 Magic UI、Aceternity UI、RareUI、Beautiful UI、21st.dev 的元件只用在展示性畫面（登入／歡迎、首次使用、空狀態、群組排行），而且要確認授權並通過 Impeccable critique。這一輪的結論是**都不用**：

| 來源 | 授權（就我所知） | 考慮過的元件 | 決定 |
|---|---|---|---|
| Magic UI | MIT（GitHub `magicuidesign/magicui`） | Number Ticker、Border Beam、Animated List | Number Ticker 與 NumberFlow 重複（同一需求只用一個函式庫）；Border Beam 是發光邊框裝飾，違反 DESIGN.md「不用發光、漸層」；Animated List 留給 M5 群組動態再評估 |
| Aceternity UI | 免費元件有自己的授權條款，部分為付費 | Background Beams、Spotlight | 純裝飾背景效果，會干擾數字閱讀，與「印鑑」世界觀無關 |
| RareUI、Beautiful UI、21st.dev | 依各元件作者而定，網站被擋無法逐一確認 | — | 無法確認授權，不採用 |

首次使用與空狀態目前用設計系統本身的 Panel、章與按鈕完成（通過 critique、偵測器 0 項）。M5 的群組排行榜慶祝畫面是最適合引入展示性元件的地方，屆時再評估授權與 critique。

## 開發工具

Vite 8、TypeScript 6.0（typescript-eslint 尚未支援 7.x）、ESLint 10、Vitest 5、Testing Library、jsdom；Playwright 使用環境預裝版本。
