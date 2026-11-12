---
name: Forliosa
description: 以台股為主的持倉帳本——像聯絡簿一樣一行一行排好的帳，旁邊坐著先寫草稿、等你簽名的 AI。
colors:
  paper: "#fbfbf8"
  raised: "#ffffff"
  rule: "#d6dee8"
  ink: "#1f2a44"
  ink-2: "#5b6478"
  ctl: "#838ca0"
  hov: "#f2f4f8"
  act-hover: "#0f1730"
  ai: "#5b3fa0"
  ai-wash: "#f5f2fb"
  ai-rule: "#a896d6"
  price-red: "#c42b2b"
  price-green: "#12773e"
  chart-bench: "#8a93a6"
  chart-blue: "#3b6bb5"
  chart-ochre: "#a87a26"
  chart-grid: "#e6ebf1"
  band-cheap: "#eef2f7"
  band-dear: "#95a8c3"
  night-paper: "#14171f"
  night-raised: "#1b2029"
  night-rule: "#2a3140"
  night-ink: "#e6e9f0"
  night-ink-2: "#97a0b4"
  night-ctl: "#5e6880"
  night-ai: "#a996f0"
  night-ai-wash: "#1d1a2c"
  night-ai-rule: "#5f4f9a"
  night-price-red: "#ff6b6b"
  night-price-green: "#4cc38a"
typography:
  total:
    fontFamily: "Noto Sans TC Variable, PingFang TC, Microsoft JhengHei, sans-serif"
    fontSize: "4rem"
    fontWeight: 500
    lineHeight: 1.05
    letterSpacing: "-0.02em"
  quote:
    fontFamily: "Noto Sans TC Variable, sans-serif"
    fontSize: "3rem"
    fontWeight: 500
    lineHeight: 1.15
    letterSpacing: "-0.015em"
  total-mobile:
    fontFamily: "Noto Sans TC Variable, sans-serif"
    fontSize: "2.5rem"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "-0.015em"
  page-title:
    fontFamily: "Noto Sans TC Variable, sans-serif"
    fontSize: "2rem"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  mobile-title:
    fontFamily: "Noto Sans TC Variable, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 700
    lineHeight: 1.3
  section-title:
    fontFamily: "Noto Sans TC Variable, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 700
    lineHeight: 1.4
  row-name:
    fontFamily: "Noto Sans TC Variable, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 500
    lineHeight: 1.35
  body:
    fontFamily: "Noto Sans TC Variable, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.5
  body-mobile:
    fontFamily: "Noto Sans TC Variable, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  dense:
    fontFamily: "Noto Sans TC Variable, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
  meta:
    fontFamily: "Noto Sans TC Variable, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.5
  micro:
    fontFamily: "Noto Sans TC Variable, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.45
  ai-greeting:
    fontFamily: "LXGW WenKai TC, Kaiti TC, BiauKai, serif"
    fontSize: "1.5rem"
    fontWeight: 400
    lineHeight: 1.4
  ai-voice:
    fontFamily: "LXGW WenKai TC, Kaiti TC, BiauKai, serif"
    fontSize: "1.25rem"
    fontWeight: 400
    lineHeight: 1.5
  ai-greeting-mobile:
    fontFamily: "LXGW WenKai TC, Kaiti TC, BiauKai, serif"
    fontSize: "2rem"
    fontWeight: 400
    lineHeight: 1.3
rounded:
  tag: "2px"
  control: "4px"
  group: "6px"
  card-mobile: "12px"
  pill: "9999px"
  sign: "0px"
spacing:
  gutter-mobile: "20px"
  gutter-tablet: "32px"
  gutter-desktop: "56px"
  ai-panel: "400px"
  row: "60px"
  row-mobile: "72px"
  section: "40px"
  stack: "16px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    height: "40px"
    padding: "0 12px"
  button-primary-hover:
    backgroundColor: "{colors.act-hover}"
  button-outline:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "40px"
    padding: "0 12px"
  segmented-active:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    height: "34px"
    padding: "0 16px"
  suggestion-card:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.group}"
    height: "52px"
    padding: "0 14px 0 16px"
  composer:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.group}"
    padding: "12px 10px 10px 14px"
  draft-card:
    backgroundColor: "{colors.ai-wash}"
    textColor: "{colors.ai}"
    rounded: "{rounded.sign}"
  sign-box:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.sign}"
    width: "76px"
    height: "60px"
  demo-tag:
    textColor: "{colors.ink}"
    rounded: "{rounded.tag}"
    typography: "{typography.micro}"
    height: "20px"
    padding: "0 5px"
  dock-tabs:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.pill}"
    height: "64px"
  ask-ai:
    backgroundColor: "{colors.ai-wash}"
    textColor: "{colors.ai}"
    rounded: "{rounded.pill}"
    width: "86px"
    height: "64px"
---

# Design System: Forliosa

> 由 `/impeccable document`（降級的 documenter 流程，前端子代理執行）從 2026-11-12 重新建成的程式碼記錄；取代舊的「印鑑與朱泥」世界。權威來源是程式碼：token 在 `apps/web/src/styles/globals.css`，世界元件在 `apps/web/src/components/`（Section、DemoTag、Sparkline、Segmented）與 `apps/web/src/ai/`（AI 面板、草稿卡、簽名格）。
> 方向來源：`apps/web/.impeccable/surfaces/src-pages-ledger-ledgerpage-tsx.md` 的 Direction contract（聯絡簿，seed:634d2915cfbf2a24），決策稿在 `.impeccable/mocks/decision/r4-*`。

## Overview

**Creative North Star: "家長簽名的聯絡簿（The Signed Contact Book）"**

帳本就是首頁。介面借用台灣學生每天帶回家的聯絡簿：淺色是紙白、深色是夜間筆記本；1px 藍灰格線就是結構，表格不包卡片；文字與動作用藍黑原子筆的墨色寫。AI 是另一支筆——老師的紫色筆，取代紅筆，因為紅色在這個產品代表「漲」。AI 說的話用文楷，看起來像手寫在簿子上的評語。AI 做的每件事都先寫成草稿（紫色虛線），使用者在方形「簽名｜確認入帳」格按下才生效；簽名後格子裡留下使用者的字。

這是 Operate 介面：導覽、表格、分段、選單都是使用者早就會用的標準元件。世界只提供四樣東西：**字型**（Noto Sans TC＋只給 AI 的文楷）、**色盤**（紙、格線、藍黑墨、紫、價格紅綠）、**密度**（Google Finance 的留白主數字＋一行一格的帳）、**一個招牌動作**（簽名格）。

**Key Characteristics:**
- 紙白（深色：夜間筆記本）的底，1px 藍灰格線分隔每一行，沒有卡片包表格。
- 藍黑墨是唯一的操作色：主要按鈕、選取中的分段、焦點框。
- 紫色只屬於 AI：問候、建議問題的圖示、回答、草稿卡、「待簽名」、「問 AI」按鈕。
- 紅綠只表示價格的漲跌，永遠配 ▲▼。
- 全站等寬數字；報價依升降單位決定小數位。

## Colors

色彩策略：**Restrained，兩支筆**。中性色是紙與格線，操作是藍黑墨，AI 是紫，價格是紅綠；每個顏色只有一個工作。

### Primary
- **藍黑墨 Ink**（淺色 `ink`、深色 `night-ink`）：所有文字、主要按鈕底、選取中的分段、焦點框、圖表上「我的」線、均價線。按下時更深（`act-hover`）。
- **淡墨 Ink 2**（`ink-2`、`night-ink-2`）：標籤、日期、單位、次要說明。對比 5.7:1（淺）／6.8:1（深）。

### Secondary
- **老師的紫 AI**（`ai`、`night-ai`）：AI 的字、圖示與草稿卡的數字。**紫色淡底**（`ai-wash`）是草稿卡與「問 AI」按鈕的底；**紫色虛線**（`ai-rule`）是草稿卡與「待簽名」的框。

### Tertiary
- **價格紅綠**（`price-red`／`price-green`，深色 `night-price-*`）：只用在價格、漲跌幅與由價格直接造成的損益（今日損益、未實現）。依 `<html data-convention>` 對應到漲／跌：預設 `tw` 紅漲綠跌，可切換 `us` 綠漲紅跌。

### Neutral
- **紙白 Paper**（`paper`）／**夜間筆記本**（`night-paper`）：頁面底色。
- **白紙 Raised**（`raised`、`night-raised`）：建議卡、輸入框、手機總資產卡、浮動分頁。
- **格線 Rule**（`rule`、`night-rule`）：列與列、區塊標題底線、AI 面板左側的雙線。
- **鉛筆灰 Ctl**（`ctl`、`night-ctl`）：控制項的 1px 外框（分段、輸出按鈕、輸入框），對比 3.2:1。
- **淡墨底 Hov**（`hov`）：hover 列、次要圓形按鈕底。

### Data visualization
- 「我的」＝墨色實線；「基準／比較」＝鉛筆灰（`chart-bench`）虛線；均線 MA5／20／60 ＝赭（`chart-ochre`）／藍筆（`chart-blue`）／鉛筆灰。
- 估值河流圖：單一藍灰色相 5 階（`band-cheap` → `band-dear`），便宜到昂貴，不用紅綠。
- 法人買賣超：買超墨色、賣超鉛筆灰，靠零軸位置與正負號辨識（不是價格，所以不用紅綠）。
- 成交量柱用 30% 的漲跌色（它跟著當天價格方向）。

### Named Rules
**The Two Pens Rule.** 墨色是使用者的筆，紫色是 AI 的筆。紫色出現的地方一定是 AI 說的話或 AI 做的事；AI 以外的東西不准用紫色。
**The Price-Only Red Rule.** 紅綠只給價格與由價格造成的損益，並且一定配 ▲▼（與螢幕閱讀器的「上漲／下跌」）。營收年增、法人買賣超、刪除按鈕都不用紅綠。
**The Rule-Is-Structure Rule.** 結構用 1px 格線表達：列底線、區塊標題底線、鍵值格的格線。表格不包卡片，卡片不巢狀。

## Typography

**字型**：Noto Sans TC Variable（介面、數字，以 `@fontsource-variable/noto-sans-tc` 自架，依 unicode-range 只載入用到的字）；LXGW WenKai TC（文楷，只給 AI 的話，以 `@fontsource/lxgw-wenkai-tc` 自架，同樣依 unicode-range 子集載入）。

**Character**：一個無襯線家族撐起整個帳本；文楷是唯一的第二個聲音，而且只屬於 AI。層級靠字級、字重與格線，不靠顏色。

### Hierarchy
- **Total**（500，64px／手機 40px，比例數字）：總資產。前面的「NT$」用 24px 淡墨。
- **Quote**（500，48px／手機 40px）：個股現價（NumberFlow）。
- **Page title**（700，32px／手機 24px）：個股名稱、設定、群組。
- **Section title**（700，20px）：區塊標題，底下一條格線。
- **Row name**（500，17px）：持倉表與清單的名稱；數字欄同為 17px。
- **Body**（400，15px 桌面／16px 手機，行高 1.5）。
- **Dense**（14px）：明細、圖例、按鈕。**Meta**（13px，淡墨）：表頭、代號・股數、日期。**Micro**（12px）：免責、資料來源、示範資料。
- **AI greeting**（文楷 400，24px；手機 32px）與 **AI voice**（文楷 400，20px）：問候、回答、「為什麼」那一行、分頁第一行。

### Named Rules
**The Tabular Ledger Rule.** `body` 全站 `tabular-nums`；只有獨立的大數字（總資產、現價）用比例數字。負號一律 U+2212「−」。
**The Tick Decimal Rule.** 報價的小數位依台股升降單位：≥ 500 元 0 位（1,085）、0.1／0.5 檔 1 位且整數不帶小數（236.5、398）、0.01／0.05 檔 2 位（22.40）、美股 2 位。漲跌點數跟著現價的位數。
**The 16px Input Rule.** 觸控裝置上輸入框一律 16px 以上（手機「搜尋或提問」17px），避免 iOS 放大頁面。

## Layout

- **桌面（≥ 1024px）**：頂部列 64px（字標、帳本／群組、搜尋股票 ⌘K、隱私、頭像），左側主欄最大 1180px、左右 56px（1280 以下 32px），右側 AI 面板 400px（1024–1279 為 340px），sticky 在頂部列下、可收合成 56px 的窄欄並記住狀態。主欄隨視窗捲動。
- **手機（< 1024px）**：標題列 60px（字標、隱私、頭像），內容左右 20px；底部浮動膠囊分頁「帳本｜群組｜紀錄」（64px，最大寬 520px）＋獨立的紫色「問 AI」（86×64px），下方預留 104px＋safe area，背後一段紙色漸層讓內容淡出。
- **帳本**：主數字列（左：總資產、今日、總損益；右：近 1 個月走勢）→ 一行「本週 N 件事」（上下格線）→ 分段「持倉・交易・股利・績效」＋待簽名＋自訂 → 內容。持倉表 5 欄、列高 60px（手機兩行列 72px）；觀察區是同一張表的第二個 tbody。
- **個股頁**：麵包屑 → 名稱 → 現價與漲跌 → 時間、參考價、漲跌停 → 「為什麼」一行（只在異常時）→ 我的部位（上下格線）→ 走勢圖（工具列、240／320px、區間）→ sticky 分頁列「總覽・估值・財務・籌碼・股利・事件」→ 分頁內容。
- **節奏**：4 的倍數；區塊之間 40px，標題上方留白大於下方。鍵值格 3 欄（手機 2 欄），每格 44px 以上。

## Elevation & Depth

平的。層級用紙色差（紙白 → 白紙）＋格線表達。陰影只出現在浮起來的東西：手機浮動分頁與「問 AI」、選單、popover、toast，共用一種柔和投影（0 6px 18px ＋ 0 1px 2px，墨色 10%）。對話框用墨色 32% 遮罩，不用背景模糊。

## Shapes

- 方肩：控制項 4px、分段外框與建議卡 6px、示範資料標記 2px。
- 手機才有的圓：總資產卡與建議卡 12px、浮動分頁與「問 AI」、手機輸入框與動作膠囊（全圓）。
- 簽名格與草稿卡是直角（0px）——表單上的方格，不是按鈕。

## Components

基礎元件來自 shadcn/ui（Base UI 版），依本系統改寫：`apps/web/src/components/ui/`。

### Buttons
- **Primary**：墨色底、紙色字、4px、高 40px（觸控 44px），按下 scale 0.97。一個畫面最多一個。
- **Outline**：透明底＋1px 鉛筆灰框，hover 淡墨底。工具列與次要動作。
- **AI**：紫色淡底＋紫色虛線（「待簽名 N 筆」）。

### Chips
- **區間選擇**（1日 5日 1月 6月 今年 1年 5年 全部）：文字按鈕，選取＝墨色實底；role=radiogroup、方向鍵切換。
- **分段**（持倉・交易・股利・績效）：1px 鉛筆灰外框 6px、內距 4px，選取＝墨色實底；role=tablist。
- **示範資料**：1px 鉛筆灰細框、12px、2px 圓角，可滑過看說明。只在 `is_demo: true` 時出現（商用模式從不出現）；同一個細框也用在「預估」（法定期限的備援日期）。
- **每月日期格**（`components/day-picker.tsx`，定期定額扣款日）：7 欄 1–28 日、可複選，格線框 4px，選取＝墨色實底，`aria-pressed`、方向鍵移動。

### Cards / Containers
- 沒有一般卡片。唯一的容器是：建議卡（白紙＋格線框，52px 高，右側紫色問號圖示）、手機總資產卡、草稿卡。

### 收合的格線區塊（已出清）
持倉表底下、預設收合：標題列和「觀察」同一套（粗體名＋淡墨檔數），右側淡墨「已實現」合計（漲跌色＋▲▼）與 ⌄；展開是另一張格線表（名稱・持有期間・已實現損益・領過股利・手續費與稅），手機三行列。個股頁對應的是「過去的持有」（上下格線，一個回合一列）。

### 資料說明（DataNotes）
後端的 `notes`（「資料累積中：自 … 起存檔」、美股沒有可商用來源…）照原文以淡墨小字放在圖表旁；圖表或績效沒有資料時，空狀態的說明就是這些 notes，再給一個現在能做的動作（看 5 日走勢、只看台幣帳戶）。頁尾一行「資料來源與授權」連到顯名聲明頁。

### Inputs / Fields
- **輸入框（桌面 AI）**：白紙底、1px 墨色框、6px；兩行文字區＋「＋」（附件與表單）＋送出（墨色方鈕）。焦點 2px 墨色外框。
- **輸入框（手機「搜尋或提問」）**：56px 全圓、紫色淡底＋紫色細框；輸入代號或名稱時上方即時列出股票。

### Navigation
- 桌面：頂部列文字分頁，選取＝粗體＋2px 墨色底線。搜尋框是一個 360px 的按鈕，打開 ⌘K（cmdk）。
- 手機：浮動膠囊分頁，選取＝粗體＋圖示後面 52×28 的淡墨圓底。

### 簽名格 Sign Box（招牌元件）
`apps/web/src/ai/DraftCard.tsx`：76×60px 直角方格、墨色底、內縮 3px 的細框（像表單上的簽名欄），上一行 12px「簽名」、下一行 14px 粗體「確認入帳」。按下後呼叫 `POST /transactions`（`source: "ai_draft"`），格子變成透明底＋墨色框，裡面以文楷寫出使用者名字的第一個字（墨水由左往右寫出，380ms ease-out），下面一行入帳時間；Sonner 通知附「復原」。

### 草稿卡 Draft Card
紫色淡底＋紫色虛線（簽名後變實線）：標題「買進 元大台灣50 0050」、成交日與帳戶、2×2 鍵值格（股數、成交價、手續費、證交稅；股利為總額、二代健保、預扣稅、手續費）、合計（20px 粗體紫）、說明行（沒寫價格／單位、賣超持股）、「怎麼算的 ⌄」（稅費規則）、修改（原地改股數、價格、日期、帳戶）、簽名格。

### AI 面板 AI Panel
頭部「問 AI」＋新對話・紀錄・收合；首頁狀態：一行文楷問候、最多 3 個依頁面與資料自動出現的建議問題（不加任何說明字樣）、常用動作（記一筆交易・匯入對帳單・股利入帳・更多）；對話狀態：使用者的話靠右（白紙小框）、AI 的話紫色文楷（串流逐字出現）、草稿卡跟在後面；回答寫完後下方一排「來源」小連結（標題＋網域，1px 格線框、↗，滑過看引用原文；網路搜尋的引用一定要顯示）；串流中末尾一個安靜的紫點（`motion-safe` 才脈動），查資料時旁邊一行灰字（「搜尋網路：…」「查看持股…」），寫完就消失；額度、連線、「AI 暫時無法使用」等狀況是一行灰字說明，拒答是 AI 的話（文楷）；每則回答下方固定一行 12px 淡墨免責（後端 `done.disclaimer`，模型不自己寫）；沒有來源的新聞式句子下方一條鉛筆灰點線，後面接「無來源」細框小字（淡墨，不用紅），按下展開「這段沒有附來源，請自行查證。」；底部輸入框（還沒有對話時下方一行免責；提問額度剩 5 題以內時多一句）。扣款日當天，建議問題最前面是「記下今天的 XXXX 定期定額」，點了交出草稿卡。

## Do's and Don'ts

### Do:
- **Do** 讓 AI 的每個動作先成為草稿（紫色虛線），使用者簽名才生效，事後可以復原並標示「由 AI 建立」。
- **Do** 漲跌一律 `--rise`／`--fall`＋▲▼，報價依升降單位決定小數位。
- **Do** 隱私模式遮蔽金額與股數、隱藏圖上的均價線與買賣點，保留百分比。
- **Do** 「為什麼」那一行、分頁第一行只在有值得說的事時出現；沒有就不顯示。
- **Do** 每個空狀態說明為什麼沒有、什麼時候會有，並給一個現在能做的動作。商用模式缺資料時照後端 `notes` 原文說明，不用示範資料充數。

### Don't:
- **Don't** 在 AI 以外的地方用紫色，也不要在價格以外的地方用紅綠（營收、法人、刪除都不行）。
- **Don't** 在介面上寫「本頁建議」「依頁面推薦」「AI 摘要」這類說明 AI 機制的字樣；紫色文楷就是唯一的 AI 識別。
- **Don't** 放 AI 今日簡報、AI 旁註或市場總覽首頁。
- **Don't** 用卡片包表格、巢狀卡片、陰影區隔一般區塊；用格線。
- **Don't** 用印章、朱泥、徽記或任何仿實物質感（舊世界已移除）。
- **Don't** 在標題上加 eyebrow／kicker 小標，也不要用 Unicode 符號代替圖示（▲▼ 是資料符號，不是圖示）。
