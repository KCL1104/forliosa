---
target: 個股頁法人觀點卡
total_score: 31
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 4
target_identity: "file:/home/user/forliosa/apps/web/src/pages/stock/AnalystViews.tsx"
target_fingerprint: "sha256:ec7364edf298e59caf6a95c46ca38291cef7346a8428363435f87c763c9f8a49"
target_path: /home/user/forliosa/apps/web/src/pages/stock/AnalystViews.tsx
timestamp: 2026-11-12T07-59-24Z
slug: apps-web-src-pages-stock-analystviews-tsx
---
⚠️ DEGRADED: single-context (subagent run; no sub-agent/Task tool exposed. Assessment A finished and recorded before detector output was read; then Assessment B.)

# Quick critique：個股頁「法人觀點」收合區塊（apps/web/src/pages/stock/AnalystViews.tsx）

Scope: 2330 ready（3 筆）、2454 none → searching → ready、2881 empty、2409 unavailable；桌面 1440 與 iPhone 15，淺色／深色。Mock 模式（commercial）。

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | 搜尋中有 AI 的話＋一行「搜尋網路：…」，查詢時間有寫；長時間搜尋沒有經過時間 |
| 2 | Match System / Real World | 4 | 機構・評等原文・目標價・日期・原文連結，像剪報；評等照抄不翻譯 |
| 3 | User Control and Freedom | 3 | 預設收合、可隨時收起；搜尋中不能取消（全體共用，取消意義不大） |
| 4 | Consistency and Standards | 4 | 和「已出清」同一種收合格線區塊、Section 標題；紫色只給 AI 的話與查詢圖示 |
| 5 | Error Prevention | 3 | 額度剩 5 題內提示「查詢算一題」、AI 暫停或額度用完時按鈕停用 |
| 6 | Recognition Rather Than Recall | 3 | 手機沒有表頭，靠「目標價」前綴；評等與日期在第二行 |
| 7 | Flexibility and Efficiency | 2 | 沒有「問 AI 外資怎麼看」的接續；過期後要重新展開 |
| 8 | Aesthetic and Minimalist Design | 3 | 免責＋說明兩行淡墨在 none 狀態略重 |
| 9 | Error Recovery | 3 | GET／POST 失敗可重試；逾時說明；unavailable 只有「稍後再打開」 |
| 10 | Help and Documentation | 3 | 資料來源與授權頁說明這不是授權資料庫 |
| **Total** | | **31/40** | **Good** |

## Design Specificity Verdict

LLM assessment: 屬於這個世界——沒有卡片外框，是格線上的一張剪報清單；評等是墨色文字（不上紅綠、不排名、沒有平均或上漲空間），AI 只在「正在找…」那句文楷與查詢按鈕的紫色圖示出現。和 Yahoo／券商 app 常見的「目標價區間條＋多空家數＋紅綠燈」刻意相反。

Deterministic scan: 原始碼 0 項；即時頁面（CDP，展開後的 ready／none／searching／empty、1440 與 390）修正前 1 項 `pulsing-dot`（搜尋中的紫點脈動），修正後 0 項。

## What's Working
- 免責文字放在清單「上方」（後端文字以「以下為…」開頭），四種狀態都看得到。
- 多空並陳、只依日期排序；評等原文加「」，動作照抄（調升／維持／調降／首評）。
- 收合時只有一行標題＋「第三方意見」，不打 API；展開才 GET，none 才讓使用者決定要不要搜尋。

## Priority Issues
- **[P1｜已修正] 螢幕閱讀器會把整張表念出來**：原本 aria-live 包住整個內容。改成一句 sr-only 狀態（「找到 3 筆法人觀點」「近期查無法人報導」…）。
- **[P1｜已修正] 搜尋中的脈動紫點**（detector `pulsing-dot`）：改成靜止紫點＋寫明「搜尋網路：聯發科 法人評等與目標價…」。AI 面板的串流點依 DESIGN.md 保留，沒有動。
- **[P1｜已修正] 桌面欄寬**：機構、評等欄留白過多，來源標題被截斷；改為 18%／19%，來源連結在觸控裝置 44px 高。
- **[P1｜已修正] mock 來源標題中英之間少空格**（「外資券商 A給…」）。
- **[P2｜未改] empty／unavailable 沒有「現在能做的動作」**（DESIGN.md Do）：可加「看公告」或「問 AI」。待產品負責人決定。
- **[P2｜未改] 很久的搜尋只有靜態文字**：90 秒逾時會說明；若後端常超過 20 秒，可考慮顯示經過秒數。

## Persona Red Flags
- **年長家人**：手機三行列字級 17px／15px，OK；「目標價」前綴避免看不懂右邊的數字。
- **想要結論的人**：會找「平均目標價」「看多幾家」——刻意不提供（產品負責人規則），免責文字說明了原因。

## Minor Observations
- 「第三方意見」與免責文字意思重疊，但收合時只有前者看得到，保留。
- 跨年的報導日期寫成「2025/12/30」，同年寫「11/10」。

## Questions to Consider
- empty 狀態要不要給一個接續動作（看公告、問 AI）？
- 90 天以前的報導要不要標「舊資料」（研究稿建議；目前交給後端篩選）？
