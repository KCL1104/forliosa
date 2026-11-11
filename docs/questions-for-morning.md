# 需要你決定的事項（2026-11-12 早上）

昨晚自主開發期間，遇到以下需要你決定或協助的事項。依重要程度排列；每題附上我的建議，你可以直接回「照建議」。

## A. 需要你操作或授權

### A1. 啟用 Impeccable 的自動設計檢查（hook）

- **狀況**：Impeccable 建議安裝 design hook：每次修改 UI 檔案後、以及每次回合結束時，自動掃描設計問題。這需要在 `.claude/settings.json` 加入 hook 設定，被 Claude Code 的自動模式判定為「修改 Claude 自身設定」而擋下，我沒有繞過。
- **目前替代做法**：前端開發時手動執行 `impeccable detect`，效果相同但要記得跑。
- **建議**：同意加入。你可以回覆「同意加 hook」，或自己把下面內容存成 `.claude/settings.json`：

```json
{
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": "[ ! -f \"${CLAUDE_PROJECT_DIR}/.claude/skills/impeccable/scripts/impeccable\" ] || \"${CLAUDE_PROJECT_DIR}/.claude/skills/impeccable/scripts/impeccable\" hook", "timeout": 5}]}],
    "PostToolUse": [{"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "[ ! -f \"${CLAUDE_PROJECT_DIR}/.claude/skills/impeccable/scripts/impeccable\" ] || \"${CLAUDE_PROJECT_DIR}/.claude/skills/impeccable/scripts/impeccable\" hook", "timeout": 5}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "[ ! -f \"${CLAUDE_PROJECT_DIR}/.claude/skills/impeccable/scripts/impeccable\" ] || \"${CLAUDE_PROJECT_DIR}/.claude/skills/impeccable/scripts/impeccable\" hook", "timeout": 30}]}]
  }
}
```

### A2. 開放開發環境連到台股資料網站

- **狀況**：這個雲端開發環境的網路擋住了 `openapi.twse.com.tw`、`www.twse.com.tw`、`mis.twse.com.tw`、`www.tpex.org.tw`、`api.finmindtrade.com`、`query1.finance.yahoo.com`、`impeccable.style`。所以目前：
  - 證交所、櫃買、FinMind 的資料解析程式只能用測試資料驗證，沒有實際連線測過。
  - 歷史股價、估值、股利是**示範資料**（畫面上有標示）；只有公司資料、最新收盤價、月營收、財報來自 shioaji-data 的真實資料。
- **建議**：允許這幾個網址，我就能用真實資料測試。你回覆後，我會送出環境設定變更，你在畫面上按核准即可。

### A3. 準備帳號（之後部署需要）

網域、Cloudflare 帳號、Railway 帳號、Anthropic API key、Telegram bot（找 BotFather 建立）、Google OAuth 用戶端。不急，M4 之前需要。

### A4. 收集券商對帳單樣本

你和家人朋友各用哪幾家券商？請各提供一份對帳單或交易明細匯出檔（Excel、CSV 或 PDF），身分證字號與帳號請先遮蔽。M3 匯入功能需要。

## B. 產品決定

### B1. Vaul 已停止維護

- Vaul（手機底部抽屜）的作者已標示不再維護，最後版本是 2024-12。目前照你的清單先用。
- **建議**：先用；如果日後遇到 React 新版本相容問題，再換成 Base UI 的 Dialog 搭配 motion 自己做抽屜。

### B2. AI 額度與預算

每月 AI 預算上限大約多少？每人每天對話幾次、每月深度報告幾份？（M4 才需要，可以先給大概數字。）

### B3. Impeccable 遙測

Impeccable 會匿名回報你選了哪個視覺方向（不含程式碼與檔案）。要關掉嗎？**建議**：關掉（金融類產品保守一點）。

### B4. 品牌

App 名稱就用 **Forliosa** 嗎？有沒有偏好的品牌色或 logo 方向？目前由 Impeccable 流程依產品定位決定。

## C. 開發過程中的其他問題

（兩個開發 agent 回報後補上。）
