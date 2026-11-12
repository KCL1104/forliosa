# Claude Platform 能否支撐 Forliosa 的 AI 功能

> 查證日期：2026-11-12。來源：Claude 官方文件 [Tool use overview](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)、[Pricing](https://platform.claude.com/docs/en/about-claude/pricing)、[Web search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)。價格會變動，上線前請再確認。

## 結論

所有規劃中的 AI 功能都能用 Claude API 做到。分工是：**Claude 負責理解、推理、找資料、寫草稿與報告；我們的後端負責市場資料、帳本、權限、排程與推播。** 不需要 Managed Agents 也能完成，用 Messages API ＋ 我們自己定義的工具（client tools）＋ 幾個 Anthropic 代管的工具（server tools）即可。

## 會用到的 Claude Platform 功能

| 功能 | 是什麼 | 費用（2026-11-12） |
|---|---|---|
| 自訂工具（client tools）＋ Tool Runner | Claude 決定呼叫我們定義的函式（查持股、查個股、試算稅費…），由我們的後端執行 | 只算 token |
| 嚴格工具與結構化輸出（`strict: true`、`output_config.format`） | 保證工具參數、報告 JSON 一定符合格式 | 只算 token |
| 網頁搜尋（web search） | Anthropic 代為搜尋，回答附來源引用；可限定網域、設定地區為台灣 | 每 1,000 次 US$10 ＋ token |
| 網頁擷取（web fetch） | 讀取指定網址的全文或 PDF（例如公司法說會簡報、公開資訊觀測站文件） | 只算 token |
| 程式執行（code execution） | 在沙盒跑 Python（例如解析 Excel 對帳單、計算） | 和搜尋／擷取一起用時免費；單獨用每月 1,550 小時免費，超過每小時 US$0.05 |
| PDF 與圖片輸入、Files API | 直接讀對帳單 PDF、截圖 | 只算 token |
| Prompt caching | 系統提示、工具定義、公司背景資料重複使用時大幅降價 | 快取讀取約為一般輸入價的 5% |
| Message Batches | 不急的工作（盤後報告、週報）非同步批次處理 | token 打 5 折；批次中也能用網頁搜尋 |
| Compaction、Message threads | 長對話自動摘要、減少重送內容 | 依 token |
| Managed Agents（選用） | Anthropic 代管 agent 迴圈、沙盒、排程部署、多 agent 工作流 | token ＋ 每 session 小時 US$0.08；不適用批次折扣 |

模型價格（每百萬 token，輸入／輸出）：高階（Opus）US$4／US$20、中階（Sonnet）US$2／US$10、輕量（Haiku）US$0.10／US$0.50（提示超過 10 萬 token 時價格提高）。模型選擇由產品負責人決定，預設用高階模型。

## 功能對照

| Forliosa 功能 | 怎麼用 Claude 做 | 我們要自己做的 |
|---|---|---|
| AI 對話（問持股、個股） | Messages API ＋ 我們的工具（`get_holdings`、`get_stock_overview`、`get_chips`、`get_financials`、`get_events`…），串流回覆 | 工具背後的資料（政府開放資料、帳本）、權限檢查 |
| 依頁面自動出現的建議問題 | 輕量模型或規則產生；可快取 | 頁面狀態、規則 |
| 一句話記帳（「買 0050 2 張 52.4」） | 嚴格工具 `draft_transaction` 產生結構化草稿 | `/transactions/preview` 試算、簽名確認後才寫入帳本 |
| 匯入對帳單（PDF、截圖、Excel） | PDF／圖片輸入 ＋ 結構化輸出逐筆抽取；Excel 用程式執行解析 | 預覽、去重、對帳、使用者確認 |
| 「為什麼漲跌」一行 | 異常時才呼叫；網頁搜尋找新聞並附引用；同一檔同一天所有使用者共用 | 異常判斷規則、快取 |
| 新聞 | **網頁搜尋可以補上新聞缺口**：AI 摘要附原始來源連結（官方要求顯示引用）；可用 `allowed_domains` 限定來源 | 顯示引用；法務確認摘要方式 |
| 持倉健檢 | 我們的工具 ＋ 結構化報告；定期健檢用 Batches | 指標計算、排程 |
| 盤後報告、群組週報 | Message Batches（5 折） | 排程（worker）、推播到 Telegram／Discord |
| 個股深度報告（多代理人） | 我們自己編排：多個分析角色平行呼叫 ＋ 總結；或改用 Managed Agents 多 agent 工作流 | 每檔每天共用一份、額度控制 |
| AI 任務（例：每週五健檢、定期定額提醒） | 任務內容由 Claude 產生 | 排程、紀錄頁 |
| 對話紀錄、長對話 | Compaction 或 Message threads | 存在我們的資料庫 |

## Claude 做不到、必須由我們負責的

- **市場資料本身**：報價、歷史、籌碼、財報都要來自我們的資料層（只用可商用來源）。網頁搜尋不是可靠的結構化行情來源，也不能拿來取代授權資料。
- **即時行情**、**推播**、**排程**（除非改用 Managed Agents 的排程部署）、**帳本寫入與權限**。
- **投顧法規**：AI 回答只做分析、不保證結果；公開收費前要法律諮詢。

## 費用粗估（家人朋友階段，僅供參考）

假設高階模型、提示快取命中良好：

| 項目 | 單次估計 | 每人每月（22 個交易日） |
|---|---|---|
| 一般提問（約 1 萬 token 輸入、800 輸出，含一次搜尋） | 約 US$0.03–0.04 | 每天 5 題 → 約 US$3.5–4.5 |
| 盤後報告（批次，約 2 萬輸入、1,500 輸出） | 約 US$0.06 | 約 US$1.3 |
| 個股深度報告（約 15 萬輸入、1.5 萬輸出，含 10 次搜尋） | 約 US$1.0（批次約 US$0.55） | 每月 4 份 → 約 US$2–4 |

合計約每人每月 US$7–10（高階模型）；改用中階模型約減半。實際數字要等功能上線後用真實用量量測。

## 建議架構

1. 後端加一層 `ai/`：Anthropic Python SDK、Tool Runner、我們的工具清單、提示快取、每人額度與用量紀錄。
2. 即時互動（對話、記帳、為什麼漲跌）用 Messages API 串流；不急的工作（盤後報告、週報、定期健檢）用 Message Batches。
3. 新聞與「為什麼漲跌」用網頁搜尋，限定可信來源網域，畫面上一定顯示引用連結。
4. 先不用 Managed Agents；等個股深度報告需要更長時間、多 agent 協作時再評估。
