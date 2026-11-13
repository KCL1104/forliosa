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

## 第四批（2026-11-12）：股利自動入帳（docs/handoff.md §3.0）

| 範圍 | 狀態 | 檔案 |
|---|---|---|
| 資料層 | ✅ `TransactionSource` 加上 `auto`（系統在除息日自動入帳的台股股利）、`auto_edited`（使用者改過的）；`TransactionInput.source` 不能是這兩個（後端 POST／PATCH 也拒絕） | `src/api/types.ts` |
| 來源標示 | ✅ `SOURCE_TAG`（每種來源一個對應）＋`<SourceTag>`：「自動」「自動・已修改」「匯入」是淡墨細框小字（可滑過看說明，不用 AI 的紫色），「由 AI 建立」維持紫色文楷；交易列表、股利頁「已入帳」都用它（股利頁名稱太長時截斷名稱，標示一定看得到）；交易列的 aria-label 帶來源；隱私模式不顯示自動入帳的備註（寫著持有股數） | `src/lib/labels.ts`、`src/components/finance.tsx`、`src/pages/ledger/TransactionsView.tsx`、`DividendsView.tsx` |
| 說明 | ✅ 股利頁「已入帳」上方一行「台股股利在除息日自動入帳，美股股利要自己記。」（空狀態也改）；編輯自動那筆時表單上方說明「儲存變更後就是你自己的版本，系統不會再更新；刪除後也不會再自動入帳」（改過的：「系統不會再更新它」）；刪除確認框與刪除通知加一句「這筆股利之後不會再自動入帳」；沒改任何欄位就按儲存不送出（維持「自動」） | `src/pages/transactions/TradeForm.tsx`、`src/lib/ledger-display.ts` |
| AI | ✅ 「股利入帳」的提問說明台股會自動入帳、範例改成美股（從台股個股頁進來時說可以更正金額）；後續建議只提美股入帳；台股現金股利草稿在 120 天內已有自動入帳時加一行「9/16 除息的股利已經自動入帳；簽名後改以這筆為準，不會重複計算」 | `src/ai/runner.ts` |
| mock | ✅ 與後端相同的同步（`syncAutoDividends`）：除息預告＝存檔起點後的台股紀錄；股數＝除息日前一天收盤的持股；自己記的（manual／import／ai_draft，除息日起 120 天內）優先；改了 → `auto_edited`＋略過；刪了 → 略過；交易新增／修改／刪除、持股快照、追蹤模式變更後重算。示範資料：8 月以前自己記的股利維持手動，之後的 2330（9/16）、6488（9/22，上櫃）、2454（10/8，零股）是自動入帳；美股照舊手動。另修正 mock 修改交易原地改物件（列表不會更新）、改股數時金額不重算的問題 | `src/api/mock/auto-dividends.ts`、`ledger.ts`、`adapter.ts` |

## 第五批（2026-11-12）：美股財報與申報（SEC EDGAR）

| 範圍 | 狀態 | 檔案 |
|---|---|---|
| 資料層 | ✅ `Financials` 多 `currency`、`amount_unit`（台股 1000、美股 1）、`period_ends`、`shares`、`as_of`；事件類型多 `sec_filing`＋`form`。mock 的 AAPL、NVDA 用後端對 SEC 真實資料（2026-11-12）的輸出（`sec-data.ts`，不是模擬數字），兩種政策都一樣；總覽的近四季 EPS 也來自它；資料來源頁多三個 SEC 資料集（授權連結是 SEC 的網站政策） | `src/api/types.ts`、`mock/sec-data.ts`、`mock/research.ts`、`mock/attributions.ts` |
| 財務分頁 | ✅ 美股個股不再是空狀態：季／年財報表格（美元、公司會計年度 `FY2026Q4`，表頭第二行「至 2026/09/26」），單位說明「美元；EPS 為稀釋每股盈餘」，首句「FY2026Q4 EPS 2.10 美元，比去年同季成長 14%」；說明（會計年度、單季推算方式、股票分割換算）逐行列出、和資料來源分開；沒有月營收。美股 ETF：「ETF 沒有自己的財報」＋「美股目前也沒有可商用的配息資料來源」（不再叫人去看股利分頁）；美股的股利分頁沒有資料時寫「美股目前沒有可商用的配息資料來源」，不說成「過去沒有配息紀錄」。SEC 未啟用或找不到公司：「目前沒有這家公司的 SEC 財報」＋後端 notes | `src/pages/stock/tabs/FinancialsTab.tsx` |
| 事件分頁 | ✅ SEC 申報依表單標類型：10-K「年報」、10-Q「季報」、8-K「重大事件」（修正加「修正」），標題如「8-K 營運結果與財務狀況」，連到 sec.gov 原文（「在 SEC EDGAR 查看」）；持有時年報、季報算「我的」；美股的頁尾說明改成 SEC 版本 | `src/pages/stock/tabs/EventsTab.tsx`、`src/lib/events.ts`（`eventLabel`） |
| 截圖 | ✅ `stock-aapl-financials-*`、`stock-aapl-events-*`（桌面／iPhone、淺／深） | `scripts/screenshots.mjs` |

## 第六批（2026-11-12）：上市股票的法人動向、定期定額草稿帶扣款日（docs/handoff.md §3.4、§3.5）

| 範圍 | 狀態 | 檔案 |
|---|---|---|
| 籌碼分頁 | ✅ 上市股票：「三大法人買賣超」是空狀態（原因＋「最近外資對這檔的動向？」交給 AI），外資持股比一句說明，頁尾不重複說明；上櫃照常 | `src/pages/stock/tabs/ChipsTab.tsx` |
| 總覽小卡 | ✅ 上市股票改列融資餘額、融資增減、融券增減、千張大戶＋一句說明（之前整張消失） | `src/pages/stock/tabs/OverviewTab.tsx` |
| 建議問題 | ✅ `foreign_flow`「最近外資對這檔的動向？」：上市個股、排在為什麼漲跌之後；自由提問也分類得到；本機規則版只說明原因、連到融資融券與公告（後端由 AI 搜尋新聞，附來源與日期） | `src/ai/suggestions.ts`、`types.ts` |
| AI 面板 | ✅ 對話捲到底只捲面板的捲動區，從頁面按「問 AI」時頁面不再跳回頂端 | `src/ai/Conversation.tsx` |
| 定期定額 | ✅ 補記過去的扣款：mock 用扣款日當天的收盤價（`price_as_of` = 扣款日）；AI 的話「我先照那天的收盤價算好股數」；設定頁說明改寫 | `src/api/mock/recurring.ts`、`src/ai/runner.ts`、`src/pages/settings/RecurringPlans.tsx` |
| mock | ✅ 上市股票任何模式都沒有法人與外資持股；2330 的為什麼漲拿掉「投信連 5 天買超」 | `src/api/mock/research.ts` |
| 審查修正 | ✅ 本機規則版的外資動向回答改說「證交所以付費商品提供，沒有免費、可商用的來源」，和籌碼分頁空狀態（後端 notes）一致；定期定額草稿的說明抽成 `recurringDraftCopy`，草稿是示範價格（`is_demo`）時 AI 的話與草稿說明都說「示範價格」，不說成收盤價 | `src/ai/suggestions.ts`、`src/ai/runner.ts` |

## 第七批（2026-11-12）：M5 分享——登入、授權唯讀查看、親友群組（`docs/api-contract.md`「分享（M5）」）

前端照合約做完（後端另一批）；合約沒寫到的地方選最保護隱私的做法，決定與要確認的事在 `OPEN_QUESTIONS.md` 40–56。

| 範圍 | 狀態 | 檔案 |
|---|---|---|
| 資料層 | ✅ 全部 M5 型別（分享投影的欄位一律選用：沒開放的鍵不存在）與 40 個端點的 HTTP adapter（含 Discord 登入網址）；`PerformanceRange` 加 `MTD`；`User.avatar_url`；查看模式時每個請求帶 `X-Forliosa-View-As`（`/me`、`/me/preferences`、`/auth/*`、`GET /delegations` 除外）；React Query hooks 都放在 `["groups", id, …]` 底下，任何改動整組重抓（投影由伺服器每次重新套用） | `src/api/types.ts`、`http.ts`、`view-as.ts`、`sharing-queries.ts` |
| mock | ✅ 每個 M5 端點，規則和合約一樣：每次讀取依目前的開關重新投影、沒開放的鍵不存在、沒開的人不在排行／動態／持股、看不到的留言對象 404、非成員 404、權限不足 403、上限 50／20、六個表情、webhook 網址檢查與 `webhook_failed`、Telegram 連結碼（約 6 秒後當作已連結）、移除成員撤回多人邀請、擁有者要先轉移才能離開。授權查看用和後端相同的路由白名單（白名單 GET 以授權者、只算範圍內帳戶；寫入 `read_only`；其他 `view_as_not_allowed`；失效 `delegation_revoked`；行情忽略標頭）。爸爸有一本完整帳本，查看、動態、分享都從它算；`?auth=signed-out` 模擬沒登入 | `src/api/mock/sharing.ts`、`members.ts`、`adapter.ts` |
| 登入 | ✅ `/login`：「用 Discord 登入」（整頁導到 `/auth/discord/start?next=`）、六種 `oauth_*` 錯誤說明、開發登入表單（`dev_login` 或開發建置）；沒有 session 時導到 `/login?next=<原網址>`，`next` 用和後端同一條規則檢查；開發模式照舊自動開發登入。登入頁與邀請頁不包外殼 | `src/pages/auth/LoginPage.tsx`、`src/app/AuthGate.tsx`、`RootLayout.tsx`、`src/lib/next-path.ts`、`oauth-errors.ts` |
| 設定 | ✅ 個人資料（顯示名稱，`PATCH /me`）；授權查看：授權給同群組的人（全部帳戶／指定帳戶）、修改範圍、撤銷；授權給我的人「查看」與「移除」 | `src/pages/settings/Profile.tsx`、`Delegations.tsx` |
| 查看模式 | ✅ 墨色橫幅「正在查看 ○○ 的資產（唯讀）」＋範圍＋結束查看（桌面在頂部列下一起 sticky，手機的「問 AI」換成「結束查看」）；隱藏 AI 面板與所有 AI 入口、記一筆、股利入帳、交易編輯刪除、待簽名、觀察、定期定額標記、加入觀察、法人觀點；群組／紀錄／設定顯示「結束查看後才能使用」；基準用授權者的；進出時丟掉使用者資料的快取；403 `delegation_revoked` 自動退出並通知 | `src/app/ViewAsBanner.tsx`、`view-as.ts`、`AppShell.tsx`、帳本與個股頁 |
| 群組列表 | ✅ 我的群組（角色、人數、不排名次、最近動態、最近週報）＋建立群組；保留可貼到 LINE 的百分比分享卡（今日・本月（MTD）・總報酬） | `src/pages/groups/GroupsPage.tsx` |
| 邀請 | ✅ `/invite/:token`：沒登入也能預覽 → 登入後回來；加入前先選六個開關（預設只開報酬率），交易動態旁明講最近 90 天；404／410 分開說明 | `src/pages/groups/InvitePage.tsx`、`ShareToggles.tsx` |
| 群組頁 | ✅ sticky 分頁：排行（今日・本月・今年、名次或依加入順序、總報酬不排名、加權報酬指數與 0050 對照、期間起點、只對自己說明「—」、當天排行的討論串）・動態（合併筆數、成交價只在對方開了才有並受隱私模式遮蔽、加入了群組、六個表情、留言串）・持股（共同持股、產業、每人權重）・週報（AI 摘要紫色文楷、數字、免責、表情與留言）・我的分享（六個開關，持股＋金額提示可推算股數、附上成交價要先開交易動態、列出推播頻道）・成員（角色、轉移、移出、離開、邀請連結管理、改名、排名開關、刪除群組）・頻道（Discord webhook、Telegram 連結碼、通知開關、停用狀態；非擁有者唯讀）。成員詳細頁只顯示存在的區塊，沒有就是「還沒有資料」 | `src/pages/groups/GroupPage.tsx`、`MemberPage.tsx`、`Discussion.tsx`、`tabs/` |
| AI | ✅ 群組頁的建議問題「群組會分享我的哪些資料？」改成說明現在的規則 | `src/ai/suggestions.ts` |
| 審查修正 | ✅ Telegram 停用後重新連結：依頻道變成使用中判斷完成，連結碼照常顯示；查看模式擋下「紀錄」頁，AI 請求也帶 `X-Forliosa-View-As`（伺服器白名單是最後一道），`useAskAi` 查看中不送出；帳本與個股頁的「你／我」查看中換成授權者名稱；手機橫幅 sticky、`--sticky-top` 排在橫幅下；⌘K 查看中的預設選取對得上看得到的項目；交易的空狀態與「接下來」的定期定額扣款在查看中不給寫入或設定頁的入口；成員詳細頁有動態時不說「還沒有資料」；橫幅範圍以 `GET /delegations`（不帶標頭）每分鐘更新 | `ChannelsTab.tsx`、`HistoryPage.tsx`、`src/ai/remote.ts`、`use-ask.ts`、`src/api/view-as.ts`、`src/app/view-as.ts`、`ViewAsBanner.tsx`、`AppShell.tsx`、`CommandSearch.tsx`、帳本與個股頁、`MemberPage.tsx`、`src/app/__tests__/view-as-ui.test.tsx` |

## 第八批（2026-11-13）：討論串（`docs/api-contract.md`「討論串（2026-11-13）」）

公開／群組的主題與回覆、表情、檢舉、站方管理、公開暱稱。線圖彈幕與指數頁暫緩，沒有做。前端自己決定的地方與要確認的事在 `OPEN_QUESTIONS.md` 57–67；視覺規則在 `DESIGN.md` Components〈討論〉。

| 範圍 | 狀態 | 檔案 |
|---|---|---|
| 資料層 | ✅ 型別（公開範圍的作者只有 `name`／`is_you`）、16 個端點的 HTTP adapter（`PUT /users/me/public-name`、`/discussions/*`、`/admin/discussions/*`）；`ApiError.extra` 帶錯誤物件裡的附加欄位（`retry_after_seconds`、`until`、`retry_after_days`）；TanStack Query hooks，表情是樂觀更新（按下就改快取，失敗還原，送完再讀一次） | `src/api/types.ts`、`http.ts`、`discussion-queries.ts`、`view-as.ts` |
| mock | ✅ 和後端同一套規則：沒登入能讀公開的、群組主題一律 404、檢查順序 停權 → 公開暱稱 → 頻率（滾動 24 小時／60 分鐘、公開發言間隔 10 秒，照實際時間）、暱稱唯一與 7 天冷卻（第一次不算）、隱藏、檢舉（每小時 20 則）、站方管理、時間是 UTC `Z`。示範資料：8 則公開主題（含被隱藏的回覆、已刪除帳號的回覆、內文有網址）、家族投資 3 則、大學同學 1 則、兩則待處理與兩則已處理的檢舉、一筆停權 | `src/api/mock/discussions.ts`、`adapter.ts`、`sharing.ts`、`src/lib/discussion-text.ts` |
| 導覽與外殼 | ✅ 頂部列與手機底部列都是 帳本・群組・討論；「紀錄」從「問 AI」的時鐘到 `/history`；討論與站方管理是 AI 面板的安靜頁面；沒登入讀公開討論用精簡的外殼（字標＋登入）；查看別人的資產時討論擋下 | `src/app/nav.ts`、`RootLayout.tsx`、`AuthGate.tsx`、`PublicShell.tsx`、`AvatarMenu.tsx`、`CommandSearch.tsx`、`src/ai/AiScreen.tsx`、`src/lib/next-path.ts`、`src/router.tsx` |
| 清單 | ✅ `/discussions`：篩選（全部｜公開｜我的群組）、排序（最新回覆｜最新主題）、印好表頭的格線列（日期格・標題・作者・回覆數・標記的股票・群組）、看更多、空狀態、免責 | `src/pages/discussions/DiscussionsPage.tsx`、`TopicRows.tsx` |
| 主題頁 | ✅ `/discussions/:id`：內文（純文字、保留換行、網址變連結）、表情、回覆（格線列）、刪除（先確認）、檢舉、回覆區（回覆框／選公開暱稱／登入後發言／停權說明／主題已隱藏） | `TopicPage.tsx`、`ReplyComposer.tsx`、`PlainText.tsx`、`PostedTime.tsx`、`src/lib/linkify.ts` |
| 開新主題 | ✅ `/discussions/new`：發到哪裡（`?scope=&group_id=` 預先選）、標題、內文、標記股票（`?symbol=` 預先標記，最多 5 檔）、就地的錯誤（422／409／403／429） | `NewTopicPage.tsx` |
| 獨立元件 | ✅ `PublicNamePrompt`（選公開暱稱的一欄表單）、`ReportDialog`（只需要合約的 `target`）——之後的功能可以直接用 | `PublicNamePrompt.tsx`、`use-public-name-form.ts`、`ReportDialog.tsx` |
| 入口 | ✅ 個股頁的「討論」分頁（事件後面；標記這一檔的主題）、群組頁的「討論」分頁（動態後面）、設定的公開暱稱與停權說明 | `src/pages/stock/tabs/DiscussionsTab.tsx`、`src/pages/groups/tabs/DiscussionsTab.tsx`、`src/pages/settings/Profile.tsx` |
| 站方管理 | ✅ `/admin/discussions`（只有站方管理員，頭像選單的「站方管理」）：檢舉（待處理｜已處理；隱藏／不處理／停權…／取消隱藏，都先確認）、停權中（解除） | `src/pages/admin/AdminDiscussionsPage.tsx` |
| 共用 | ✅ 表情小格抽成共用元件（群組與討論同一個）；連結樣式的外框按鈕有框線了；代號搜尋在觸控裝置 44px 高 | `src/components/reaction-chips.tsx`、`ui/button.tsx`、`symbol-picker.tsx` |
| 測試 | ✅ 單元：mock 合約 30 項、文字規則與連結安全 9 項、畫面 31 項（沒登入的外殼、篩選與排序、公開暱稱、回覆與頻率限制、表情樂觀更新、檢舉、站方管理的權限、開新主題、查看模式、導覽）；冒煙：9 個路由＋7 個流程；截圖 32 組 | `src/api/mock/__tests__/discussions.test.ts`、`src/pages/discussions/__tests__/`、`scripts/smoke.mjs`、`scripts/screenshots.mjs` |

## 驗證

- `pnpm typecheck`、`pnpm lint`（0 warning）、`pnpm test`（13 檔 166 項；第三批新增：法人觀點 reducer 與狀態、顯示規則、mock 端點；漏記扣款判斷；已出清依年份；定期定額標記；第四批新增：來源標示、編輯說明與「沒改不送出」、AI 會取代的自動入帳、mock 股利自動入帳的同步規則）、`pnpm build` 全部通過。
- Playwright 冒煙（`node scripts/smoke.mjs`，mock 模式）：22 個路由＋30 個流程全部通過（第四批新增：股利頁的「自動」與說明；編輯自動那筆 → 「自動・已修改」、刪除自動那筆後不再出現）；第三批新增：補記 11/06 的 0050（草稿成交日 11/6 → 簽名 → 不再提出）、已出清年份（2026／2025／2024、最近一年展開、小計）、持倉標記（說明、到設定的那個計畫、隱私模式遮金額）、法人觀點（預設收合、2330 三筆＋免責、2454 查詢 → 搜尋中 → 結果、2881 查無、2409 查不到、ETF 沒有）、手機的標記與整列點擊、手機法人觀點。
- 截圖（`pnpm screenshots`）：`docs/screenshots/v2/`，58 張全部重拍（mock 資料有變）；新增 `stock-2330-analyst-*`、`ledger-recurring-marks-*`，`ledger-closed-*` 改成年份分組。第四批新增 12 張 `ledger-auto-dividends-{transactions,dividends,edit}-{desktop,iphone}-{light,dark}`（只拍新的：其他畫面的數字沒變，交易列表的股利改在除息日、多了「自動」）。
- 第五批：`pnpm test` 13 檔 168 項（新增外資動向的建議與回答、上市股票的 mock 籌碼、補記用扣款日收盤價）；冒煙 22 個路由＋31 個流程全部通過（新增上市／上櫃籌碼與問 AI 外資動向、補記說「那天的收盤價」；設定頁修改計畫前先等商品帶入，避免機器忙時按太快）；截圖新增 `stock-2330-foreign-ask-*`、`stock-6488-chips-*`，重拍 `stock-2330-chips-*`、`stock-2330-overview-*`；detector 原始碼與 2330／6488 籌碼網址 0 項。
- 第五批審查修正：`pnpm test` 14 檔 171 項（新增 `recurring-draft.test.ts`：那天的收盤價／最近收盤價／示範價格三種說法；外資動向回答和空狀態說法一致）；冒煙全部通過（外資動向的等待字串跟著改）；重拍 `stock-2330-foreign-ask-*` 4 張。
- Impeccable detector：原始碼 0 項；即時網址（帳本、2330、2454、NVDA、設定、資料來源；1440 與 390）0 項；展開後的狀態以 `--cdp` 掃（法人觀點 ready／none／searching／empty、已出清年份；1440 與 390）修正前 1 項（搜尋中的脈動紫點）→ 0 項。
- 寬度檢查：390、820、1024、1280、1440、1920 都沒有水平捲動。
- 第七批（M5）：見下方「M5 驗證」。

### M5 驗證

- `pnpm typecheck`、`pnpm lint`（0 warning）、`pnpm build` 通過；`pnpm test` 18 檔 216 項（新增 `api/mock/__tests__/sharing.test.ts` 22 項：排行／成員分享／動態的投影與鍵不存在、看不到的留言對象 404、非成員 404、權限 403、webhook、邀請 401／409／410／404、授權查看白名單與 `delegation_revoked`；`api/__tests__/view-as.test.ts` 8 項：查看標頭帶與不帶、切換時丟快取、撤銷自動退出、`next` 規則、`oauth_*` 說明；`pages/groups/__tests__/m5-ui.test.tsx` 9 項：分享開關、排行／動態／成員分享不顯示「未分享」與沒開放的區塊、成交價隱私遮蔽、邀請流程）。
- 冒煙（`node scripts/smoke.mjs`）：32 個路由＋44 個檢查全部通過，新增 10 個路由與 14 個流程（建立群組與邀請連結、排行與討論串、表情與成交價、關掉交易動態後消失、成員分享與隱私模式、頻道、授權給別人、查看模式、授權失效自動退出、沒登入的邀請流程、登入錯誤說明、手機的結束查看與分頁捲動）。
- 截圖：`docs/screenshots/v2/m5-*-{desktop,iphone}-{light,dark}.png` 19 個畫面 76 張。
- Impeccable detector：原始碼 0 項；即時網址（群組列表、家族投資七個分頁、大學同學、成員詳細、邀請、登入、設定；1280 與 390）0 項。

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
3. ETF 成分股，美股籌碼：設計過的空狀態，等資料來源（研究稿 Q10、Q11）。美股財報已接 SEC EDGAR（第四批）。ETF 折溢價已接證期局〈證券投資信託基金每日淨值〉（2026-11-12，總覽與估值分頁的「淨值與折溢價」）。
4. 比較線「加權報酬指數」需要後端的 `/instruments/^TAIEXTR/history`；mock 以 0050 代替。真實後端沒有時圖會停留在不比較。
5. 漲跌停與參考價以後端為準；前端只在報價沒有帶時才自行計算（`lib/tick.ts`）。
6. 產品負責人決定預設 `DATA_POLICY=commercial`：盤中走勢、媒體新聞、上市股票的法人、美股報價是空的並帶 `notes`；前端照實顯示。mock 預設也模擬商用模式（`?policy=personal` 看舊的示範資料）。
7. 真實手機實測（mobile-native 的 tap delay、鍵盤、safe area）還沒做，只用 Playwright 的 iPhone 15 模擬。
