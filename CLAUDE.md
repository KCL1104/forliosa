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
- **唯一的例外（產品負責人 2026-11-13 決定，知道授權風險）**：存檔開始以前的五年日線用 Yahoo Finance 回補（`PRICE_HISTORY_SOURCE=yahoo`，只在正式環境的 Railway 變數打開）。這批資料只給走勢圖、技術指標、走勢小圖用，帳本的市值與績效不用；被擋（403、轉址）就停，不偽裝瀏覽器、不換位址。狀態：`cd apps/api && uv run python -m forliosa.history_backfill status`；整批刪除：`… history_backfill drop`。
- 初期資料源不付費（不買 E-Shop 等付費資料）；缺的資料老實顯示空狀態。
- 檢查三把 Claude key 是否分屬三個 workspace：`cd apps/api && uv run python -m forliosa.ai.smoke --keys`。
- AI 用 Claude API，預設模型 Haiku 等級；key 放在環境變數 `Claude_API_KEY_1..3`（三個 workspace，對話黏著同一把 key）。
- 在這個雲端沙盒跑 AI smoke test：`cd apps/api && uv run python -m forliosa.ai.smoke`（沙盒禁止 web fetch 工具時程式會自動移除該工具重試）。
- 前端設計流程使用 Impeccable（`.claude/skills/impeccable`）。
