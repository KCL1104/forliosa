---
version: 1
slug: "src-pages-settings-settingspage-tsx"
primary_target: "src/pages/settings/SettingsPage.tsx"
related_targets: ["src/pages/placeholders/ComingSoonPages.tsx"]
---

# Surface: 設定 `/settings` 與規劃中頁面

`/impeccable shape 設定` 的產出（無人可回答，假設標示〔推論〕）。繼承 shell 視覺世界。

## 設定

- **工作**：調整顯示習慣、管理券商帳戶。表單型（Operate），即時生效，不需要「儲存」按鈕（偏好以 `PATCH /me/preferences` 同步，失敗時 toast 並還原）。
- **分組**：顯示（漲跌顏色：紅漲綠跌／綠漲紅跌，附即時預覽 ▲+1.23% ▼-0.85%；主題：淺色／深色／跟隨系統；數量單位：張＋股／股；數字縮寫 萬／億 開關）→ 隱私（預設開啟隱私模式）→ 計算（成本法：移動平均／FIFO；績效基準）→ 券商帳戶清單（名稱、券商、幣別、手續費折扣「2.8 折」、最低手續費、追蹤模式；編輯在 Dialog／Drawer）→ 關於資料（示範資料說明、資料來源與授權：TradingView、shioaji-data）。
- AI 額度、通知、資料匯出、刪除帳號：顯示「規劃中（M4／M5）」列，不可點。

## 規劃中頁面（自選 M2、AI 助理 M4、報告 M4、群組 M5、匯入 M3）

- 用 onboard 指引：每頁說明「這裡會有什麼、能幫你做什麼、現在可以先做什麼」，提供一個現在就能用的下一步（例如匯入頁 →「先手動輸入目前持股」）。
- 版面：標題＋一句價值說明＋2–3 個具體功能列（每列一行說明，不用 icon 卡片網格）＋示意（用真實格式的靜態示範，例如 AI 回答的樣式，明確標「示範」）＋ 現在可以做的事。
- 不捏造 AI 輸出的投資結論；示意內容使用中性範例並標示「示範，非投資建議」。
- 手機「更多」分頁：列出交易、績效、報告、群組、匯入、設定。
