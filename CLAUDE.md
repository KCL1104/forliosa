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
- AI 用 Claude API，預設模型 Haiku 等級；key 放在環境變數 `Claude_API_KEY_1..3`（三個 workspace，對話黏著同一把 key）。
- 在這個雲端沙盒跑 AI smoke test：`cd apps/api && uv run python -m forliosa.ai.smoke`（沙盒禁止 web fetch 工具時程式會自動移除該工具重試）。
- 前端設計流程使用 Impeccable（`.claude/skills/impeccable`）。
