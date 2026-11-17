# Forliosa 專案說明（給 Claude）

## 溝通
- **回覆產品負責人一律使用繁體中文**（技術名詞、程式碼、指令可保留英文）。
- 需要產品負責人決定的事，附上建議選項。

## 專案位置
- 產品真相：`PRODUCT.md`；視覺系統：`DESIGN.md`；需求規格：`docs/product-spec.md`。
- API 合約：`docs/api-contract.md`，後端實作差異：`apps/api/CONTRACT_NOTES.md`。
- 研究：`docs/research/`（資料授權、Claude Platform、個股頁、重新設計）。
- 後端 `apps/api`（FastAPI，`uv`）；前端 `apps/web`（Vite＋React，`pnpm`）。

## 重要決定
- 資料只用可合法商用的來源：`DATA_POLICY=commercial`（預設）；不得自動擷取證交所網站或 MIS。
- **例外：證交所在政府資料開放平臺登記的下載網址（產品負責人 2026-11-16 決定）**：`https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=open_data`（個股日成交資訊，data.gov.tw 11549）與 `https://www.twse.com.tw/exchangeReport/MI_INDEX?response=open_data`（每日收盤行情－大盤統計，11555）可以用程式下載，讓上市收盤價在當天下午就進來（OpenAPI 要到隔天清晨）。依據：政府資料開放授權條款，以及證交所 2025-09-17 在平臺上回覆「本資料集可以使用自動程式進行下載」。只抓這兩個完整網址、不帶日期參數，交易日 13:45 起最多每 10 分鐘一次，拿到當天的就停；被擋（轉址、403、429）就停，不偽裝瀏覽器、不換位址。證交所其他網頁與 MIS 一律不抓；證交所表示不同意就關掉。櫃買中心網站的下載網址不在這個例外裡。
- **另一個例外：Yahoo Finance 歷史日線（產品負責人 2026-11-13 決定，知道授權風險）**：存檔開始以前的五年日線用 Yahoo Finance 回補（`PRICE_HISTORY_SOURCE=yahoo`，只在正式環境的 Railway 變數打開）。這批資料只給走勢圖、技術指標、走勢小圖用，帳本的市值與績效不用；（2026-11-17 負責人擴大）也可以當「記一筆」選舊日期時的收盤參考價，以及匯入對帳單核對價格；只當參考、標明非官方，記下的價格以使用者輸入或對帳單為準。被擋（403、轉址）就停，不偽裝瀏覽器、不換位址。狀態：`cd apps/api && uv run python -m forliosa.history_backfill status`；整批刪除：`… history_backfill drop`。
- **另一個例外：LangSearch 新聞搜尋（產品負責人 2026-11-17 決定，知道條款風險）**：條款沒寫清楚能不能保存結果、經營者不明，負責人仍決定採用，並可以把搜到的新聞標題、媒體、時間、網址存進新聞表（和其他來源一樣 30 天後刪除），不存內文。金鑰：沙盒用 api.langsearch.com 的 proxy 憑證；正式環境用 Railway worker 的環境變數。在免費的每日額度內使用；被擋（429、403、轉址）就停到隔天，不換帳號、不偽裝。服務停擺時其他新聞來源照常。
- 初期資料源不付費（不買 E-Shop 等付費資料）；缺的資料老實顯示空狀態。
- **美股收盤價（產品負責人 2026-11-15 決定，沒有先寫信問 Databento，知道授權風險）**：用 Databento 歷史 API 的 `EQUS.SUMMARY`（官方合併收盤、日線、未還原權息，從 2024-07-01 起）；`US_PRICE_SOURCE=databento`＋`DATABENTO_API_KEY`（Basic auth：金鑰當使用者名稱、密碼空白）。按量計費，用註冊送的 US$125 額度（6 個月到期）。研究與待確認事項：`docs/research/us-market-data.md`。圖表維持自己的 Lightweight Charts，不改用 TradingView 小工具。
- 檢查三把 Claude key 是否分屬三個 workspace：`cd apps/api && uv run python -m forliosa.ai.smoke --keys`。
- AI 用 Claude API，預設模型 Haiku 等級；key 放在環境變數 `Claude_API_KEY_1..3`（三個 workspace，對話黏著同一把 key）。
- 在這個雲端沙盒跑 AI smoke test：`cd apps/api && uv run python -m forliosa.ai.smoke`（沙盒禁止 web fetch 工具時程式會自動移除該工具重試）。
- 前端設計流程使用 Impeccable（`.claude/skills/impeccable`）。
