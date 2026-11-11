---
version: 1
slug: "src-pages-home-homepage-tsx"
primary_target: "src/pages/home/HomePage.tsx"
related_targets: ["src/app/AppShell.tsx"]
---

# Surface: App shell + 總覽（首頁）

`/impeccable shape 總覽` 的產出（無人可回答：子代理依需求文件推論，假設標示〔推論〕）。

## Scope and mode

- 模式：**Operate**（登入後的 app 畫面；使用者來完成「看懂今天」這件事）。
- 範圍：整個 app 外殼（桌面左側欄＋頂部列、手機底部五分頁）與首頁 `/`。正式程式碼（production-ready），所有資料走 typed API client（無後端時用 mock adapter）。

## Job and audience

- 誰：產品負責人與家人朋友；手機（通勤、午休、收盤後）與桌機（週末整理）同等重要。
- 需求：打開就知道**總資產與今日損益**；其次「含股利的總損益」「走勢與大盤比較」「哪些股票快除權息」「資產集中在哪」。
- 成功：3 秒內讀到兩個大數字與方向（▲▼＋顏色），不需捲動。

## Outcome and proof

- 主要數字：`PortfolioSummary.market_value`、`day_change`/`day_change_pct`、`total_pnl`/`total_return_pct`（含股利）。
- 走勢：`Performance.series`（`twr_index` vs `benchmark_index`），區間 1D/5D/1M/6M/YTD/1Y/全部。〔推論〕API 的 performance range 只有 1M/3M/6M/YTD/1Y/ALL；1D 與 5D 由前端以「1M」資料裁切最後 1／5 個交易日顯示（1D 顯示今日 vs 昨收兩點，標示「盤中走勢需即時行情（M2）」）。已記入 OPEN_QUESTIONS。
- AI 今日重點：靜態說明卡，標示「M4 推出」，不得捏造 AI 分析內容。
- 配置：`allocation.by_type / by_market / by_industry / by_currency` 圓環圖＋切換。
- 即將除權息：`upcoming_dividends`。前幾大持股：`/portfolio/holdings` 依權重排序前 5。

## Selected direction

- 視覺權威：新世界（無既有設計）。見下方 Direction contract。
- 結構：首頁＝簡潔（Google Finance 式大數字、留白、少量卡片）；其餘頁＝密集。
- 焦點時刻：Hero 的兩個 NumberFlow 數字；隱私模式切換時數字以「＊＊＊」等寬遮罩取代（寬度穩定，不跳版）。

## States and ranges

- 金額範圍：0 → NT$123,456,789,012；負值（虧損）；今日損益 0（平盤，灰色、無箭頭，用「—」）。
- 首次使用（沒有持股）：hero 換成兩個入口「輸入目前持股」「匯入對帳單（M3）」＋「先新增一筆交易」。
- 載入：骨架（同尺寸佔位），不用置中 spinner。錯誤：卡片內說明＋重試。
- 示範資料：頂部列與各卡片 `is_demo` 時顯示「示範資料」章。

## Interaction and layout

- 桌面：左側欄 232px（品牌章＋10 個導覽，分組：帳本／研究／AI 與分享／設定）；頂部列：⌘K 搜尋、示範章、隱私切換、主題切換。
- 內容最大寬 1280，hero 一列；下面 2/3 走勢圖＋1/3 AI 卡；再下面 配置／除權息／前五大持股 三欄。
- 手機（390）：頂部精簡列（品牌、搜尋、隱私），內容單欄；底部分頁「總覽、持股、自選、AI、更多」含 safe-area；圖表高度 200。

## Constraints and open decisions

- 紅漲綠跌（可切換），永遠加 ▲▼；等寬數字；萬／億縮寫只在空間不足處（手機卡片）；詳細處用完整數字。
- 1D/5D 資料來源待後端確認（OPEN_QUESTIONS）。

## Direction contract

THESIS: 帳本的每一筆都「蓋章為憑」。Forliosa 借用台灣銀行臨櫃的印鑑與印台儀式：資料狀態（示範資料、預估、已入帳、即將推出）用方形「章」標示，像存摺上蓋過章的那一行才算數。拒絕這個類別的預設：灰底儀表板＋紫藍漸層卡片＋發光數字。

OWN-WORLD: 底色取自青田石的冷灰微綠（淺色）／墨色石板（深色）；側欄是深靛青墨色（兩種主題都是）；操作與選取色是藍色印台的印泥藍（深、不偏紫）；朱泥紅只出現在品牌章，因為紅色在本產品代表「漲」。紅綠只用於漲跌並永遠配 ▲▼。字型 Source Sans 3（拉丁與等寬數字）＋ Noto Sans TC（思源黑體，同一設計血統）。元件方肩小圓角、細線框、不用玻璃與漸層；「章」是 1.5px 墨線方框、字內縮。

STORY: 使用者一打開就看到總資產與今日損益，相信數字算對（稅費、股利都算進去），也清楚資料狀態（示範、延遲）；接著往下看走勢與大盤、配置、除權息，或用 ⌘K 進個股研究估值。

FIRST VIEWPORT: 桌面 1440：左側 232px 靛青墨色側欄（朱泥品牌章＋分組導覽）；頂部列左側 ⌘K 搜尋框，右側示範資料章、隱私眼睛、主題切換。內容第一列：總資產（40px 等寬數字）＋今日損益（方向色＋▲▼＋%）＋含股利總損益；第二列 2/3 報酬走勢（區間章鈕＋基準疊加）、1/3 AI 今日重點。手機 390：hero 滿版、底部五分頁。

FORM: 自有清單第 7 名（印鑑與朱泥）；seed:bf59ff6fbd34ea97。Signature move：狀態章；儲存交易時章「蓋下」（scale 1.08→1、160ms ease-out）出現在 Sonner 通知與新的一列。名稱翻譯：朱泥紅因與「紅漲」語意衝突，只保留在品牌章。

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Grounded candidate list（concept-seed 降級擲骰，無 challengers）

依共鳴排序：1 存摺（紙本印刷）、2 經濟日報股市行情版（新聞紙表格）、3 台北捷運導視系統（識別系統）、4 紅包與春聯（儀式物件）、5 郵局儲金綠（識別系統）、6 台灣高山茶園等高線（自然地景）、7 **印鑑與朱泥**（器物、臨櫃儀式）。擲骰指定 7。impeccable.style 無法連線，所以沒有 catalog challengers 與 QUALITY BAR 圖卡；沒有人可在決策頁回答，因此直接採用指定方向（未重擲）。IMPECCABLE’S PICK（未採用）為 1 存摺──風險：過於熟悉、容易變成「橫線帳簿」的戲服。
