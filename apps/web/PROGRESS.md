# 前端進度（2026-11-12 重新設計：聯絡簿）

第一版（印鑑與朱泥、側欄五分頁、AI 今日簡報）已整個替換。新的視覺世界與資訊架構依
`apps/web/.impeccable/surfaces/src-pages-ledger-ledgerpage-tsx.md` 的 Direction contract（seed:634d2915cfbf2a24）
與決策稿 `.impeccable/mocks/decision/r4-*`。設計系統見 `/DESIGN.md`＋`/.impeccable/design.json`（從建成的程式碼重寫）。

## 已完成

| 範圍 | 狀態 | 檔案 |
|---|---|---|
| 視覺世界 | ✅ 紙白／夜間筆記本、1px 藍灰格線、藍黑墨、紫色只給 AI（文楷）、紅綠只給價格；Noto Sans TC＋霞鶩文楷 TC 皆以 @fontsource 自架 | `src/styles/globals.css` |
| 外殼 | ✅ 桌面頂部列（字標、帳本／群組、搜尋股票 ⌘K、隱私、頭像選單：設定・帳戶・外觀・漲跌顏色）＋右側 AI 面板（400px，可收合並記住，⌘J）；手機標題列＋浮動膠囊分頁「帳本｜群組｜紀錄」＋紫色「問 AI」全螢幕 | `src/app/`、`src/ai/AiPanel.tsx`、`src/ai/AiScreen.tsx` |
| AI（M4 前規則版） | ✅ 記帳指令解析（買／賣／股利、張／股、價格、日期、全形）→ `/transactions/preview` → 紫色虛線草稿（怎麼算的、修改、捨棄）→ 方形「簽名｜確認入帳」→ `POST /transactions`（`source: "ai_draft"`）→ Sonner 復原；帳本「待簽名 N 筆」；依頁面與資料自動出現的建議問題（不加說明字樣）與只用使用者資料的回答；自由提問誠實說明下一階段並給手動路徑；紀錄（對話＋示範 AI 任務） | `src/ai/` |
| 帳本（首頁） | ✅ 總資產＋今日＋總損益＋近 1 個月走勢、本週 N 件事（`/portfolio/upcoming`）、分段持倉・交易・股利・績效（網址 `?view=`）、自訂（欄位、走勢圖、釘選，存在這台瀏覽器）、持倉 5 欄可排序表／手機兩行列、觀察（`/watchlist`，盤中迷你走勢）、空帳本的 AI 入口 | `src/pages/ledger/` |
| 個股頁 | ✅ 麵包屑（注意／處置章、加入觀察、記一筆）、現價（NumberFlow，漲跌對參考價、依升降單位的小數位）、參考價與漲跌停、「為什麼」一行（只在異常時）、我的部位（隱私模式隱藏）、走勢圖（1日分時／線／K、比較加權報酬指數或 0050、MA5/20/60、成交量、均價線、B/S/D 標記、◆ 重要時刻、區間 1日…全部）、六個分頁：總覽・估值・財務・籌碼・股利・事件；ETF 與美股的設計過的空狀態 | `src/pages/stock/` |
| 群組／紀錄／設定 | ✅ 群組（M5 規則＋可複製的百分比分享卡）、紀錄（對話＋AI 任務）、設定改為新世界 | `src/pages/groups/`、`src/pages/history/`、`src/pages/settings/` |
| 資料層 | ✅ 新端點的型別、HTTP adapter、mock：overview、intraday、chips、financials、events、news、position、why、watchlist（get/post/delete）、portfolio/upcoming、Quote 的 reference_price／limit_up／limit_down、Transaction.source `ai_draft`；並依後端 CONTRACT_NOTES 的新增欄位（watchlist `quote: null`、`sparkline_interval`、集保 `label`、`notes`、`sources`）調整 | `src/api/` |
| 舊網址 | ✅ `/holdings`、`/transactions`、`/performance`、`/watchlist`、`/ai`、`/reports`、`/import`、`/more` 導到新的位置 | `src/router.tsx` |

## 驗證

- `pnpm typecheck`、`pnpm lint`（0 warning）、`pnpm test`（7 檔 86 項：指令解析、建議規則與回答、升降單位與漲跌停顯示、格式化、mock 新端點形狀、元件）、`pnpm build` 全部通過。
- Playwright 冒煙（`node scripts/smoke.mjs`，mock 模式）：19 個路由＋11 個流程（建議問題回答、AI 草稿→待簽名→簽名入帳→復原、股利指令、自由提問、表單備援、隱私、⌘K、面板收合記憶、深色、手機問 AI 搜尋、手機分頁）全部通過。
- 截圖（`pnpm screenshots`）：`docs/screenshots/v2/`，30 張（桌面 1440×900 @2x 與 iPhone 15，淺色／深色）：帳本、帳本＋AI 草稿、交易、個股 2330 總覽／估值／籌碼、紀錄、手機問 AI。
- 寬度檢查：390、820、1024、1280、1440、1920 都沒有水平捲動。

## Impeccable 流程與產出位置

| 步驟 | 產出 |
|---|---|
| `context`（目標 LedgerPage） | 載入 PRODUCT.md、舊 DESIGN.md、帳本 surface brief（Direction contract 為準） |
| new-work §6 code-led build | 依合約與 r4 決策稿建成（決策稿只作為 critique reference） |
| craft-floor | 每次 UI 編輯前遵守；design hook 對每個寫入的 UI 檔回報 0 項 |
| critique ×2 | `/.impeccable/critique/2026-11-12T04-37-08Z__*.md`（helper 寫入）；追蹤副本 `/.impeccable/reports/critique/` |
| audit | `/.impeccable/reports/audit/2026-11-12T04-40Z__apps-web.md`（這版 CLI 沒有 audit-storage，手動存放）：17/20 |
| detect | 原始碼 0 項（重寫 DESIGN.md 後）；11 個桌面網址＋8 個手機網址 0 項（修正前 2 項：標題跳級、字級層級太平） |
| finish review | `/.impeccable/reports/finish/2026-11-12__ledger-and-stock.md`：以 degraded/finish-reviewer.md 在同一上下文執行（子代理無法再派子代理，已揭露）；review 回 `fix`（新聞示範標記、› 字元當圖示），修正後 verdict pass 回 `ship`（只涵蓋這兩項） |
| document（documenter 降級流程） | `/DESIGN.md`＋`/.impeccable/design.json` 從建成的程式碼重寫（產品負責人指示直接覆寫） |
| review captures | `/.impeccable/review/desktop.png`、`mobile.png` |
| 舊 surface briefs | home／holdings／performance／transactions 標示「已被取代」；stock／settings 加上更新說明 |

Emil Kowalski skills：`mobile-native`（theme-color 改成紙色、hover 一律 gate、16px 輸入、safe area、觸控 44px、移除重複的 skip link）、ask-sonner 的原則（單一 Toaster、復原 action）、emil-design-eng（⌘K 不做動畫、按下 0.97）、animate（只有一個招牌動作：簽名墨水 380ms ease-out；其他是 220ms 落下）。

## 與決策稿／合約的差異（刻意）

- AI 輸入框沒有麥克風：還沒有語音輸入，不放不能用的控制項。「＋」改成「匯入對帳單（M3）／改用表單記一筆」。
- 分段上的數字只算到 500 筆（超過不顯示）；交易與股利數來自 `GET /transactions?limit=500`。
- 草稿合計 20px（稿 21px）、簽名格小字 12px（稿 11px）、手機問候 32px（稿 34px）：收斂到字級表。
- 研究稿建議個股頁的 AI 面板「沒有問候語」；這裡沿用外殼的一行問候（改成「台積電的事，都可以問我」），和帳本一致。
- 法人買賣超、營收年增不用紅綠（合約：紅綠只表示價格）；以墨色＋正負號、零軸位置表示。
- 「重要時刻 ◆」在 M4 前只用規則（區間內單日漲跌 ≥ 3% 的前 5 天），不寫原因。
- 隱私模式：部位區塊整塊隱藏、圖上的均價線與買賣點隱藏（研究稿建議保留線；產品負責人決定隱藏）。

## 還沒做／待確認

1. AI 任務、對話紀錄目前存在這台瀏覽器（示範的任務是 mock）；M4 定義端點後改由後端同步。
2. 「本週 N 件事」的定期定額：後端說明 `recurring` 目前不會出現（沒有資料模型），mock 有示範。
3. ETF 折溢價、成分股，美股財報與籌碼：設計過的空狀態，等資料來源（研究稿 Q10、Q11）。
4. 比較線「加權報酬指數」需要後端的 `/instruments/^TAIEXTR/history`；mock 以 0050 代替。真實後端沒有時圖會停留在不比較。
5. 漲跌停與參考價以後端為準；前端只在報價沒有帶時才自行計算（`lib/tick.ts`）。
6. 真實手機實測（mobile-native 的 tap delay、鍵盤、safe area）還沒做，只用 Playwright 的 iPhone 15 模擬。
