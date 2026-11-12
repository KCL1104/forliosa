---
version: 1
slug: "src-pages-transactions-transactionspage-tsx"
primary_target: "src/pages/transactions/TransactionsPage.tsx"
related_targets: []
---

> **已被取代（2026-11-12）**：交易紀錄併入帳本的「交易」分段（`src/pages/ledger/TransactionsView.tsx`）；記帳的主要入口改為 AI 草稿＋簽名，表單是備援。本檔只是歷史紀錄。

# Surface: 交易 `/transactions`

`/impeccable shape 交易` 的產出（無人可回答，假設標示〔推論〕）。繼承 shell 視覺世界。

- **工作**：逐筆記帳（買進、賣出、現金股利、配股、分割、減資、存入、提出、手續費、稅、利息），檢查過去的紀錄、修正錯誤。記帳時最在意「手續費和稅算得對不對」。
- **清單**：react-virtuoso 虛擬化（數百到數千筆），由新到舊、依日期分組（日期標頭黏住）；每列：日期、類型章（買進／賣出…）、名稱＋代號、張股、價格、金額、手續費＋稅、帳戶。分頁用 `next_cursor`，捲到底自動載入。
- **篩選**：帳戶、類型、代號、日期區間（本月／今年／全部）。桌面在清單上方一列；手機收進「篩選」底部抽屜（Vaul）。
- **新增／編輯**：桌面 Dialog、手機 Vaul Drawer；欄位：帳戶、類型（segmented）、代號（cmdk 搜尋 combobox）、日期、數量（張／股切換輸入，即時顯示換算）、價格、當沖勾選、備註；右側（手機在下方）**即時稅費預估**（`POST /transactions/preview`，300ms debounce）：成交金額、手續費（含規則說明「0.1425% × 2.8 折」）、證交稅、二代健保、淨收付。可展開手動覆寫手續費與稅。儲存 → Sonner「已記錄：買進 台積電 1 張」（附「復原」= 刪除）＋新列蓋章動畫。
- **狀態**：沒有交易（首次使用：「先記第一筆交易」或「只輸入目前持股」）；篩選無結果；預估失敗（欄位不完整時顯示「填完數量與價格後會自動試算」）；儲存失敗（toast 錯誤＋保留表單內容）。
- **限制**：數量輸入 inputmode=decimal、16px 字；金額等寬；刪除需確認（AlertDialog）。
