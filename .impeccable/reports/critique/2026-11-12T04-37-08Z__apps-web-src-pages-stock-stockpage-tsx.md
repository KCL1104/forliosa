---
target_identity: "file:/home/user/forliosa/apps/web/src/pages/stock/StockPage.tsx"
target_fingerprint: "sha256:959d1e69e43a06d91792952bf0427863eba5becf553f5c0af14c51f09164afcf"
target_path: /home/user/forliosa/apps/web/src/pages/stock/StockPage.tsx
timestamp: 2026-11-12T04-37-08Z
slug: apps-web-src-pages-stock-stockpage-tsx
---
> 單一上下文降級模式（同帳本報告）。目標：個股頁 /stock/:symbol（報價、為什麼、我的部位、走勢圖、六個分頁）。證據：docs/screenshots/v2/stock-2330-*。

## Design Health Score

| # | Heuristic | Score | Key finding |
|---|---|---|---|
| 1 | Visibility of system status | 4 | 收盤／盤中・延遲、參考價、漲跌停、示範資料、籌碼資料日期 |
| 2 | Match between system and real world | 4 | 漲跌以參考價計、升降單位小數位、張為單位、注意／處置章 |
| 3 | User control and freedom | 3 | 分頁寫進網址；區間預設依是否持有（6 月／1 月），可改 |
| 4 | Consistency and standards | 3 | 鍵值格、格線區塊、區間選擇與帳本同一套 |
| 5 | Error prevention | 3 | 1 日線沒有點時說明原因並給「加入觀察」 |
| 6 | Recognition rather than recall | 3 | 「為什麼」只在異常時出現；每個分頁第一行一句話 |
| 7 | Flexibility and efficiency | 3 | 類型、比較、指標、重要時刻；分頁方向鍵切換 |
| 8 | Aesthetic and minimalist design | 3 | 總覽內容多但以格線分層；沒有卡片堆疊 |
| 9 | Error recovery | 3 | 找不到代號、資料錯誤都有說明與重試 |
| 10 | Help and documentation | 3 | 河流圖說明、資料來源、只列新聞標題 |
| **Total** | | **32/40** | **Good** |

## Priority Issues（已處理）
- **[P1] 均價線在縱軸範圍外看不到**：→ 持有時把均價納入自動縮放（`autoscaleInfoProvider`）。
- **[P1] 重要時刻標記同時畫方塊和 ◆**：→ 只留 ◆ 文字標記。
- **[P1] 手機部位兩欄擠壓重疊**：→ 改成換行排列，今日與已領股利移到展開區。
- **[P1] 法人買賣超與營收年增用紅綠**：違反「紅綠只表示價格」→ 改成墨色＋正負號；圖表買超墨色、賣超鉛筆灰。
- **[P2] 價格小數位不一致**（932.00、236.50）：→ 依升降單位顯示（932、236.5、22.40）。

## Minor Observations（未處理）
- ETF 折溢價、成分股、美股財報與籌碼是設計過的空狀態，等資料來源。
- 比較線（加權報酬指數）在 mock 以 0050 走勢代替。

Questions skipped: unattended subagent run, no user available.
