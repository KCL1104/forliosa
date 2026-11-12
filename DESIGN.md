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
  night-paper: "#0e1424"
  night-raised: "#141b2e"
  night-rule: "#2a3754"
  night-ink: "#e6e9f2"
  night-ink-2: "#9ba6c0"
  night-ctl: "#5a6888"
  night-hov: "#172038"
  night-sel: "#1f2a45"
  night-act: "#dbe2f1"
  night-act-hover: "#eef2fa"
  night-on-bg: "#24314d"
  night-on-ring: "#8796ba"
  night-ai: "#b4a3f5"
  night-ai-wash: "#1a1a35"
  night-ai-rule: "#6b5dbb"
  night-price-red: "#ff6b6b"
  night-price-green: "#4cc38a"
  night-chart-bench: "#7d89a8"
  night-chart-blue: "#7fa6e0"
  night-chart-ochre: "#d2a75a"
  night-chart-grid: "#1d2741"
  night-band-1: "#16203a"
  night-band-2: "#1d2a4a"
  night-band-3: "#26365c"
  night-band-4: "#31456f"
  night-band-5: "#3e5584"
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
    fontFamily: "TW-Kai, Noto Sans TC Variable, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 400
    lineHeight: 1.4
  ai-voice:
    fontFamily: "TW-Kai, Noto Sans TC Variable, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 400
    lineHeight: 1.5
  ai-greeting-mobile:
    fontFamily: "TW-Kai, Noto Sans TC Variable, sans-serif"
    fontSize: "2rem"
    fontWeight: 400
    lineHeight: 1.3
rounded:
  tag: "2px"
  control: "4px"
  group: "6px"
  card-mobile: "12px"
  pill: "9999px"
  menu: "6px"
  dialog: "12px"
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
  button-sign:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.sign}"
    typography: "{typography.dense}"
    height: "40px"
    padding: "0 20px"
  segmented-active:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    height: "34px"
    padding: "0 16px"
  segmented-active-night:
    backgroundColor: "{colors.night-on-bg}"
    textColor: "{colors.night-ink}"
    rounded: "{rounded.control}"
    height: "34px"
    padding: "0 16px"
  form-head:
    textColor: "{colors.ink-2}"
    typography: "{typography.meta}"
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

> 由 `/impeccable document`（降級的 documenter 流程，前端子代理執行）從 2026-11-12 重新建成的程式碼記錄；取代舊的「印鑑與朱泥」世界。權威來源是程式碼：token 在 `apps/web/src/styles/globals.css`，世界元件在 `apps/web/src/components/`（Section、DemoTag、Sparkline、Segmented、ScrollRow、Sources）與 `apps/web/src/ai/`（AI 面板、草稿卡、簽名格）。
> 方向來源：`apps/web/.impeccable/surfaces/src-pages-ledger-ledgerpage-tsx.md` 的 Direction contract（聯絡簿，seed:634d2915cfbf2a24），決策稿在 `.impeccable/mocks/decision/r4-*`。

## Overview

**Creative North Star: "家長簽名的聯絡簿（The Signed Contact Book）"**

帳本就是首頁。介面借用台灣學生每天帶回家的聯絡簿：淺色是紙白、深色是藍黑夜間筆記本；1px 藍灰格線就是結構，表格不包卡片；文字與動作用藍黑原子筆的墨色寫。AI 是另一支筆——老師的紫色筆，取代紅筆，因為紅色在這個產品代表「漲」。模型寫出來的話用楷體（全字庫正楷體），看起來像老師手寫在簿子上的評語。AI 做的每件事都先寫成草稿（紫色虛線），使用者在方形「簽名｜確認入帳」格按下才生效；簽名後格子裡留下使用者的字。

這是 Operate 介面：導覽、表格、分段、選單都是使用者早就會用的標準元件。世界只提供四樣東西：**字型**（Noto Sans TC＋只給模型寫的字的楷體）、**色盤**（紙、格線、藍黑墨、紫、價格紅綠）、**密度**（Google Finance 的留白主數字＋一行一格的帳）、**一個招牌動作**（簽名格）。

**Key Characteristics:**
- 紙白（深色：藍黑夜間筆記本）的底，1px 藍灰格線分隔每一行，沒有卡片包表格。
- 藍黑墨是唯一的操作色：主要按鈕、選取、焦點框。選取全站只有三種語法（見 Components〈Selected states〉）。
- 紫色只屬於 AI：模型寫的話、AI 做的事（草稿卡、「待簽名」）與「問 AI」入口。
- 世界在結構裡：印好的表頭（雙線）、聯絡簿的日期格、簽名格語法的定案按鈕。
- 紅綠只表示價格的漲跌，永遠配 ▲▼。
- 全站等寬數字；報價依升降單位決定小數位。

## Colors

色彩策略：**Restrained，兩支筆**。中性色是紙與格線，操作是藍黑墨，AI 是紫，價格是紅綠；每個顏色只有一個工作。

### Primary
- **藍黑墨 Ink**（淺色 `ink`、深色 `night-ink`）：使用者要讀的字（名稱、數值、句子）、主要按鈕底、焦點框、圖表上「我的」線、均價線。按下時更深（`act-hover`）。深色的主要按鈕是藍調的紙（`night-act` #dbe2f1，按下 `night-act-hover` #eef2fa，字是夜間的紙色），不是純白。
- **淡墨 Ink 2**（`ink-2`、`night-ink-2`）：只給標籤、單位、日期與其他 meta；使用者要讀的內容用墨色。對比 5.7:1（淺）／7.5:1（深；raised 上 7.0:1）。
- **選取 On**（`on-bg`／`on-fg`／`on-ring`）：分段、區間、篩選、日期格、開關的選取。淺色就是墨色實底＋紙色字（內框同色看不見）；深色是格線色調的藍底 `night-on-bg` #24314d＋墨色字（10.7:1）＋1px 內框 `night-on-ring` #8796ba（對紙 6.2:1），不是白色實塊。

### Secondary
- **老師的紫 AI**（`ai`、`night-ai`）：AI 的字、圖示與草稿卡的數字。**紫色淡底**（`ai-wash`）是草稿卡與「問 AI」按鈕的底；**紫色虛線**（`ai-rule`）是草稿卡與「待簽名」的框。

### Tertiary
- **價格紅綠**（`price-red`／`price-green`，深色 `night-price-*`）：只用在價格、漲跌幅與由價格直接造成的損益（今日損益、未實現）。依 `<html data-convention>` 對應到漲／跌：預設 `tw` 紅漲綠跌，可切換 `us` 綠漲紅跌。

### Neutral
- **紙白 Paper**（`paper`）／**藍黑夜間筆記本**（`night-paper` #0e1424）：頁面底色。深色是夜裡的筆記本：色相 224 的深藍黑，不是石板灰。
- **白紙 Raised**（`raised`、`night-raised` #141b2e）：建議卡、輸入框、手機總資產卡、浮動分頁、選單。
- **格線 Rule**（`rule`、`night-rule` #2a3754）：列與列、區塊標題底線、表頭雙線、AI 面板左側的雙線。深色的格線是看得見但安靜的印刷藍線（對紙 1.55:1）。
- **鉛筆灰 Ctl**（`ctl`、`night-ctl`）：控制項的 1px 外框（分段、輸出按鈕、輸入框），對比 3.25:1（淺）／3.3:1（深）。
- **淡墨底 Hov**（`hov`、`night-hov` #172038）：hover 列、選取的清單列、次要圓形按鈕底。

### Data visualization
- 「我的」＝墨色實線；「基準／比較」＝鉛筆灰（`chart-bench`）虛線；均線 MA5／20／60 ＝赭（`chart-ochre`）／藍筆（`chart-blue`）／鉛筆灰。
- 估值河流圖：單一藍灰色相 5 階（`band-cheap` → `band-dear`；深色 `night-band-1` → `night-band-5`，同一個藍色相越貴越亮），便宜到昂貴，不用紅綠。
- 法人買賣超：買超墨色、賣超鉛筆灰，靠零軸位置與正負號辨識（不是價格，所以不用紅綠）。
- 成交量柱用 30% 的漲跌色（它跟著當天價格方向）。

### 藍黑夜間筆記本（深色）
深色不是把淺色反過來，而是夜裡攤開的同一本簿子：頁面 `#0e1424`、浮起來的紙 `#141b2e`、印刷格線 `#2a3754`、字 `#e6e9f2`、淡墨 `#9ba6c0`、鉛筆灰 `#5a6888`、hover `#172038`、圖表格線 `#1d2741`；AI 紫 `#b4a3f5`（對紙 8.3:1、對 `#1a1a35` 淡底 7.6:1）、紫色虛線 `#6b5dbb`（對淡底 3.1:1）；漲 `#ff6b6b`（6.6:1）、跌 `#4cc38a`（8.3:1）；遮罩 `rgb(3 6 15 / .6)`。選取用格線藍底＋內框，主要按鈕用藍調的紙；整個畫面沒有純白色塊。

### Named Rules
**The Two Pens Rule.** 墨色是使用者的筆，紫色是 AI 的筆。紫色＝AI 說的話或做的事；AI 以外的東西不准用紫色。**楷體（`var(--font-ai)`／`.ai-voice`）只給模型真的寫出來的字**：串流的回答、模型寫的「為什麼」、法人觀點與公司簡介、群組週報、AI 的拒答。規則或範本產生的句子（例如「本益比 20.8 倍，比過去 5 年 96% 的日子貴」、固定的問候語、建議問題的文字）是墨色 Noto Sans，關鍵數字可以用 600，**不用紫色、不用楷體**。
**The Price-Only Red Rule.** 紅綠只給價格與由價格造成的損益，並且一定配 ▲▼（與螢幕閱讀器的「上漲／下跌」）。營收年增、法人買賣超、刪除按鈕都不用紅綠。
**The Rule-Is-Structure Rule.** 結構用 1px 格線表達：列底線、區塊標題底線、鍵值格的格線。表格不包卡片，卡片不巢狀。

## Typography

**字型**：Noto Sans TC Variable（介面、數字，以 `@fontsource-variable/noto-sans-tc` 自架，依 unicode-range 只載入用到的字）；**全字庫正楷體 TW-Kai**（`--font-ai`，只給模型寫的字）：數位發展部〈全字庫〉CNS11643 開放資料字型，依 SIL OFL 1.1 使用（授權檔在 `apps/web/src/assets/fonts/tw-kai/OFL.txt`），是台灣教育部標準字形（「為」不會變成「爲」）。自架為 unicode-range 切片（`apps/web/src/styles/tw-kai.css`，由 `scripts/tw-kai/build.py` 產生），切片裡只有漢字與全形標點；數字與拉丁字母落到 Noto Sans TC，所以 AI 句子裡的數字和帳本的數字長得一樣。

**Character**：一個無襯線家族撐起整個帳本；楷體是唯一的第二個聲音，而且只屬於模型寫的字。層級靠字級、字重與格線，不靠顏色；使用者要讀的字是墨色，淡墨只給標籤與 meta。

### Hierarchy
- **Total**（500，64px／手機 40px，比例數字）：總資產。前面的「NT$」用 24px 淡墨。
- **Quote**（500，48px／手機 40px）：個股現價（NumberFlow）。
- **Page title**（700，32px／手機 24px）：個股名稱、設定、群組。
- **Section title**（700，20px）：區塊標題，底下一條格線。
- **Row name**（500，17px）：持倉表與清單的名稱；數字欄同為 17px。
- **Body**（400，15px 桌面／16px 手機，行高 1.5）。
- **Dense**（14px）：明細、圖例、按鈕。**Meta**（13px，淡墨）：表頭、代號・股數、日期；使用者必須讀的字不小於 13px。**Micro**（12px）：免責、示範資料、日期格裡的星期。
- ▲▼ 和它旁邊的數字同一個字級（`1em`），不另外縮小。
- **AI voice**（楷體 400，20px）與 **AI greeting**（楷體 400，24px；手機 32px）：只用在模型寫的字（見 Two Pens Rule）。固定的問候語、分頁第一行這類規則句子用墨色 Noto Sans。

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

- 方肩：控制項 4px、分段外框、建議卡、選單與 popover 6px、示範資料標記與圖例色塊 2px。只用這些 token（`rounded-xs/sm/md/xl/full/none`），不寫 3px 之類的任意值。
- 手機才有的圓：總資產卡與建議卡 12px、浮動分頁與「問 AI」、手機輸入框與動作膠囊（全圓）。
- 對話框 12px。
- 簽名格、草稿卡與 `sign` 按鈕是直角（0px）——表單上的方格。

## Components

基礎元件來自 shadcn/ui（Base UI 版），依本系統改寫：`apps/web/src/components/ui/`。

### Buttons
- **Primary**：墨色底、紙色字、4px、高 40px（觸控 44px），按下 scale 0.97。一個畫面最多一個。深色是藍調的紙（`night-act`），不是純白。
- **Sign**（`<Button variant="sign">`）：簽名格的語法，給一個表單裡唯一「定案」的動作（建立群組、儲存、加入群組、記一筆的送出）。直角、墨色底、內縮 3px 的 1px 細框（40% 透明，和簽名格的 `::after` 一樣）、14px 粗體；高度和一般按鈕相同（40px，觸控 44px），左右 20px。取消、次要動作仍用 Outline／Ghost。
- **Outline**：透明底＋1px 鉛筆灰框，hover 淡墨底。工具列與次要動作。
- **AI**：紫色淡底＋紫色虛線（「待簽名 N 筆」）。

### Selected states（選取的語法）
全站只有三種選取，樣式跟著 ARIA／Base UI 的狀態屬性走（`aria-selected`、`aria-checked`、`aria-pressed`、`aria-current`、`data-active`、`data-pressed`），元件不用自己寫條件 class；token 與 utility 在 `apps/web/src/styles/globals.css`。
- **(a) 文字分頁與導覽**（`sel-tab`）：頂部列「帳本／群組」、個股分頁列、群組分頁列。選取＝墨色字、700、2px 墨色底線（壓在分頁列的格線上）；未選取＝淡墨；沒有底色。
- **(b) 分段與選項**（`sel-chip`）：分段（持倉・交易・股利・績效）、區間（1日…全部）、篩選、每月日期格、切換群組、開關的「開」。選取＝`on-bg` 底＋`on-fg` 字＋1px 內框 `on-ring`、500。淺色就是墨色實底＋紙色字；深色是格線藍底 #24314d＋墨色字＋#8796ba 內框——**不是白色實塊**。hover 是淡墨底。
- **(c) 清單裡選取的那一列**（`sel-row`）：`hov` 底＋開頭 2px 墨色線（`inset` 陰影，不改版面）。
- 不准有第四種：不用白色實塊、不用紫色、不用陰影表示選取。

### Chips
- **區間選擇**（1日 5日 1月 6月 今年 1年 5年 全部）：文字按鈕，選取語法 (b)；role=radiogroup、方向鍵切換；放不下時是 ScrollRow（見下）。
- **分段**（持倉・交易・股利・績效）：1px 鉛筆灰外框 6px、內距 4px，選取語法 (b)；role=tablist。
- **示範資料**：1px 鉛筆灰細框、12px、2px 圓角，可滑過看說明。只在 `is_demo: true` 時出現（商用模式從不出現）；同一個細框也用在「預估」（法定期限的備援日期）。
- **每月日期格**（`components/day-picker.tsx`，定期定額扣款日）：7 欄 1–28 日、可複選，格線框 4px，選取語法 (b)，`aria-pressed`、方向鍵移動。

### ScrollRow（橫向捲動的一列）
`components/scroll-row.tsx`：手機上放不下的分頁列、區間與篩選。沒有箭頭；只有「後面還有」的那一邊用 mask 淡出 28px，隨捲動與尺寸變化（ResizeObserver）更新；選取中的子元件在載入與選取改變時捲進畫面，鍵盤移動焦點時焦點所在的子元件也會。這個 div 就是捲動容器，可以直接給 `role="tablist"`／`role="radiogroup"`。

### 印好的表頭與日期格
- **`.form-head`**：表格與格線清單的表頭像印好的表格——13px 淡墨標籤，下面一條雙線（1px 格線、2px 空隙、1px 格線，畫在背景、不佔版面）。用在 `<thead>`、表頭的 `<tr>`，或 div／li 做的表頭列；表頭列自己不要再加 `border-b`。
- **`.date-cell`**：聯絡簿的日期格——日期墨色 500（等寬數字），星期（`.weekday`）12px 淡墨，右邊一條 1px 格線。用在 `<td>`／`<th>` 或 div 格線清單的第一欄。

### Cards / Containers
- 沒有一般卡片。唯一的容器是：建議卡（白紙＋格線框，52px 高，右側紫色問號圖示）、手機總資產卡、草稿卡。

### 收合的格線區塊（已出清）
持倉表底下、預設收合：標題列和「觀察」同一套（粗體名＋淡墨檔數），右側淡墨「已實現」合計（漲跌色＋▲▼）與 ⌄；展開是另一張格線表（名稱・持有期間・已實現損益・領過股利・手續費與稅），手機三行列。個股頁對應的是「過去的持有」（上下格線，一個回合一列）。

### 資料說明（DataNotes）
後端的 `notes`（「資料累積中：自 … 起存檔」、美股沒有可商用來源…）照原文以淡墨小字放在圖表旁；圖表或績效沒有資料時，空狀態的說明就是這些 notes，再給一個現在能做的動作（看 5 日走勢、只看台幣帳戶）。狀態說明不是資料來源，不放進頁尾。

### 資料來源頁尾（Sources footer）
每一頁只在最下面出現一次，各區塊不再各自寫授權段落。頁面用 `<SourcesProvider>` 包住，區塊用 `useSourceNote(sources)` 登記自己用到的來源（後端 `sources` 的顯名聲明字串可以直接給；以名稱＋授權去重），頁尾放 `<SourcesFooter />`：收合時是一行 13px 淡墨的「資料來源與授權 ⌄」（`aria-expanded`），展開是依授權分組的格線清單（授權名稱 13px 淡墨一次，下面每個來源一列 14px 墨色），最後一行連到「完整顯名聲明」（`/data-sources`）。這一頁沒有登記任何來源時，只是一個連到聲明頁的小連結。

### Inputs / Fields
- **輸入框（桌面 AI）**：白紙底、1px 墨色框、6px；兩行文字區＋「＋」（附件與表單）＋送出（墨色方鈕）。焦點 2px 墨色外框。
- **輸入框（手機「搜尋或提問」）**：56px 全圓、紫色淡底＋紫色細框；輸入代號或名稱時上方即時列出股票。

### Navigation
- 桌面：頂部列文字分頁，選取語法 (a)。搜尋框是一個 360px 的按鈕，打開 ⌘K（cmdk）。
- 個股與群組的分頁列：選取語法 (a)；手機放不下時是 ScrollRow。
- 手機：浮動膠囊分頁，選取＝粗體＋圖示後面 52×28 的 `sel` 圓底（深色 #1f2a45）。

### 簽名格 Sign Box（招牌元件）
`apps/web/src/ai/DraftCard.tsx`：76×60px 直角方格、墨色底、內縮 3px 的細框（像表單上的簽名欄），上一行 12px「簽名」、下一行 14px 粗體「確認入帳」。按下後呼叫 `POST /transactions`（`source: "ai_draft"`），格子變成透明底＋墨色框，裡面寫出使用者名字的第一個字（墨色；這不是模型寫的字，依 Two Pens Rule 不用楷體）（墨水由左往右寫出，380ms ease-out），下面一行入帳時間；Sonner 通知附「復原」。

### 草稿卡 Draft Card
紫色淡底＋紫色虛線（簽名後變實線）：標題「買進 元大台灣50 0050」、成交日與帳戶、2×2 鍵值格（股數、成交價、手續費、證交稅；股利為總額、二代健保、預扣稅、手續費）、合計（20px 粗體紫）、說明行（沒寫價格／單位、賣超持股）、「怎麼算的 ⌄」（稅費規則）、修改（原地改股數、價格、日期、帳戶）、簽名格。

### AI 面板 AI Panel
頭部「問 AI」＋新對話・紀錄・收合；首頁狀態：（問候只在模型真的寫了那一句時出現，楷體）最多 3 個依頁面與資料自動出現的建議問題（不加任何說明字樣）、常用動作（記一筆交易・匯入對帳單・股利入帳・更多）；對話狀態：使用者的話靠右（白紙小框）、AI 的話紫色楷體（串流逐字出現）、草稿卡跟在後面；回答寫完後下方一排「來源」小連結（標題＋網域，1px 格線框、↗，滑過看引用原文；網路搜尋的引用一定要顯示）；串流中末尾一個安靜的紫點（`motion-safe` 才脈動），查資料時旁邊一行灰字（「搜尋網路：…」「查看持股…」），寫完就消失；額度、連線、「AI 暫時無法使用」等狀況是一行灰字說明，拒答是 AI 的話（楷體）；每則回答下方固定一行 12px 淡墨免責（後端 `done.disclaimer`，模型不自己寫）；沒有來源的新聞式句子下方一條鉛筆灰點線，後面接「無來源」細框小字（淡墨，不用紅），按下展開「這段沒有附來源，請自行查證。」；底部輸入框（還沒有對話時下方一行免責；提問額度剩 5 題以內時多一句）。扣款日當天，建議問題最前面是「記下今天的 XXXX 定期定額」，點了交出草稿卡。

## Do's and Don'ts

### Do:
- **Do** 讓 AI 的每個動作先成為草稿（紫色虛線），使用者簽名才生效，事後可以復原並標示「由 AI 建立」。
- **Do** 漲跌一律 `--rise`／`--fall`＋▲▼，報價依升降單位決定小數位。
- **Do** 隱私模式遮蔽金額與股數、隱藏圖上的均價線與買賣點，保留百分比。
- **Do** 「為什麼」那一行、分頁第一行只在有值得說的事時出現；沒有就不顯示。
- **Do** 每個空狀態說明為什麼沒有、什麼時候會有，並給一個現在能做的動作。商用模式缺資料時照後端 `notes` 原文說明，不用示範資料充數。

### Don't:
- **Don't** 在 AI 以外的地方用紫色，也不要在價格以外的地方用紅綠（營收、法人、刪除都不行）。
- **Don't** 在介面上寫「本頁建議」「依頁面推薦」「AI 摘要」這類說明 AI 機制的字樣；紫色楷體（只在模型寫的字上）就是唯一的 AI 識別。
- **Don't** 放 AI 今日簡報、AI 旁註或市場總覽首頁。
- **Don't** 用卡片包表格、巢狀卡片、陰影區隔一般區塊；用格線。
- **Don't** 用白色實塊表示選取（深色模式尤其），也不要發明第四種選取樣式；用 Selected states 的 (a)(b)(c)。
- **Don't** 把規則或範本產生的句子寫成紫色楷體；楷體只給模型寫的字。
- **Don't** 用印章、朱泥、徽記或任何仿實物質感（舊世界已移除）。
- **Don't** 在標題上加 eyebrow／kicker 小標，也不要用 Unicode 符號代替圖示（▲▼ 是資料符號，不是圖示）。
