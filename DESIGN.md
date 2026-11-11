---
name: Forliosa
description: 以台股為主的投資管理——首頁簡潔、細節頁密集；資料狀態「蓋章為憑」。
colors:
  ground-stone: "oklch(0.972 0.005 195)"
  surface-card: "oklch(0.996 0.002 195)"
  ink: "oklch(0.23 0.025 262)"
  ink-muted: "oklch(0.47 0.018 255)"
  hairline: "oklch(0.92 0.007 215)"
  border: "oklch(0.885 0.009 215)"
  muted: "oklch(0.945 0.007 205)"
  stamp-blue: "oklch(0.44 0.135 259)"
  stamp-blue-tint: "oklch(0.935 0.022 255)"
  rail-indigo: "oklch(0.255 0.05 263)"
  rail-active: "oklch(0.345 0.07 262)"
  seal-vermilion: "oklch(0.565 0.19 33)"
  price-red: "oklch(0.545 0.205 26)"
  price-green: "oklch(0.5 0.13 152)"
  amber: "oklch(0.62 0.13 75)"
  destructive: "oklch(0.5 0.17 30)"
  chart-mine: "oklch(0.494 0.141 258.8)"
  chart-benchmark: "oklch(0.66 0.02 230)"
  chart-ochre: "oklch(0.659 0.136 68.8)"
  chart-teal: "oklch(0.624 0.105 194.9)"
  chart-violet: "oklch(0.546 0.175 285.2)"
  chart-magenta: "oklch(0.621 0.163 346.6)"
  band-1: "oklch(0.955 0.02 245)"
  band-5: "oklch(0.72 0.1 259)"
  dark-ground: "oklch(0.175 0.014 258)"
  dark-card: "oklch(0.212 0.016 258)"
  dark-ink: "oklch(0.935 0.008 250)"
  dark-stamp-blue: "oklch(0.74 0.11 256)"
  dark-rail: "oklch(0.145 0.03 263)"
typography:
  hero:
    fontFamily: "Source Sans 3 Variable, Noto Sans TC Variable, PingFang TC, Microsoft JhengHei, sans-serif"
    fontSize: "3rem"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.02em"
  page-title:
    fontFamily: "Source Sans 3 Variable, Noto Sans TC Variable, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  figure:
    fontFamily: "Source Sans 3 Variable, Noto Sans TC Variable, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 600
    lineHeight: 1.3
  section-title:
    fontFamily: "Source Sans 3 Variable, Noto Sans TC Variable, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.6
  body:
    fontFamily: "Source Sans 3 Variable, Noto Sans TC Variable, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.6
  dense:
    fontFamily: "Source Sans 3 Variable, Noto Sans TC Variable, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.55
  meta:
    fontFamily: "Source Sans 3 Variable, Noto Sans TC Variable, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.55
  chop:
    fontFamily: "Source Sans 3 Variable, Noto Sans TC Variable, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "0.06em"
rounded:
  chop: "3px"
  sm: "4px"
  md: "6px"
  lg: "8px"
  xl: "10px"
spacing:
  gutter-mobile: "16px"
  gutter-desktop: "32px"
  panel-x: "20px"
  stack: "16px"
  section: "24px"
components:
  button-primary:
    backgroundColor: "{colors.stamp-blue}"
    textColor: "{colors.surface-card}"
    rounded: "{rounded.md}"
    height: "36px"
    padding: "0 12px"
  button-outline:
    backgroundColor: "{colors.ground-stone}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    height: "36px"
  segmented-active:
    backgroundColor: "{colors.stamp-blue-tint}"
    textColor: "{colors.stamp-blue}"
    rounded: "{rounded.md}"
    height: "32px"
  chop:
    textColor: "{colors.stamp-blue}"
    rounded: "{rounded.chop}"
    typography: "{typography.chop}"
    height: "22px"
    padding: "0 5.6px"
  panel:
    backgroundColor: "{colors.surface-card}"
    rounded: "{rounded.xl}"
    padding: "12px 20px 16px"
  input:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    height: "40px"
  nav-rail-item-active:
    backgroundColor: "{colors.rail-active}"
    textColor: "{colors.surface-card}"
    rounded: "{rounded.md}"
    height: "40px"
---

# Design System: Forliosa

> 由 `/impeccable document` 從已建成的程式碼記錄（`apps/web/src/styles/globals.css`、`apps/web/src/components/`）。權威來源是程式碼；這份文件描述它。
> 方向來源：`apps/web/.impeccable/surfaces/src-pages-home-homepage-tsx.md` 的 Direction contract（印鑑與朱泥，seed:bf59ff6fbd34ea97）。concept-seed 第一次因 impeccable.style 被封鎖而降級；網路開通後以同一 seed 重擲取得 6 個 challengers，沒有一個在兩軸都勝出，因此保留指定方向並加入 6 條 RAISE（見該檔）。

## Overview

**North star：蓋章為憑（The Bank-Counter Seal）。** Forliosa 借用台灣銀行臨櫃的印鑑與印台：存摺上蓋過章的那一行才算數。介面把這個儀式用在**資料狀態**——示範資料、預估、已入帳、即將推出、M4 推出——一律以方形「章」標示；儲存交易時，通知裡的「已入帳」章會「蓋下」。

這是 Operate 介面：使用者先要知道東西在哪，才注意到世界觀。世界只提供四樣東西：**字型、色盤、密度、一個招牌動作（章）**。導覽、表格、按鈕、對話框都是標準元件（shadcn/ui + Base UI）。

混合密度（產品負責人指定）：首頁像 Google Finance——大數字、留白、少量卡片；持股、個股、交易、績效像 Yahoo 股市與 Shioaji Pro——表格與圖表為主，細線分隔、緊湊間距（RAISE：日本高密度網站的密度勇氣）。

**Key characteristics**
- 青田石冷灰底＋靛青墨色側欄（兩種主題都是深色側欄）。
- 印泥藍是唯一的操作色；朱泥紅只在品牌章；紅綠只表示漲跌。
- 全站等寬數字，大數字改用比例數字。
- 細線（hairline）而非陰影區隔；卡片不巢狀。

## Colors

色彩策略：**Restrained＋專責**。中性色取自印章石（青田石）與墨，一個操作色（印泥藍），其餘顏色各有唯一的工作（RAISE：機場黃色導視的「顏色專責」紀律）。

### Primary
- **印泥藍 Stamp Blue**（`oklch(0.44 0.135 259)`；深色 `oklch(0.74 0.11 256)`）：主要按鈕、選取狀態、焦點環、「章」的線條、圖表裡「我的」系列。藍色印台是銀行與郵局日期章的顏色。
- **印泥藍淡色**（`oklch(0.935 0.022 255)`）：選取中的分段按鈕、hover 列。

### Neutral
- **青田石底 Stone Ground**（`oklch(0.972 0.005 195)`）：頁面底色，冷灰帶一點綠青。
- **卡面 Surface**（`oklch(0.996 0.002 195)`）：Panel、表格、輸入框。
- **墨 Ink**（`oklch(0.23 0.025 262)`）與 **淡墨**（`oklch(0.47 0.018 255)`，對比 6.7:1）。
- **靛青墨側欄 Rail**（`oklch(0.255 0.05 263)`；深色 `oklch(0.145 0.03 263)`）：桌面左側欄，主題無關。
- **細線 Hairline**（`oklch(0.92 0.007 215)`）：列與列之間；**Border**（`oklch(0.885 0.009 215)`）：Panel 外框。

### Semantic
- **漲 / 跌**：`--rise`／`--fall` 依 `<html data-convention>` 對應到紅（`oklch(0.545 0.205 26)`）或綠（`oklch(0.5 0.13 152)`）。預設 `tw` 紅漲綠跌，可切換 `us`。對比皆 ≥ 4.6:1。
- **朱泥 Seal Vermilion**（`oklch(0.565 0.19 33)`）：**只**用在品牌章。
- **琥珀**：自選星號（圖形，非文字）。**Destructive**：刪除確認。

### Data visualization
- 分類色（配置圓環，固定順序，不依排名重新上色）：印泥藍 → 赭黃 → 青綠 → 紫 → 洋紅 → 石灰（第 6 塊固定是「其他」）。已用 dataviz `validate_palette.js` 驗證：淺色與深色都通過亮度帶、彩度下限、相鄰 CVD 與一般視覺下限、對比 3:1。
- 「我的」＝印泥藍實線＋8% 漸層填色；「基準」＝石灰細線。
- 估值河流圖：單一色相 5 階色帶 `--band-1…5`（便宜→昂貴），**不用紅綠**避免與漲跌混淆（RAISE：暗房曝光紀錄的固定階數）。

### Named Rules
**The One Job Rule.** 每個顏色只有一個工作。印泥藍不拿來表示「好」，紅色不拿來當品牌，綠色不拿來表示「成功」。
**The Glyph Pair Rule.** 漲跌顏色一定配 ▲▼（以及螢幕閱讀器的「上漲／下跌」），色弱也能分辨；平盤用淡墨、不加符號。

## Typography

**字型**：Source Sans 3（拉丁字母與數字，含 `tnum`）＋ Noto Sans TC（思源黑體）。兩者同一設計血統——思源黑體的拉丁部分就是從 Source Sans 衍生——所以混排時字重與字高一致。兩者都以 `@fontsource-variable` 自架（Noto Sans TC 依 unicode-range 切成約 100 個子集，只載入用到的字）。

**Character**：一個家族撐起所有角色（Operate：不用 display face）。層級靠字重、色調與細線，不靠更多字級（RAISE：航空時刻表的單一字級紀律）。

### Hierarchy（固定 rem，比例約 1.2）
- **Hero**（600，2.25rem 手機／3rem 桌面，比例數字）：總資產、個股現價、目前本益比。
- **Page title**（600，1.75rem）：每頁一個 h1。
- **Figure**（600，1.375rem）：今日損益、指標格。
- **Section title**（600，1rem）：Panel 標題。
- **Body**（400，1rem／1.6）：說明文字，行長 ≤ 65ch（`max-w-prose`）。
- **Dense**（400，0.875rem）：表格、清單、表單。
- **Meta**（400，0.8125rem）：日期、代號、補充說明。
- **Chop**（600，0.75rem，字距 0.06em）：章內文字。

### Named Rules
**The Tabular Ledger Rule.** `body` 全站 `font-variant-numeric: tabular-nums`，金額、股數、日期在表格裡直向對齊；只有獨立的大數字（`.hero-figure`）改用比例數字。負號一律用 U+2212「−」。
**The 16px Input Rule.** 輸入框在觸控裝置一律 16px（避免 iOS 放大頁面）。

## Layout

- **Shell**：桌面 ≥ 1024px：232px 靛青側欄＋sticky 頂部列（⌘K 搜尋、隱私、主題、記一筆）＋內容最大寬 1280px、左右 32px。手機：精簡頂部列（品牌章、搜尋、隱私、主題）＋底部五分頁（總覽、持股、自選、AI、更多），內容左右 16px，底部預留 `88px + safe-area`。
- **首頁**：Hero 兩欄（總資產與損益｜今天誰影響最大）→ 2/3 報酬走勢＋1/3 AI 今日重點 → 配置／除權息／前五大持股三欄。
- **細節頁**：頁首（標題＋一句說明＋動作）→ 一列篩選（帳戶 select＋分段按鈕）→ 資料。篩選永遠在它影響的資料上方一列（dataviz）。
- **響應式是結構性的**：表格在 < 768px 收合成卡片；個股分頁列水平捲動；交易表單桌面 Dialog（左右兩欄：欄位｜稅費試算），手機 Vaul 抽屜（上下堆疊）。
- 間距節奏：4 的倍數；Panel 內 20px、Panel 間 16px、區塊間 24px；標題上方空間大於下方。

## Elevation & Depth

平面系統。層級用**底色差＋細線**表達：青田石底 → 卡面 → muted 區塊（例如稅費試算欄）。陰影只出現在浮起來的東西：tooltip／popover／toast（`shadow-md`），對話框用墨色 40% 遮罩，**不用 backdrop blur**（shadcn nova 預設的玻璃效果已移除）。

## Shapes

- 方肩小圓角：控制項 6px、Panel 10px、章 3px。像印章的方肩，不是藥丸。
- 唯一的圓：圖表資料點、甜甜圈、開關。

## Components

所有基礎元件來自 shadcn/ui（style `base-nova`、Base UI primitives），依本系統改寫：見 `apps/web/src/components/ui/`。

### Chop 章（招牌元件）
`apps/web/src/components/chop.tsx`、`.chop`：1.5px 印泥藍線框、3px 圓角、12px 600 字、字距 0.06em、高 22px。語氣：`ink`（資料狀態）、`muted`（類型、里程碑）、`rail`（側欄）。`press` 變體播放「蓋章」：scale 1.12→1＋淡入，180ms `--ease-out`；只在儲存交易成功時出現（toast 的「已入帳」）。
用途：示範資料（可滑過說明）、預估（稅費試算）、即將除息、交易類型、M2–M5 推出。**不**用在一般標籤或裝飾。

### Buttons
Primary＝印泥藍底白字；Outline＝卡面底＋邊框；Ghost＝透明、hover muted。高 36px（觸控 44px）、6px 圓角、`:active` scale 0.97。

### Segmented（分段按鈕）
`components/segmented.tsx`：區間（1D…全部）、分類、設定值。role=radiogroup；選取＝印泥藍淡底＋內框線。

### Panel
`components/section.tsx`：卡面＋外框、10px 圓角、標題列 48px。不巢狀。

### Inputs / Fields
`components/form-field.tsx`：標籤在上、右側提示（例如「= 1,000 股」）、錯誤以 role=alert 讀出。輸入框高 40px、卡面底、焦點 3px 印泥藍環。

### Navigation
桌面側欄：40px 列、選取＝`rail-active` 底＋白字；尚未推出的項目右側小字標 M2–M5。手機底部分頁：60px 高、選取＝印泥藍＋粗線圖示。

### Data display
- `Money`／`Pct`／`Quantity`／`FlowMoney`（`components/finance.tsx`）：處理隱私模式（固定寬度「••••」）、萬／億縮寫（`title` 給完整數字）、漲跌色＋▲▼。
- 表格：表頭 13px 淡墨、可排序欄有 `aria-sort`、整列可點（Enter 可進入）、第一欄 sticky。
- 清單列連結 `.row-link`：整列可點、hover muted、按下 scale 0.985。

## Do's and Don'ts

### Do:
- **Do** 用章標示資料狀態（示範、預估、即將推出），並讓章可以被說明（tooltip）。
- **Do** 漲跌一律 `--rise`／`--fall`＋▲▼；圖表的系列色用印泥藍／石灰，不用紅綠。
- **Do** 隱私模式下遮蔽金額與股數，保留百分比；圖表的金額軸整張隱藏並說明原因。
- **Do** 在空間不足處用萬／億，在明細處用完整數字。
- **Do** 每個空狀態說明「這裡會出現什麼」並給一個現在能做的動作。

### Don't:
- **Don't** 把朱泥紅用在品牌章以外的地方（紅色在本產品代表「漲」）。
- **Don't** 用雙 Y 軸；營收與年增率拆成兩張圖。
- **Don't** 用玻璃模糊、漸層文字、發光數字、紫色漸層卡片。
- **Don't** 在標題上加 eyebrow／kicker 小標。
- **Don't** 用陰影區隔一般卡片；用細線。
- **Don't** 讓 AI 示意內容出現投資結論；示意只能用使用者自己的資料計算，並附免責聲明。
