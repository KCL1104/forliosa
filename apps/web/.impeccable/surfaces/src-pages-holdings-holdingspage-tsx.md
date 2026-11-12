---
version: 1
slug: "src-pages-holdings-holdingspage-tsx"
primary_target: "src/pages/holdings/HoldingsPage.tsx"
related_targets: []
---

> **已被取代（2026-11-12）**：持股頁併入帳本的「持倉」分段（`src/pages/ledger/HoldingsView.tsx`），世界觀依 `src-pages-ledger-ledgerpage-tsx.md`。本檔只是歷史紀錄。

# Surface: 持股 `/holdings`

`/impeccable shape 持股` 的產出（無人可回答，假設標示〔推論〕）。繼承 shell 的視覺世界（見 home 的 Direction contract），不另立新世界。

- **工作與對象（Operate、密集）**：檢查每檔持股的成本、現價、損益與權重；決定要不要加碼／減碼；找出某帳戶或某市場的部位。桌面為主要使用情境，手機用來快速掃。
- **資料**：`/portfolio/holdings?account_id=`。欄位（spec §5）：代號、名稱、股數（X 張 Y 股）、均價、現價、今日漲跌、市值、未實現損益、報酬率、佔比、AI 訊號（M4 才有：欄位顯示「—」並以表頭提示說明）。合計列：市值、今日損益、未實現損益合計。
- **結構**：頁首（標題＋摘要數字三格）→ 篩選列（帳戶 select、市場 segmented：全部／上市／上櫃／美股，排序）→ 桌面表格（表頭可排序、數字右對齊、代號與名稱左對齊、整列可點 → `/stock/:symbol`，鍵盤 Enter 可進入）→ 手機收合成卡片（名稱＋代號、市值、今日漲跌、未實現損益與報酬率；點開進個股頁）。
- **狀態與範圍**：0 檔（首次使用 → 兩個入口）、篩選後 0 檔（「這個帳戶沒有上櫃持股」＋清除篩選）、40 檔以上（表格不虛擬化，40 列內效能足夠〔推論〕）、超長中文名（「國泰永續高股息」「元大台灣卓越50」→ 截斷＋title）、零股（「0 張 37 股」顯示為「37 股」）、美股（數量以股、價格以 USD）、負值。
- **限制**：張／股依偏好；美股一律以股。萬／億只在手機卡片使用。隱私模式遮蔽金額與股數，但報酬率與佔比保留（百分比不洩漏金額）〔推論，記入 OPEN_QUESTIONS〕。
