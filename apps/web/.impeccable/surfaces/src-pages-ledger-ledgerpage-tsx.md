---
version: 1
slug: "src-pages-ledger-ledgerpage-tsx"
primary_target: "src/pages/ledger/LedgerPage.tsx"
related_targets: ["src/app/AppShell.tsx"]
---

# 帳本（首頁）與全域外殼

- **範圍與模式**：帳本首頁＋全域外殼（頂部列、右側 AI 面板）；Operate。相關：群組、個股頁、交易與匯入流程。
- **使用者與工作**：台股投資人與家人朋友；打開就知道自己的部位，想知道原因或要記帳時直接問 AI；AI 先寫草稿，使用者簽名確認才入帳。
- **約束**：紅漲綠跌只用在價格；張／股；手機與桌面同等重要；淺色與深色都要；不放市場總覽、不放 AI 今日簡報、不放旁註。
- **未決**：手機版 AI 面板的呈現（全螢幕分頁或底部抽屜）；本週事項在手機上的位置。

## Direction contract

THESIS：帳本就是首頁——一本跨券商、照台股規則算對、像聯絡簿一樣一行一行排好的帳；旁邊坐著一位隨時可問、先寫好草稿等你簽名的 AI。拒絕市場總覽首頁、AI 簡報、深色報價終端與券商帳務表格。

OWN-WORLD：學校聯絡簿。淺色是紙白、深色是夜間筆記本；1px 藍灰格線就是結構，表格不包卡片；藍黑原子筆墨是文字與動作；紫色只屬於 AI（老師的筆，取代紅筆，因為紅代表漲），AI 的話語用文楷手寫感字體；確認入帳是方形「家長簽名」格；紅綠只表示漲跌。

STORY：使用者先看總資產與今日損益，再掃過格線上的每一檔持股；想知道為什麼或想記帳，就點右側本頁的建議問題或直接輸入；AI 交出附稅費的草稿，使用者在簽名格確認後才入帳。

FIRST VIEWPORT：1440×900。頂部列：字標、帳本／群組、搜尋股票 ⌘K、隱私、頭像。左側約 2/3：主數字列（總資產最大、今日、總損益、近 1 月走勢）、本週事項小框、分段「持倉 7・交易 128・股利 12・績效」與自訂、7 列持股、觀察列。右側約 1/3：AI 面板，標題列（新對話、紀錄與任務、展開）、問候、3 個本頁建議問題、「交給 AI」動作列，底部輸入框（附件、語音、送出）是主要動作。

FORM：聯絡簿；第二輪候選清單第 1 名（IMPECCABLE'S PICK），產品負責人選定並修改：右欄改為 Google Finance 式 AI 面板、取消 AI 旁註。seed:634d2915cfbf2a24

FINISH：unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
