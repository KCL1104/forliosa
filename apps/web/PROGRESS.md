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

## 第二批（2026-11-12）：出清紀錄、定期定額、公告、只用可商用資料、資料授權、AI 免責與無來源

| 範圍 | 狀態 | 檔案 |
|---|---|---|
| 資料層 | ✅ 型別＋HTTP＋mock：`/portfolio/closed`、`/instruments/{symbol}/position/history`（注意路徑，`/history` 是日線）、`/recurring`（GET/POST/PATCH/DELETE、`/{id}/draft`）、`/meta/attributions`；`History`／`Performance.notes`、事件 `estimated`／`period`／`investor_conference`、公告 `category`、本週事項 `plan_id`／`scheduled_date`；交易清單依後端上限每頁 200 筆分頁（先前 `limit=500` 會 422） | `src/api/` |
| mock 商用模式 | ✅ 預設模擬 `DATA_POLICY=commercial`：沒有示範標記、存檔自 2026-06-01 起（更早的日線、估值、籌碼、績效回空＋「資料累積中」）、盤中沒有點、上市股票沒有個股法人、美股沒有報價（以成本計值）、含美股時績效算不出來；`?policy=personal` 回到舊的示範資料 | `src/api/mock/commercial.ts`、`adapter.ts`、`research.ts`、`ledger.ts` |
| 已出清 | ✅ 帳本「持倉」底下的收合區塊（桌面格線表、手機三行列）；個股頁未持有時「過去的持有」；圖上的 B/S/D 與事件「只看我的」改用交易歷史（出清後也有） | `src/pages/ledger/ClosedRounds.tsx`、`src/pages/stock/StockPage.tsx` |
| 定期定額 | ✅ 設定頁「定期定額」（頭像選單、股利分頁的扣款列都連到這裡）：列表、新增／修改（帳戶、股票搜尋、金額、1–28 日複選、開始／結束、啟用、備註）、暫停開關、刪除確認；本週事項與股利分頁列出扣款（遇休市順延會說明）；扣款日 AI 面板提出「記下今天的 XXXX 定期定額」→ `POST /recurring/{id}/draft` → 草稿卡 → 簽名才入帳 | `src/pages/settings/RecurringPlans.tsx`、`src/components/day-picker.tsx`、`src/ai/recurring-offer.ts` |
| 公告與事件 | ✅ 總覽「新聞」改為「公告」（重大訊息・證交所公告，連到原文）；事件分頁把公告併入時間軸（同一則重大訊息去重）、「預估」標記、財報／營收／法說會分開 | `src/lib/events.ts`、`src/pages/stock/tabs/` |
| 商用模式的空狀態 | ✅ 1 日走勢「盤中走勢需要授權行情，目前提供收盤後資料」＋後端 notes＋「看 5 日走勢」；日線與績效的 notes 放在圖旁；績效算不出來時說明原因並可「只看台幣帳戶」；美股持股現價「—」與說明；美股個股頁不放大大的「—」 | `src/pages/stock/PriceChart.tsx`、`src/pages/ledger/PerformanceView.tsx`、`HoldingsView.tsx` |
| 資料來源與授權 | ✅ `/data-sources`：授權條款固定文字、每個資料集的完整顯名聲明（不改寫）、沒有使用的來源；頭像選單與帳本、個股頁頁尾連結 | `src/pages/data-sources/DataSourcesPage.tsx` |
| AI | ✅ 每則回答下方固定免責（`done.disclaimer` → `/ai/usage.disclaimer` → 常數「AI 回答僅供參考，非投資建議。」），模型最後一行若寫了同樣的話就不重複；`grounding` 事件（與 `ThreadMessage.grounding`）標「無來源」（淡墨細框，按下展開「這段沒有附來源，請自行查證。」）；503 `ai_unavailable` 顯示「AI 暫時無法使用」（記帳指令仍在本機寫成草稿）；紀錄「對話紀錄保留 30 天」（本機紀錄也只留 30 天） | `src/ai/answer-text.ts`、`Conversation.tsx`、`remote.ts`、`runner.ts`、`HistoryList.tsx` |

## 第三批（2026-11-12）：法人觀點、定期定額標記與補記、已出清依年份

| 範圍 | 狀態 | 檔案 |
|---|---|---|
| 資料層 | ✅ 型別＋HTTP＋mock：`GET/POST /instruments/{symbol}/analyst-views`（`none`／`pending`／`ready`／`unavailable`，最多 5 筆、免責文字）；mock：2330 直接 3 筆、其他 none → POST → pending → 約 2.6 秒後 ready 1–2 筆、2881 查無報導、2409 查不到；機構與連結是版面示意（「外資券商 A」、example.com） | `src/api/types.ts`、`http.ts`、`mock/analyst.ts` |
| 法人觀點 | ✅ 個股頁總覽、月營收／籌碼之後一個預設收合的格線區塊（和「已出清」同一種，不是卡片）：展開才 GET；`none` 給「查詢近期法人觀點」（紫色查詢圖示）→ POST → 搜尋中（文楷「正在找近期媒體報導的法人觀點…」＋一行「搜尋網路：…」）→ 每 2.5 秒輪詢、90 秒逾時；結果是桌面格線表（日期・機構・評等原文・目標價・來源連結）／手機三行列；免責文字永遠在清單上方；查無報導、查不到、AI 暫停（503）、端點還沒有（404）都是安靜的說明；額度剩 5 題內提示「查詢算一題」。不算平均、上漲空間，不排名、不寫買賣提示，評等不上色；隱私模式不影響。只有個股（ETF 沒有） | `src/pages/stock/AnalystViews.tsx`、`src/lib/analyst-views.ts`（reducer） |
| 定期定額標記 | ✅ 持倉桌面表與手機列：有啟用中計畫的股票名稱旁一個淡墨日曆圖示（可點範圍 44px），滑過「定期定額：每月 6 日 NT$10,000」（隱私模式遮金額），按下到 `/settings#plan-<id>`（捲到那一列、淡墨底標示）。手機列改成「名稱連結的 ::after 蓋滿整列」，標記才能是另一個連結 | `src/pages/ledger/RecurringMark.tsx`、`use-active-plans.ts`、`HoldingsView.tsx`、`settings/RecurringPlans.tsx` |
| 補記扣款 | ✅ 最近 7 天漏記的扣款（同帳戶同一檔在扣款日之後、下一次扣款之前沒有買進，也沒寫過草稿）→ AI 面板「補記 11/06 的 0050 定期定額」（最舊在前、最多 3 筆，今天的仍在最前）→ `POST /recurring/{id}/draft?date=`（後端支援 `date`）→ 草稿成交日是那天、說明請照對帳單改 → 簽名才入帳 | `src/ai/recurring-offer.ts`、`runner.ts` |
| 已出清依年份 | ✅ 依 `closed_at` 年份分組、新的在前，每年可收合（最近一年預設展開），年份列有已實現小計（▲▼）；桌面每年一個 tbody、小計對齊「已實現損益」欄；手機每年一個 h3＋清單 | `src/pages/ledger/ClosedRounds.tsx`、`src/lib/ledger-display.ts` |
| 法人觀點接後端 | ✅ 2026-11-12：api 模式本來就走 `http.ts` 的 `GET/POST /instruments/{symbol}/analyst-views`，後端完成（`forliosa.ai.analyst`）；`rating_text` 改為可 null、mock 的「查不到」改成後端的「HH:MM 之後可以再查一次。」；截圖補上搜尋中（2454）、查無（2881）、查不到（2409）三種狀態 | `src/api/types.ts`、`src/api/mock/analyst.ts`、`scripts/screenshots.mjs` |
| 資料來源頁 | ✅ 說明法人觀點不是授權資料庫（有人查詢時 AI 搜尋公開報導、當天共用、隔天刪除） | `src/pages/data-sources/DataSourcesPage.tsx` |

## 驗證

- `pnpm typecheck`、`pnpm lint`（0 warning）、`pnpm test`（11 檔 145 項；第三批新增：法人觀點 reducer 與狀態、顯示規則、mock 端點；漏記扣款判斷；已出清依年份；定期定額標記）、`pnpm build` 全部通過。
- Playwright 冒煙（`node scripts/smoke.mjs`，mock 模式）：22 個路由＋28 個流程全部通過；第三批新增：補記 11/06 的 0050（草稿成交日 11/6 → 簽名 → 不再提出）、已出清年份（2026／2025／2024、最近一年展開、小計）、持倉標記（說明、到設定的那個計畫、隱私模式遮金額）、法人觀點（預設收合、2330 三筆＋免責、2454 查詢 → 搜尋中 → 結果、2881 查無、2409 查不到、ETF 沒有）、手機的標記與整列點擊、手機法人觀點。
- 截圖（`pnpm screenshots`）：`docs/screenshots/v2/`，58 張全部重拍（mock 資料有變）；新增 `stock-2330-analyst-*`、`ledger-recurring-marks-*`，`ledger-closed-*` 改成年份分組。
- Impeccable detector：原始碼 0 項；即時網址（帳本、2330、2454、NVDA、設定、資料來源；1440 與 390）0 項；展開後的狀態以 `--cdp` 掃（法人觀點 ready／none／searching／empty、已出清年份；1440 與 390）修正前 1 項（搜尋中的脈動紫點）→ 0 項。
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
| critique（第三批，法人觀點） | `/.impeccable/critique/2026-11-12T07-59-24Z__apps-web-src-pages-stock-analystviews-tsx.md`（helper 寫入，31/40；子代理沒有再派子代理的工具，single-context 降級並標示）；追蹤副本 `/.impeccable/reports/critique/`；P1 四項已修正（螢幕閱讀器只念一句狀態、脈動紫點改靜止、欄寬與觸控高度、mock 標題空格），P2 兩項列在 OPEN_QUESTIONS 27–28 |
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
2. ~~「本週 N 件事」的定期定額~~：後端已有 `/recurring`，本週事項列出每一次扣款。
3. ETF 折溢價、成分股，美股財報與籌碼：設計過的空狀態，等資料來源（研究稿 Q10、Q11）。
4. 比較線「加權報酬指數」需要後端的 `/instruments/^TAIEXTR/history`；mock 以 0050 代替。真實後端沒有時圖會停留在不比較。
5. 漲跌停與參考價以後端為準；前端只在報價沒有帶時才自行計算（`lib/tick.ts`）。
6. 產品負責人決定預設 `DATA_POLICY=commercial`：盤中走勢、媒體新聞、上市股票的法人、美股報價是空的並帶 `notes`；前端照實顯示。mock 預設也模擬商用模式（`?policy=personal` 看舊的示範資料）。
7. 真實手機實測（mobile-native 的 tap delay、鍵盤、safe area）還沒做，只用 Playwright 的 iPhone 15 模擬。
