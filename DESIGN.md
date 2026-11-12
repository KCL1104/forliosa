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
  ai-voice:
    fontFamily: "TW-Kai, Noto Sans TC Variable, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.8
    letterSpacing: "-0.01em"
  ai-voice-mobile:
    fontFamily: "TW-Kai, Noto Sans TC Variable, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 400
    lineHeight: 1.8
    letterSpacing: "-0.01em"
  ai-line:
    fontFamily: "TW-Kai, Noto Sans TC Variable, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "-0.01em"
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
  page-max: "1180px"
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
  suggestion-row:
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    height: "52px"
    padding: "0 28px"
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
- 紅綠只表示價格的漲跌：百分比配 ▲▼，金額配 +／−。
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
- **白紙 Raised**（`raised`、`night-raised` #141b2e）：輸入框、手機總資產卡、浮動分頁、選單。
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
**The Two Pens Rule.** 墨色是使用者的筆，紫色是 AI 的筆。紫色＝AI 說的話或做的事；AI 以外的東西不准用紫色。**楷體（`var(--font-ai)`／`.ai-voice`）只給模型真的寫出來的字**：串流的回答、模型寫的「為什麼」、模型寫的公司簡介（法人觀點列是照原文擷取的資料，用墨色）、群組週報、AI 的拒答。規則或範本產生的句子（例如「本益比 20.8 倍，比過去 5 年 96% 的日子貴」——期間照資料實際長度寫、固定的問候語、建議問題的文字）是墨色 Noto Sans，關鍵數字可以用 600，**不用紫色、不用楷體**。
**The Price-Only Red Rule.** 紅綠只給價格與由價格造成的損益，而且一定有顏色以外的記號：**百分比（漲跌幅、報酬率）與股價漲跌點數用 ▲▼（百分比不帶正負號，例如 ▲4.81%）；金額（今日損益、未實現、已實現、小計）用 +／−，不加 ▲▼**（例如 −NT$1,056）。螢幕閱讀器另外讀「上漲／下跌」或「獲利／虧損」。營收年增、法人買賣超、刪除按鈕都不用紅綠。
**The Rule-Is-Structure Rule.** 結構用 1px 格線表達：列底線、區塊標題底線、鍵值格的格線。表格不包卡片，卡片不巢狀。

## Typography

**字型**：Noto Sans TC Variable（介面、數字，以 `@fontsource-variable/noto-sans-tc` 自架，依 unicode-range 只載入用到的字）；**全字庫正楷體 TW-Kai**（`--font-ai`，只給模型寫的字）：數位發展部〈全字庫〉CNS11643 開放資料字型，依 SIL OFL 1.1 使用（授權檔在 `apps/web/src/assets/fonts/tw-kai/OFL.txt`），是台灣教育部標準字形（「為」不會變成「爲」）。自架為 unicode-range 切片（`apps/web/src/styles/tw-kai.css`，由 `scripts/tw-kai/build.py` 產生），切片裡只有漢字與全形標點；數字與拉丁字母落到 Noto Sans TC，所以 AI 句子裡的數字和帳本的數字長得一樣。楷體的字面比 Noto Sans TC 小、又坐得低，切片的 `size-adjust` 是 120%：漢字墨跡的上緣和 Noto Sans TC 同字等高，同一行的數字不會顯得比楷字大。

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
- **AI voice**（楷體 400，17px／手機 18px，行高 1.8，字距 −0.01em）：模型寫的回答；楷體已經放大到和 Noto Sans TC 的漢字一樣大（size-adjust 120%），字距只收一點點，數字（Noto Sans）不會被擠。一行的楷體（模型寫的「為什麼」這類）可以用 **AI line**（20px）。只用在模型寫的字（見 Two Pens Rule）；AI 面板沒有問候語，分頁第一行這類規則句子用墨色 Noto Sans。

### Named Rules
**The Tabular Ledger Rule.** `body` 全站 `tabular-nums`；只有獨立的大數字（總資產、現價）用比例數字。負號一律 U+2212「−」。
**The Tick Decimal Rule.** 報價的小數位依台股升降單位：≥ 500 元 0 位（1,085）、0.1／0.5 檔 1 位且整數不帶小數（236.5、398）、0.01／0.05 檔 2 位（22.40）、美股 2 位。漲跌點數跟著現價的位數。
**The 16px Input Rule.** 觸控裝置上輸入框一律 16px 以上（手機「搜尋或提問」17px），避免 iOS 放大頁面。

## Layout

- **一個版心、一個左緣**（`apps/web/src/app/PageFrame.tsx`）：每一頁（帳本、個股、群組、成員、設定、資料來源、查看模式的擋頁）都用同一個外框（紀錄頁待 AI 分支合併時改用 PageFrame＋內層 max-w-[760px]）——最大寬 1180px 置中，左右 20px（手機）／32px（≥ 768px）／56px（≥ 1280px），頂端 12px（手機）／40px（桌面），底部 40px／56px。所以每一頁的標題和第一行字都從同一條左緣開始（桌面 AI 面板開著時就是頂部列字標的位置）。有麵包屑（「← 群組」）的頁面頂端用 24px：麵包屑那一列本身 44px 高，第一行字的位置和帳本一樣。
- **表單與長文在版心裡自己限寬**：設定與資料來源頁的內容欄最大 816px、靠左（左緣不變），標籤和開關不會隔太遠、長段落不會太寬；成員頁與群組「持股」的權重清單最大 720px（長條和百分比不會離名稱太遠）。表格、排行、其他清單用整個版心。長網址（授權條款）可以在任何地方斷行，不撐寬頁面。
- **桌面（≥ 1024px）**：頂部列 64px（字標、帳本／群組、搜尋股票 ⌘K、隱私、頭像；字標左邊 56px，和版心對齊），主欄放版心，右側 AI 面板 400px（1024–1279 為 340px），sticky 在頂部列下、可收合成 56px 的窄欄並記住狀態。主欄隨視窗捲動。
- **手機（< 1024px）**：標題列 60px（字標、隱私、頭像），內容左右 20px；底部浮動膠囊分頁「帳本｜群組｜紀錄」（64px，最大寬 520px）＋獨立的紫色「問 AI」（86×64px，圖示和桌面 AI 面板的「問 AI」相同：lucide PenLine），下方預留 104px＋safe area，背後一段紙色漸層讓內容淡出。放不下的分頁列（群組的七個分頁）是 ScrollRow。
- **帳本**：主數字列（左：總資產、今日、總損益；右：近 1 個月走勢——畫不出來、而且後端 notes 說了原因時，右邊是一行淡墨的原因，連到績效：notes 提到美股是「近 1 個月走勢：含美股，算不出來」，提到「資料累積中」是「資料還不夠」；載入失敗或 notes 沒說原因時什麼都不放，左邊的主數字自己撐開，不猜原因）→ 一行「本週 N 件事」（上下格線）→ 分段「持倉・交易・股利・績效」＋待簽名＋自訂 → 內容。持倉表 5 欄、列高 60px（手機兩行列 72px）；觀察區是同一張表的第二個 tbody。
- **個股頁**：麵包屑 → 名稱 → 現價與漲跌 → 時間、參考價、漲跌停 → 「為什麼」一行（只在異常時；規則判斷的句子是墨色、數字 600，後端標示模型改寫過的才是紫色楷體）→ 我的部位（上下格線）→ 走勢圖（工具列、240／320px、區間）→ sticky 分頁列「總覽・估值・財務・籌碼・股利・事件」（選取語法 (a)，手機是 ScrollRow）→ 分頁內容 → 頁尾一個「資料來源與授權」（各區塊用 `useSourceNote` 登記，不寫授權段落）。總覽分三層，不是九個一樣重的區塊：
  1. **鍵值帶**（分頁列正下方，標題只給螢幕報讀器）：股票先一行估值位置——「本益比 20.8 倍，比 6/1 以來 96% 的日子貴。」（百分位只說這一次；期間照資料實際的長度寫，滿 5 年才寫「過去 5 年」，不滿時尺下放「資料累積中」）＋整條寬的刻度尺：1px 鉛筆灰線、0／25／50／75／100 百分位五個刻度，刻度下寫該百分位的本益比，現在＝墨色實心點＋「現在」，你的成本＝空心點（隱私模式不畫；標籤會撞到「現在」時換到刻度下一行；尺是 aria-hidden，成本另外寫給螢幕報讀器）；不用 ▼△。接著一張格線鍵值格（3 欄、手機 2 欄）：行情與基本數字、月營收（年增那格併「連 N 個月」）、籌碼（近 5 日）；每股金額寫「元」（美股 US$）。只列有值的格子，不排「—」：ETF 只列 ETF 有的欄位（淨值、殖利率、折溢價——比較長，手機上自己佔一列——、配息、成交量…），格子下面接折溢價走勢；剩不到 3 格時（美股沒有行情）寫成一行，走勢圖也只留空狀態。
  2. **事件**（20px 標題）：最近 3 則官方公告（重大訊息、證交所公告；美股是 SEC 申報）＋接下來 4 件事合成一張依日期排的表，第一欄是日期格（`.date-cell`），類別欄之後的標題不重複類別（「除息｜每股 5 元」），有原文的標題常駐淡底線，右欄是相對天數，持有時除息列寫可領金額。
  3. **參考**（17px 標題、沒有說明段落）：法人觀點（收合）、新聞報導（先 3 則，「看更多」再加）、關於〈公司〉（簡介＋緊湊的兩欄鍵值格）、相關股票（一列 4 格，價格與漲跌寫在格子裡，不畫小走勢；手機橫向捲動）。
  文字連結（「所有事件」「在帳本中查看」）常駐 ctl 色底線、hover 變墨色，不只在 hover 時才出現。回應本身沒有 `sources` 的資料（月營收、股利、估值序列）用 `/meta/attributions` 的資料集登記到頁尾。
- **群組**：名稱與「N 位成員・你是○○」→ sticky 分頁列（選取語法 (a)，手機是 ScrollRow）→ 分頁內容 → 頁尾資料來源。排行是一張印好表頭的表：名次・成員・期間報酬・總報酬（含股利）。**總報酬是主數字**：最右欄、桌面 20px 600（手機 17px 600）；期間報酬是一般字級（15px 400）的一欄，名次依它排；兩個都有 ▲▼。手機也是同樣四欄（不是小字第二行），數字欄有最小寬、放不下時再長（表頭、每一列與對照是同一個 grid 的 subgrid，一起對齊）；對照（加權報酬指數、0050）只有期間報酬，對齊期間欄。
- **節奏**：4 的倍數；區塊之間 40px，標題上方留白大於下方。鍵值格 3 欄（手機 2 欄），每格 44px 以上。

## Elevation & Depth

平的。層級用紙色差（紙白 → 白紙）＋格線表達。陰影只出現在浮起來的東西：手機浮動分頁與「問 AI」、選單、popover、toast，共用一種柔和投影（0 6px 18px ＋ 0 1px 2px，墨色 10%）。對話框用墨色 32% 遮罩，不用背景模糊。

## Shapes

- 方肩：控制項 4px、分段外框、AI 輸入框、選單與 popover 6px、示範資料標記與圖例色塊 2px。只用這些 token（`rounded-xs/sm/md/xl/full/none`），不寫 3px 之類的任意值。
- 手機才有的圓：總資產卡 12px、浮動分頁與「問 AI」（全圓）。手機的 AI 輸入框和桌面一樣是 6px。
- 對話框 12px。
- 簽名格、草稿卡與 `sign` 按鈕是直角（0px）——表單上的方格。

## Components

基礎元件來自 shadcn/ui（Base UI 版），依本系統改寫：`apps/web/src/components/ui/`。

### Buttons
- **Primary**：墨色底、紙色字、4px、高 40px（觸控 44px），按下 scale 0.97。一個畫面最多一個。深色是藍調的紙（`night-act`），不是純白。
- **Sign**（`<Button variant="sign">`）：簽名格的語法，給一個表單裡唯一「定案」的動作：建立群組對話框的「建立群組」、邀請頁的「加入群組」、交易表單的「儲存／儲存變更」、設定的「儲存」（顯示名稱、群組名稱）、帳戶與定期定額對話框的「新增帳戶／新增計畫／儲存」、授權查看的「授權／儲存」、Discord 頻道的「儲存並送測試訊息」。只有一個欄位的就地修改（顯示名稱、群組名稱）：簽名格只在欄位改過之後出現，沒改時桌面留一個看不見的同寬位置（輸入框不跳動）、手機什麼都不放；桌面和輸入框同一列、同高。打開對話框的按鈕（頁首的「＋ 建立群組」）、篩選的「套用」、留言的「送出」不是定案，仍用一般按鈕。手機上不撐滿整列（`self-start`）。直角、墨色底、內縮 3px 的 1px 細框（40% 透明，和簽名格的 `::after` 一樣）、14px 粗體；高度和一般按鈕相同（40px，觸控 44px），左右 20px。取消、次要動作仍用 Outline／Ghost。
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
- **表情**（群組動態、週報、排行討論）：已經有人按的表情是 1px 格線全圓小框（表情＋數字），自己按過的用選取語法 (b)（`aria-pressed`）；旁邊「表情」是有字的按鈕（和「留言」一樣），打開六個固定表情的 popover（每一格也是 (b)）。只有圖示的按鈕（刪除留言、刪除定期定額）滑過有說明（Tooltip）。
- **篩選中**（交易的「只看 2330 ×」、動態的「只看爸爸 ×」）：選取語法 (b)（`aria-pressed="true"`），再按一次取消篩選。
- **每月日期格**（`components/day-picker.tsx`，定期定額扣款日）：7 欄 1–28 日、可複選，格線框 4px，選取語法 (b)，`aria-pressed`、方向鍵移動。

### ScrollRow（橫向捲動的一列）
`components/scroll-row.tsx`：手機上放不下的分頁列、區間與篩選。沒有箭頭；只有「後面還有」的那一邊用 mask 淡出 28px，隨捲動與尺寸變化（ResizeObserver）更新；選取中的子元件在載入與選取改變時捲進畫面，鍵盤移動焦點時焦點所在的子元件也會。這個 div 就是捲動容器，可以直接給 `role="tablist"`／`role="radiogroup"`。

### 印好的表頭與日期格
- **`.form-head`**：表格與格線清單的表頭像印好的表格——13px 淡墨標籤，下面一條雙線（1px 格線、2px 空隙、1px 格線，畫在背景、不佔版面）。用在 `<thead>`、表頭的 `<tr>`，或 div／li 做的表頭列；表頭列自己不要再加 `border-b`。目前用在：持倉表（桌面 `<thead>`、手機「持有 N 檔／現價・今日漲跌」）、交易列表、股利的「接下來」與「已入帳」（已入帳每一年一張表：年份與合計 → 表頭 → 列，年份列不另畫底線）、已出清（桌面 `<thead>`；手機展開的年份下面「名稱・持有／已實現」）、群組排行（桌面與手機）。排序中的欄位用墨色字＋箭頭（lucide ArrowDown／ArrowUp，和字同高），不用 ▲▼（那是價格漲跌的符號）。
- **`.date-cell`**：聯絡簿的日期格——日期墨色 500（等寬數字），星期（`.weekday`）12px 淡墨，右邊一條 1px 格線。元件 `apps/web/src/components/date-cell.tsx`（`<DateCell date=…>`，帳本與個股頁共用）：撐滿整列高度（抵掉列的上下內距），一列接一列時格線連成一條直線；星期的全形括號用 `halt`（半寬），兩行時左緣和日期對齊。預設手機日期與星期上下兩行、桌面一行——只給很窄的欄（交易列表的 3.25rem）；欄夠寬時用 `inline`，任何寬度都一行（股利清單的 88px 欄：「10/12（四）」）。下面可以再放一行 13px 淡墨（例如「6 天後」）。用在交易列表與股利清單的第一欄。

### Cards / Containers
- 沒有一般卡片。唯一的容器是：手機總資產卡、草稿卡。AI 面板的建議是格線列，不是卡片。
- 錯誤與狀態的一行說明（登入錯誤、頻道已停用）：上下各一條格線，不用左邊的色條。

### 收合的格線區塊（已出清）
持倉表底下、預設收合：標題列和「觀察」同一套（粗體名＋淡墨檔數），右側淡墨「已實現」合計（漲跌色＋正負號，金額不加 ▲▼）與 ⌄；展開是另一張格線表（名稱・持有期間・已實現損益・領過股利・手續費與稅），手機三行列。個股頁對應的是「過去的持有」（上下格線，一個回合一列）。

### 資料說明（DataNotes）
後端的 `notes`（「資料累積中：自 … 起存檔」、美股沒有可商用來源…）照原文以淡墨小字放在圖表旁；圖表或績效沒有資料時，空狀態的說明就是這些 notes，再給一個現在能做的動作（看 5 日走勢、只看台幣帳戶）。狀態說明不是資料來源，不放進頁尾。

### 資料來源頁尾（Sources footer）
每一頁只在最下面出現一次，各區塊不再各自寫授權段落。頁面用 `<SourcesProvider>` 包住，區塊用 `useSourceNote(sources)` 登記自己用到的來源（後端 `sources` 的顯名聲明字串可以直接給；以名稱＋授權去重），頁尾放 `<SourcesFooter />`：收合時是一行 13px 淡墨的「資料來源與授權 ⌄」（`aria-expanded`），展開是依授權分組的格線清單（授權名稱 13px 淡墨一次，下面每個來源一列 14px 墨色），最後一行連到「完整顯名聲明」（`/data-sources`）。這一頁沒有登記任何來源時，只是一個連到聲明頁的小連結。群組頁（排行、週報登記各自的來源）、帳本、設定各有一個；資料來源頁本身照常列出完整的顯名聲明。

### Inputs / Fields
- **輸入框（桌面 AI）**：白紙底、1px 墨色框、6px；兩行文字區＋「＋」（附件與表單，沒有外框的圖示鈕）＋送出（墨色方鈕，沒有字時是格線色）。焦點 2px 墨色外框；「Enter 送出・Shift+Enter 換行」只在有焦點時出現（畫面上的這行對螢幕閱讀器隱藏，改由輸入框的 `aria-describedby` 讀出同一句）。使用者在這裡寫字，所以是墨色，不是紫色。
- **輸入框（手機「搜尋或提問」）**：和桌面同一套（白紙底、1px 墨色框、6px），56px 高的一行：「＋」、17px 文字、44px 的墨色送出方鈕。輸入代號或名稱時即時列出股票，一律在輸入框上方（iOS Safari 的鍵盤直接蓋在畫面上、不縮版面，列在下方會被蓋住）：還沒有對話時取代建議與連結（同一套格線列，最高約 220px，可以捲動），對話中浮在輸入框上。

### Navigation
- 桌面：頂部列文字分頁，選取語法 (a)。搜尋框是一個 360px 的按鈕，打開 ⌘K（cmdk；清單裡只有結果與動作，不列鍵盤提示）。隱私模式的眼睛按鈕開著時是選取語法 (b)。頭像是 `sel` 圓底＋墨色字（深色不是白色實塊）。
- 個股與群組的分頁列：選取語法 (a)；手機放不下時是 ScrollRow。
- 手機：浮動膠囊分頁，選取＝粗體＋圖示後面 52×28 的 `sel` 圓底（深色 #1f2a45）。

### 簽名格 Sign Box（招牌元件）
`apps/web/src/ai/DraftCard.tsx`：76×60px 直角方格、墨色底、內縮 3px 的細框（像表單上的簽名欄），上一行 12px「簽名」、下一行 14px 粗體「確認入帳」。按下後呼叫 `POST /transactions`（`source: "ai_draft"`），格子變成透明底＋墨色框，裡面寫出使用者名字的第一個字（墨色；這不是模型寫的字，依 Two Pens Rule 不用楷體）（墨水由左往右寫出，380ms ease-out），下面一行入帳時間；Sonner 通知附「復原」。

### 草稿卡 Draft Card
紫色淡底＋紫色虛線（簽名後變實線）：標題「買進 元大台灣50 0050」、成交日與帳戶、2×2 鍵值格（股數「2,000 股」、成交價「52.40 元」（美股「182.30 美元」；和股數一樣，單位接在值後面）、手續費、證交稅；股利為總額、二代健保、預扣稅、手續費）、合計（20px 粗體紫）、說明行（沒寫價格／單位、賣超持股）、「怎麼算的 ⌄」（稅費規則）、修改（原地改股數、價格、日期、帳戶）、簽名格。

### AI 面板 AI Panel
`apps/web/src/ai/`（`AiPanel` 桌面、`AiScreen` 手機、`Home` 首頁狀態、`Composer`、`Conversation`）。

- **頭部**：紫色的筆＋「問 AI」（粗體 15px），右邊新對話・紀錄・收合（36px 圖示鈕，`sel-chip`；「紀錄」用 `aria-pressed` 表示打開）。「問 AI」全站只有一個圖示：`AskAiIcon`（`apps/web/src/ai/ask-icon.ts`，lucide `PenLineIcon`）——面板頭部、收合後的窄欄、手機的「問 AI」都用它。
- **還沒有對話（首頁狀態）是安靜的**：沒有問候、沒有說明字樣、建議上面沒有小標。
  - **建議**（最多 3 列，依頁面與資料自動出現；正在發生的事排前面：有待簽名的草稿時第一列是「N 筆草稿等你簽名」（按下打開那份草稿所在的對話），接著是扣款日的「記下今天的 XXXX 定期定額」、補記）：一行一格的格線列，緊接在頭部的格線下，左右延伸到面板邊緣（hover 的淡墨底滿版，文字對齊內文）；墨色 15px（手機 17px），列高 52px（手機 56px），列與列之間 1px 格線；沒有卡片、沒有每列的圖示。是按鈕（鍵盤可操作）。
  - **常用動作**：一行依頁面出現的文字連結，墨色 14px（手機 15px）、鉛筆灰底線（`ctl`，對紙 3.2:1 以上，看得出可以按；滑過變墨色），以「・」分隔。帳本「記一筆交易・匯入對帳單・股利入帳」；個股頁只放這一檔真的能做的事（「記一筆台積電」，有持股時加「股利入帳」；美股用代號「記一筆 AAPL」）；群組、設定、資料來源、紀錄沒有。
  - **輸入框緊接在下面**（16px：捲動區 6px 下內距＋10px，最後一個連結的焦點外框不會被裁掉），不沉到面板底部；下面沒有免責聲明。什麼都沒有的頁面（設定、紀錄）就只有頭部和輸入框。
- **對話狀態**：輸入框固定在底部。
  - 使用者的話靠右，白紙小框、墨色 Noto Sans。
  - **模型寫的話**（`/ai/chat` 串流的回答、`/ai/threads` 載入的回答、拒答）：紫色楷體 17px（手機 18px）、行高 1.8、字距 −0.01em，逐字出現；數字落到 Noto Sans。
  - **規則或範本寫的句子**（草稿前的「我照你說的算好了稅費，簽名後才會入帳。」、定期定額的說明、mock 與離線時的規則版回答）：墨色 Noto Sans 15px（手機 16px），不用紫色、不用楷體。訊息上的 `model` 欄位決定用哪一支筆。
  - 規則版回答的句子用字說漲跌（「上漲 4.83%」「下跌 1.85%」）；▲▼ 與漲跌色只放在後面的數字列（格線清單，金額與百分比都上漲跌色）。可以去的地方是 1px 鉛筆灰框的小按鈕；追問是墨色文字連結（同常用動作）。規則句子只說現在能做什麼，不寫「下一階段開放」這類時程。草稿卡跟在後面。
  - 回答寫完後下方一排「來源」小連結（13px 淡墨標籤；標題＋網域，1px 格線框、↗，滑過看引用原文；網路搜尋的引用一定要顯示）。
  - 串流中末尾一個安靜的紫點（`motion-safe` 才脈動），查資料時旁邊一行淡墨字（「搜尋網路：…」「查看持股…」），寫完就消失。
  - 沒有來源的新聞式句子下方一條鉛筆灰點線，後面接「無來源」細框小字（淡墨，不用紅），按下展開「這段沒有附來源，請自行查證。」
  - 每則回答（模型的回答、規則版回答）下方固定一行 12px 淡墨免責（後端 `done.disclaimer`，模型不自己寫）；草稿說明不加（那是照使用者的指令算的稅費，不是建議）。「資料至 …」13px 淡墨。
  - 額度、連線、「AI 暫時無法使用」等狀況是一行淡墨說明。
- **輸入框下方**：只有提問額度剩 5 題以內、用完或 AI 暫時無法使用時才有一行（13px 墨色）。
- **手機**（全螢幕「問 AI」）：同一套。標題列下一條格線、直向的格線列建議（不是橫滑卡片、沒有 ↗）、同一行文字連結、和桌面同一套的輸入框；輸入代號或名稱時，符合的股票取代建議、列在輸入框上方（見輸入框）。

## Do's and Don'ts

### Do:
- **Do** 讓 AI 的每個動作先成為草稿（紫色虛線），使用者簽名才生效，事後可以復原並標示「由 AI 建立」（紫色 Noto Sans 的固定標籤，不用楷體）。
- **Do** 讓 AI 面板沒事時保持安靜：只有依資料出現的建議（格線列）、一行依頁面出現的文字連結和輸入框；正在發生的事（待簽名的草稿、扣款日、補記）排在前面。
- **Do** 漲跌一律 `--rise`／`--fall`，百分比配 ▲▼、金額配 +／−（見 Price-Only Red Rule），報價依升降單位決定小數位。
- **Do** 隱私模式遮蔽金額與股數、隱藏圖上的均價線與買賣點，保留百分比。
- **Do** 「為什麼」那一行、分頁第一行只在有值得說的事時出現；沒有就不顯示。
- **Do** 每個空狀態說明為什麼沒有、什麼時候會有，並給一個現在能做的動作。商用模式缺資料時照後端 `notes` 原文說明，不用示範資料充數。

### Don't:
- **Don't** 在 AI 以外的地方用紫色，也不要在價格以外的地方用紅綠（營收、法人、刪除都不行）。
- **Don't** 在介面上寫「本頁建議」「依頁面推薦」「AI 摘要」這類說明 AI 機制的字樣；紫色楷體（只在模型寫的字上）就是唯一的 AI 識別。
- **Don't** 放 AI 今日簡報、AI 旁註或市場總覽首頁。
- **Don't** 用卡片包表格、巢狀卡片、陰影區隔一般區塊；用格線。
- **Don't** 用白色實塊表示選取（深色模式尤其），也不要發明第四種選取樣式；用 Selected states 的 (a)(b)(c)。
- **Don't** 把規則或範本產生的句子寫成紫色楷體；楷體只給模型寫的字。草稿前的說明、規則版回答、建議與追問都是墨色 Noto Sans。
- **Don't** 在 AI 面板放固定問候、建議卡片、每列重複的圖示、按鈕方格或「交給 AI」這類小標；也不要在每一頁都放同一組動作（設定、群組沒有常用動作）。
- **Don't** 用交易員記號（「@22.86」）；價格寫成「22.86 元」，和「2,000 股」同一套（值後面接單位）。
- **Don't** 用印章、朱泥、徽記或任何仿實物質感（舊世界已移除）。
- **Don't** 在標題上加 eyebrow／kicker 小標，也不要用 Unicode 符號代替圖示（▲▼ 是資料符號，不是圖示）。
- **Don't** 在頁面標題下面加一句說明（副標）；設定列的說明只留給後果重大的選擇（隱私、分享、授權、刪除、會重算數字的成本方法），其他設定只有標籤與控制項。
- **Don't** 放「之後開放」的佔位列或功能預告清單；還沒有的功能就不出現。
- **Don't** 讓開發用語出現在介面上（「M4 開放」、環境變數、網址參數、「後端」）：寫使用者的話（「之後開放」「伺服器」），或不寫。
