# 前端 UI 函式庫紀錄

依 [產品規格 §6「UI 函式庫分工」](product-spec.md) 與 Emil Kowalski 的 `pick-ui-library` skill 選擇：每種需求只用一個函式庫。這份文件記錄實際用了什麼、為什麼、在哪裡，以及看過但沒採用的參考。

> **2026-11-12 重新設計（聯絡簿世界）**：函式庫組合不變，只換視覺世界與資訊架構；新增文楷字型。下表已更新為新世界的用法。

> 參考網站的瀏覽狀況（2026-11-11）：ui.shadcn.com、base-ui.com、magicui.design、ui.aceternity.com、21st.dev、rareui.in、beautifului.dev、number-flow.barvian.me 在開發環境都被網路政策擋下（HTTP 403）。可以連到 npm registry 與 raw.githubusercontent.com，因此 shadcn/ui 的 Base UI 元件原始碼是直接從 GitHub（`shadcn-ui/ui` 的 `apps/v4/registry/bases/base/ui/*` 與 `styles/style-nova.css`）取得，並用和 shadcn CLI 相同的方式把 `cn-*` 樣式類別展開。

## 採用

| 需求 | 函式庫（版本） | 用在哪裡 | 理由與注意事項 |
|---|---|---|---|
| 元件骨架 | shadcn/ui（style `base-nova`，見 `apps/web/components.json`） | `src/components/ui/*`：button、dialog、alert-dialog、tabs、select、switch、tooltip、popover、dropdown-menu、input、kbd、skeleton… | 元件複製進專案、可改。依聯絡簿世界改寫：方肩 4px、主要按鈕墨色底、次要按鈕 1px 鉛筆灰框、新增 `ai` 變體（紫色虛線，只給 AI）；選單與 popover 用格線框＋一種柔和投影；沒有玻璃模糊；觸控 44px、觸控裝置 16px 輸入字級 |
| 無樣式基礎元件 | Base UI `@base-ui/react` 1.9 | 上述 shadcn 元件的 primitives | pick-ui-library 首選；處理焦點、鍵盤、ARIA |
| Base UI 沒有的元件 | Radix | **沒有用到** | 這次需要的元件 Base UI 都有 |
| 通知 | Sonner 2.0 | `components/ui/sonner.tsx`；AI 草稿簽名入帳（含「復原」）、表單記一筆、更新、刪除、設定同步失敗 | 依 ask-sonner：一個 Toaster、位置 top-center 並加 safe-area offset；主題跟本專案的 zustand 偏好（不依賴 next-themes）；「復原」用 action 按鈕（墨色），描述用淡墨 |
| 手機底部抽屜 | Vaul 1.1.2（shadcn Radix 版 Drawer） | 手機的記一筆／編輯交易表單、交易篩選 | ⚠️ Vaul 已標示不再維護（2024-12）。**發現**：Base UI 1.x 已內建 `Drawer`，shadcn 的 base 版 drawer 就是用它；之後可評估替換（見 OPEN_QUESTIONS） |
| ⌘K 搜尋 | cmdk 1.1 | 桌面頂部列「搜尋股票」（`app/CommandSearch.tsx`）、交易表單的代號選擇；手機的搜尋改住在「問 AI」的「搜尋或提問」輸入框 | 使用 `shouldFilter={false}`，由 API 依代號或中文名稱搜尋；依 emil-design-eng，每天用上百次的面板不做開關動畫 |
| 數字動畫 | NumberFlow `@number-flow/react` 0.6 | 帳本總資產、個股現價 | 自行處理 U+2212 負號與 NT$／US$ 前綴（Intl 的 TWD 會顯示 `$`）；隱私模式時改成固定寬度遮罩 |
| 一般動畫 | motion | **沒有用到（已移除依賴）** | 規格寫「簡單淡入淡出用 CSS 即可」：按下回饋、簽名墨水（clip-path）、對話落下、問 AI 全螢幕進出都用 CSS／Base UI 的 starting/ending style |
| 一般圖表 | recharts 3.10 | 績效（報酬走勢、市值、每月股利、已實現）、河流圖、殖利率、月營收與年增、三大法人、融資融券、外資持股、歷年股利 | 不用雙 Y 軸（dataviz）；分類色已用 dataviz `validate_palette.js` 驗證淺色與深色 |
| 走勢圖／K 線 | lightweight-charts 5.3 | `pages/stock/PriceChart.tsx`（1 日分時、線／K、比較（百分比模式）、MA5/20/60、成交量、均價線、買賣與股利標記、◆ 重要時刻） | 圖下方文字標示「圖表由 TradingView Lightweight Charts™ 繪製」（Apache-2.0）；顏色在執行時從 CSS token 轉成 rgba；均價納入自動縮放 |
| 長清單 | react-virtuoso 4.18 | 帳本「交易」分段（`GroupedVirtuoso`、月份分組、捲到底載入下一頁） | pick-ui-library 的虛擬化首選 |
| 狀態 | zustand 5 | 顯示偏好、帳本自訂（欄位、走勢圖、釘選）、AI 面板（開合、對話紀錄、待簽名草稿）、UI 暫存狀態（都存在這台瀏覽器；自選改由 `/watchlist` API） | 伺服器資料用 TanStack Query |
| 伺服器資料 | TanStack Query 5、TanStack Router 1 | 全部 API 呼叫；路由與 search params（分頁、篩選） | 規格 §7 |
| className | clsx、class-variance-authority、tailwind-merge | `cn()`、按鈕變體 | shadcn 內建 |
| 動畫工具 | tw-animate-css | shadcn 元件的 data-open／closed 動畫 | shadcn v4 預設 |
| 圖示 | lucide-react | 全站 | shadcn 預設圖示庫；全站統一 1.6px 線條（和決策稿一致） |
| 字型 | `@fontsource-variable/noto-sans-tc` 5.3；全字庫正楷體（自架子集，`apps/web/scripts/tw-kai/build.py`） | 全站／只給 AI 寫的話 | Noto Sans TC（介面與數字）；全字庫正楷體 TW-Kai（數位發展部，教育部標準字形，擇用 SIL OFL 1.1；只給模型寫出來的話：回答、為什麼、法人觀點、群組週報）。楷體只切漢字與全形標點，數字與拉丁字母落到 Noto Sans TC。兩者都自架、依 unicode-range 分片載入，只下載用到的字；不用 Google Fonts。霞鶩文楷 TC 已移除（「為」等字是舊字形） |
| 主題切換 | 自寫（`hooks/use-theme.ts`＋ `index.html` 內聯腳本） | 淺色／深色／跟隨系統 | pick-ui-library 建議 next-themes，但它是為 SSR 設計；Vite SPA 用一段內聯腳本即可避免閃爍，少一個依賴 |

## 參考但沒有採用的展示性元件

規格允許 Magic UI、Aceternity UI、RareUI、Beautiful UI、21st.dev 的元件只用在展示性畫面（登入／歡迎、首次使用、空狀態、群組排行），而且要確認授權並通過 Impeccable critique。這一輪的結論是**都不用**：

| 來源 | 授權（就我所知） | 考慮過的元件 | 決定 |
|---|---|---|---|
| Magic UI | MIT（GitHub `magicuidesign/magicui`） | Number Ticker、Border Beam、Animated List | Number Ticker 與 NumberFlow 重複（同一需求只用一個函式庫）；Border Beam 是發光邊框裝飾，違反 DESIGN.md「不用發光、漸層」；Animated List 留給 M5 群組動態再評估 |
| Aceternity UI | 免費元件有自己的授權條款，部分為付費 | Background Beams、Spotlight | 純裝飾背景效果，會干擾數字閱讀，與聯絡簿世界無關 |
| RareUI、Beautiful UI、21st.dev | 依各元件作者而定，網站被擋無法逐一確認 | — | 無法確認授權，不採用 |

首次使用與空狀態用設計系統本身的格線區塊與按鈕完成（通過 critique、偵測器 0 項）。M5 的群組排行榜慶祝畫面是最適合引入展示性元件的地方，屆時再評估授權與 critique。

## 開發工具

Vite 8、TypeScript 6.0（typescript-eslint 尚未支援 7.x）、ESLint 10、Vitest 5、Testing Library、jsdom；Playwright 使用環境預裝版本。
