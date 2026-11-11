# 前端進度（2026-11-11）

## 已完成

| 範圍 | 狀態 | 檔案 |
|---|---|---|
| App 外殼 | ✅ 桌面靛青側欄＋頂部列（⌘K、隱私、主題、記一筆）；手機頂部列＋底部五分頁（safe area） | `src/app/` |
| 總覽 | ✅ 總資產／今日損益（NumberFlow）、含股利總損益、今天誰影響最大、報酬走勢（1D–全部＋0050 疊加）、AI 今日重點（M4 說明）、配置圓環、即將除權息、前五大持股、首次使用 | `src/pages/home/` |
| 持股 | ✅ 桌面可排序密集表格＋合計、手機卡片、帳戶與市場篩選（寫入網址） | `src/pages/holdings/` |
| 個股頁 | ✅ 頁首（現價、漲跌、量、加入自選、問 AI）＋分頁：總覽、K 線（lightweight-charts，日週月 K、MA）、估值（本益比／股價淨值比河流圖、EPS ≤ 0 留白、殖利率）、財務（月營收＋年增，兩張圖）、股利、我的交易；籌碼／新聞／AI 報告為「即將推出」 | `src/pages/stock/` |
| 交易 | ✅ 虛擬化清單（月份分組、無限載入）、篩選（手機抽屜）、新增／編輯（桌面 Dialog、手機 Vaul Drawer）、即時稅費試算、Sonner 通知＋復原、刪除 | `src/pages/transactions/` |
| 績效 | ✅ TWR、XIRR、最大回撤、波動度、基準比較、市值與投入本金、每月股利、每年已實現、計算方式說明 | `src/pages/performance/` |
| 設定 | ✅ 漲跌顏色（含預覽）、主題、張／股、萬億縮寫、隱私預設、成本法、基準、券商帳戶新增／編輯 | `src/pages/settings/` |
| 規劃中頁面 | ✅ 自選（本機清單可用）、AI 助理、報告、群組、匯入、手機「更多」 | `src/pages/placeholders/` |
| 資料層 | ✅ 依 api-contract 的型別、HTTP adapter（cookie）、一致的 mock adapter（default／empty／stress 情境） | `src/api/` |
| 測試 | ✅ Vitest 39 項；Playwright 冒煙 23 項；截圖 24 張 | `src/**/__tests__`、`scripts/` |
| 部署 | ✅ `public/_redirects`、README（zh-TW） | |

## Impeccable 流程與產出位置

| 步驟 | 產出 |
|---|---|
| `init` | `/PRODUCT.md`（無人可回答，依需求文件推論並標示〔推論〕） |
| `concept-seed`（new-work） | 第一次降級（impeccable.style 被擋）；網路開通後同 seed 重擲，6 個 challengers 的評比與 6 條 RAISE 記在首頁的 surface brief |
| `shape` ×6 | `apps/web/.impeccable/surfaces/*.md`（首頁含 Direction contract） |
| `document` | `/DESIGN.md`＋`/.impeccable/design.json` |
| `extract` | `src/lib/labels.ts`、`components/form-field.tsx`、`components/segmented.tsx`、`lib/chart.ts`、`.row-link`、`lib/valuation.ts`／`kline.ts`／`allocation.ts` |
| `critique` ×7 | `/.impeccable/critique/2026-11-11T16-29-49Z__*.md`（helper 寫入，會被它自己的 `.gitignore` 忽略）；追蹤副本在 `/.impeccable/reports/critique/`。單一上下文降級模式，報告第一行有標示 |
| `audit` | `/.impeccable/reports/audit/2026-11-11T16-35Z__apps-web.md`（引擎沒有 audit-storage，手動存放） |
| `detect` | 原始碼 `[]`；8 個 dev server 網址 0 項（修正前 4＋6 項，全部修正） |
| adapt／harden／onboard／clarify／polish | 見下方 |

收尾各步驟做了什麼：

- **adapt**：桌面 1440 與 iPhone 15，淺色／深色；表格 < 768px 收合為卡片；Dialog ↔ Drawer；手機抽屜固定底部的「應付＋按鈕」；`scrollbar-gutter: stable` 避免圖表在捲軸出現時溢出。
- **harden**：`?mock=stress`（26 字基金名、NT$1,234.57 億、−20% 虧損）、錯誤狀態＋重試、骨架、404 代號、ETF／美股沒有估值或營收時的說明、走勢資料不足兩天的狀態。
- **onboard**：`?mock=empty` 首頁兩個入口（輸入目前持股／匯入 M3）、沒有帳戶時導向設定、各頁空狀態都有下一步。
- **clarify**：全站 zh-TW；錯誤訊息寫原因與做法；河流圖與績效指標都有白話說明。
- **polish**：移除 shadcn nova 的玻璃模糊、統一 6／10px 圓角、按下回饋 scale 0.97、⌘K 不做動畫、蓋章動畫只在儲存成功時。

## 與真實後端整合（2026-11-11 晚）

- `pnpm dev:api`：Vite proxy `/api` → `localhost:8000`，同源 cookie；`AuthGate` 先確認 `GET /me`，開發模式自動開發登入，
  其他情況顯示「請先登入」說明（正式登入 TODO）；使用中收到 401 會回到登入畫面。
- 型別依後端 `CONTRACT_NOTES` 對齊（可為 null 的報價欄位、`Holding.is_demo`、`Valuation.notes`、`DividendRecord.is_demo`、
  現金類交易的 `quantity/price = null`…），畫面一律顯示「—」。
- 首頁與績效頁的 1D／5D 改用後端的 `range=1D`／`5D`，不再在前端裁切；基準可選 0050、加權報酬指數（`^TAIEXTR`）、
  006208、VOO，設定頁與績效頁都能改，存到 `PATCH /me/preferences`。
- 「示範資料」只標在真的是模擬的地方：持股頁逐檔標「示範報價」（美股），總覽／績效頁標「含示範資料」並列出是哪幾檔。
- 修正：交易列刪除後確認框沒有關、且被下一筆沿用（可能誤刪下一筆）；⌘K 第二次搜尋按 Enter 沒反應；
  表單關閉後「復原」沒有通知；估值頁的資料頻率與來源說明；美股股利單位。
- mock 的手續費改為元以下捨去（與後端相同：1,070,000 × 0.1425% × 0.28 → 426），也支援 1D／5D 與基準選擇。
- Playwright 對真實 API 走過所有頁面與互動，沒有 console 錯誤與失敗請求（除了登入前預期的 401）；
  真實資料截圖在 `docs/screenshots/real/`（`pnpm screenshots:real`）。

## 尚未完成／下一步

- 實機（iPhone／Android）檢查 safe area 與鍵盤＋抽屜。
- 「只記持股」帳戶的批次快照輸入畫面（`PUT /accounts/{id}/holdings`）。
- 刪除帳戶的 UI。
- 對照後端 OpenAPI 自動產生型別（目前 `src/api/types.ts` 手動維護，已與真實 API 對過）。
- 正式登入畫面（Email、Google）。
- M2：SSE 即時報價（NumberFlow 原地更新＋變動標示）、自選同步、籌碼／新聞分頁。
- 待確認事項見 `OPEN_QUESTIONS.md`。
