---
target_identity: "file:/home/user/forliosa/apps/web/src/pages/ledger/LedgerPage.tsx"
target_fingerprint: "sha256:705cf7baee55d565e5b196086663be342b5409a4444dec1981b3638f499715a2"
target_path: /home/user/forliosa/apps/web/src/pages/ledger/LedgerPage.tsx
timestamp: 2026-11-12T04-37-08Z
slug: apps-web-src-pages-ledger-ledgerpage-tsx
---
> 單一上下文降級模式：本次重建由前端子代理執行，沒有可派出的子代理，Assessment A（設計評審）與 B（detect＋瀏覽器證據）在同一個上下文完成。
> 目標：帳本（首頁）＋全域外殼＋AI 面板／草稿流程。證據：docs/screenshots/v2/ledger-*、ledger-draft-*、ai-iphone-*，.impeccable/review/desktop.png、mobile.png；對照 r4 決策稿（.impeccable/mocks/decision/r4-*）。

## Design Health Score

| # | Heuristic | Score | Key finding |
|---|---|---|---|
| 1 | Visibility of system status | 4 | 資料時間（11/12 13:30 收盤）、示範資料標記、待簽名 N 筆、骨架與 toast 都在 |
| 2 | Match between system and real world | 4 | 張／股、紅漲綠跌＋▲▼、萬／億、台股升降單位小數位、聯絡簿的「簽名」 |
| 3 | User control and freedom | 3 | 草稿可修改、捨棄，入帳後可復原；（已修）重新打開時面板改從問候開始 |
| 4 | Consistency and standards | 3 | 同一套分段與格線；手機「問 AI」的膠囊按鈕和桌面方肩按鈕是兩種形狀（依決策稿） |
| 5 | Error prevention | 4 | 先草稿後生效；賣超持股、沒寫價格或單位時草稿上直接說明 |
| 6 | Recognition rather than recall | 3 | 建議問題依資料自動出現；指令語法寫在輸入框提示 |
| 7 | Flexibility and efficiency | 3 | ⌘K、⌘J、一句話記帳、自訂欄位與釘選 |
| 8 | Aesthetic and minimalist design | 4 | 格線就是結構，沒有卡片包表格；紫色只在 AI |
| 9 | Error recovery | 3 | 錯誤寫原因與重試；入帳失敗留在草稿上 |
| 10 | Help and documentation | 3 | 「怎麼算的 ⌄」、免責一行、空狀態說下一步 |
| **Total** | | **34/40** | **Good** |

## Design Specificity Verdict

**LLM assessment**：作者感明確。聯絡簿的四個貢獻都在而且各司其職：字型（Noto Sans TC＋文楷只給 AI）、色盤（紙白／夜間筆記本、藍黑墨、紫只屬於 AI、紅綠只給價格）、密度（Google Finance 的留白主數字＋1px 格線表格）、招牌動作（方形「簽名｜確認入帳」，簽名後留下使用者的字由左往右寫出）。導覽與控制項都是標準元件，不是聯絡簿的戲服。
**Deterministic scan**：`impeccable detect` 在 11 個桌面網址與 8 個手機網址（390×844）上 0 項；原始碼掃描只有「字級不在 DESIGN.md」的建議（舊 DESIGN.md 描述被替換的世界，重寫後消失），已把任意字級收斂到字級表。

## Priority Issues（已處理）
- **[P1] 每次打開都停在上一段對話**：面板持久化了 threadId，回來的人看不到問候與建議。→ 修正：重新載入時回到問候，只有含待簽名草稿的對話會直接打開（`src/ai/store.ts`）。
- **[P1] 手機觸控目標**：區間按鈕 40px、分段 38px。→ 粗指標時 44px，分段加上下延伸的點擊區（`components/segmented.tsx`、`PriceChart.tsx`）。
- **[P1] 漲跌百分比同時有 ▲ 和 +**：和決策稿與台灣慣例不同。→ 有符號時不加正負號（`components/finance.tsx`）。
- **[P2] 平板的浮動分頁拉滿整寬**：→ 最大寬 520px 置中。
- **[P2] 字級層級太平**（股利頁 h2 17px 與年份 15px）：→ 區塊標題 20px。

## Persona Red Flags
- **Alex（重度使用者）**：⌘K 搜尋、⌘J 叫 AI、Enter 送出；表格可排序、可自訂欄位。沒有發現阻礙。
- **Jordan（第一次用）**：空帳本直接給「試試『買 0050 2 張 52.4』」與表單兩條路；草稿上寫清楚沒填的欄位怎麼補。
- **長輩**：主數字 64／40px、列高 60／72px、觸控 ≥ 44px；隱私模式一鍵。

## Minor Observations（未處理）
- 建議卡外框用格線色（1.31:1），靠文字與紫色圖示辨識；依決策稿保留。
- 名字超過 3 個字時問候省略名字（避免一行塞不下）。

Questions skipped: unattended subagent run, no user available; decisions recorded in apps/web/PROGRESS.md.
