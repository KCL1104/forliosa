---
version: 1
slug: "src-pages-performance-performancepage-tsx"
primary_target: "src/pages/performance/PerformancePage.tsx"
related_targets: []
---

# Surface: 績效 `/performance`

`/impeccable shape 績效` 的產出（無人可回答，假設標示〔推論〕）。繼承 shell 視覺世界。

- **工作**：了解自己的投資能力（TWR）與實際賺多少（XIRR），跟大盤／0050 比較；看回撤與波動；看每月股利與每年已實現。
- **結構**：頁首＋區間章鈕（1M/3M/6M/YTD/1Y/全部）＋帳戶篩選＋基準選擇（0050、加權報酬指數〔API 待確認〕、自訂）→ 指標列（TWR、XIRR、最大回撤、年化波動度，各附一句白話說明 tooltip）→ 基準比較圖（twr_index vs benchmark_index，換算成 %）＋「超額報酬」數字 → 市值與投入本金面積圖 → 兩欄：每月股利長條、每年已實現損益長條 → 底部「計算方式」摺疊說明（TWR、XIRR 定義，對應 api-contract 的定義）。
- **狀態**：資料不足（少於 2 個交易日）→ 說明「至少需要兩個交易日的資料」；XIRR 為 null → 「—」＋說明；負報酬正常顯示。
- **限制**：所有比率用 % 一位或兩位小數；漲跌色只用在報酬數字，圖表的系列色用中性的「印泥藍（我的）＋石灰（基準）」，避免紅綠與漲跌混淆。
