# Forliosa

以台股為主的投資管理 web app：持倉帳本與績效、個股資訊（報價、估值河流圖、財務、股利）、AI 分析，以及親友群組分享。

## 文件

- [產品需求規格](docs/product-spec.md)
- [API 介面合約](docs/api-contract.md)
- [部署指南（Cloudflare Pages＋Railway）](docs/deploy.md)
- [研究報告：台股 AI 開源投資管理平台](reports/台股%20AI%20開源投資管理平台.md)

## 專案結構

```
apps/
  api/    Python FastAPI 後端（帳本、稅費、績效、行情、背景工作）
  web/    Vite + React 前端（Cloudflare Pages）
docs/     規格與設計文件
.claude/skills/  前端設計用的 skills（Impeccable、Emil Kowalski 的 UI skills）
```

## 開發

需要 Python 3.13＋[uv](https://docs.astral.sh/uv/)、Node 22（≥ 22.12）＋pnpm 10。在本機同時跑後端與前端：

```bash
# 終端機 1：後端（SQLite，開發模式），http://localhost:8000
cd apps/api
uv sync
uv run python -m forliosa.seed          # 建立資料表與示範使用者 demo@forliosa.local（兩年交易，真實台股收盤價）
uv run uvicorn forliosa.main:app --port 8000

# 終端機 2：前端連後端，http://localhost:5173
pnpm install
pnpm dev:web:api                        # Vite 把 /api 轉給 localhost:8000（同源 cookie），自動以示範使用者開發登入
```

只想看畫面、不跑後端：`pnpm dev:web`（瀏覽器內的 mock 示範資料）。測試：`apps/api` 裡 `uv run pytest`、`uv run ruff check .`；
前端 `pnpm --filter @forliosa/web typecheck`、`lint`、`test`、`build`。CI 見 `.github/workflows/ci.yml`。
細節見 `apps/api/README.md` 與 `apps/web/README.md`。

## 授權聲明

`.claude/skills/impeccable` 來自 [pbakaus/impeccable](https://github.com/pbakaus/impeccable)（Apache-2.0）；
`.claude/skills/` 下其餘的 UI skills 來自 [emilkowalski/skills](https://github.com/emilkowalski/skills)（MIT）。
