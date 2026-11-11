# Forliosa

以台股為主的投資管理 web app：持倉帳本與績效、個股資訊（報價、估值河流圖、財務、股利）、AI 分析，以及親友群組分享。

## 文件

- [產品需求規格](docs/product-spec.md)
- [API 介面合約](docs/api-contract.md)
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

後端與前端各自的啟動方式見 `apps/api/README.md` 與 `apps/web/README.md`。

## 授權聲明

`.claude/skills/impeccable` 來自 [pbakaus/impeccable](https://github.com/pbakaus/impeccable)（Apache-2.0）；
`.claude/skills/` 下其餘的 UI skills 來自 [emilkowalski/skills](https://github.com/emilkowalski/skills)（MIT）。
