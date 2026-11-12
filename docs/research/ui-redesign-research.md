# UI 重設計研究：導覽結構、AI 的位置、避開「台灣預設」

> 撰寫：2026-11-12（研究子代理）。用途：給協調者整理成約 10 分鐘的討論材料。
> 範圍：只談**結構、導覽、AI 放置與互動模式**，不談視覺風格（色彩、字型、美感由另一個設計流程決定）。
>
> **標示說明**
> - 【事實】官方文件，或多個可靠來源一致的說法。
> - 【單一來源】只有一個來源，或來源是第三方評論、SEO 網站，未能交叉驗證。
> - 【記憶】研究者對舊版介面的印象，這次沒找到文件佐證。
> - 【推論】研究者自己的推論，不是事實。第 4 節全部屬於推論。
> - **（舊）** 表示來源早於 2025 年。
>
> **研究限制**：這個工作環境的 WebFetch 被網路政策擋住（blog.google、9to5google.com 都解析失敗），因此沒有直接打開 Google 部落格、Google Finance 頁面或產品負責人給的 `google.com/finance/beta/...` 連結。下文的 Google 官方說法，是透過搜尋引擎擷取的官方頁面摘要，以及引用這些頁面的媒體報導。需要登入的部分（投資組合、Threads & tasks）沒有實際操作過。如果要逐畫面確認，建議請產品負責人提供目前版本的截圖，或開放這兩個網域。

---

## 0. 一頁摘要（討論用）

1. **Google Finance 的導覽非常少**。舊版的頂層目的地只有 3–4 個（首頁、市場趨勢、投資組合、自選清單），其他內容都從頂部的大搜尋框進入。AI 版（2025-08 開始測試，2026-06-25 正式推出）沒有增加導覽項目，而是讓**搜尋框也能直接提問**，再加上一個**常駐的 Research 面板**。AI 的對話紀錄（Threads）和排程任務（tasks）都收在這個面板裡，不是另外的頁面。Android app 只有 4 個底部分頁：Markets／Lists／History／Ask，其中 2 個給 AI。
2. **2025–2026 年 AI 投資產品常見的 6 種放法**：(1) 搜尋框也能提問；(2) 常駐側欄或下拉式助理；(3) 在數字和圖表旁直接說明「為什麼動」；(4) 主動產生的摘要（整個投資組合，或每一檔）；(5) AI 先準備好草稿，使用者確認後才執行；(6) 用一句話建立排程任務或簡報。
3. **「台灣預設」的核心**：底部分頁是「行情／自選／下單／帳務／更多」，首頁是指數加自選報價表，個股頁有十幾個頁籤，深色看盤畫面，AI 只是掛在角落的一個功能。這種一致性有結構上的原因：約九成券商的看盤 App 都委託同一家廠商（三竹）開發。
4. **Forliosa 的三個 IA 候選**（推論）：A「Google Finance 型」3 個目的地加常駐 AI 面板；B「全域指令列」，AI 不是一個頁面，而是一個到處都在的輸入框；C「AI 簡報當首頁」。三案都把 10 個側欄項目收成 3–4 個目的地；差別在 AI 是放在旁邊、放在上面，還是取代首頁。

---

## 1. Google Finance

### 1.1 時間軸

| 日期 | 事件 | 來源 |
|---|---|---|
| 2020-09 **（舊）** | 舊版改版，以自選清單（watchlists）為中心 | [9to5Google 2020-09-09](https://9to5google.com/2020/09/09/new-google-finance/) |
| 2025-08-08 | 美國開始測試 AI 版：AI 研究問答、進階圖表（K 線、移動平均包絡線）、即時新聞流；可在新舊版之間切換 | [TechCrunch 2025-08-08](https://techcrunch.com/2025/08/08/google-tests-revamped-google-finance-with-ai-upgrades-live-news-feed/)、[Google 部落格](https://blog.google/products/search/google-finance-ai/) |
| 2025-10～11 | 新增 Earnings 分頁：法說會直播音訊、即時逐字稿、AI 重點（"At a glance"） | [SERoundtable](https://www.seroundtable.com/google-finance-ai-update-40372.html)、[Android Authority](https://www.androidauthority.com/google-finance-earnings-feature-3612127) |
| 2025-11-06 | Deep Search（Gemini 同時執行大量搜尋，產出附引用的報告，並列出研究步驟）、預測市場資料（Kalshi／Polymarket）、印度上線 | [Google 部落格](https://blog.google/products-and-platforms/products/search/new-google-finance-ai-deep-search/)、[PYMNTS](https://www.pymnts.com/google/2025/google-finance-rolls-out-ai-driven-deep-search-prediction-market-data/)、[數位時代](https://www.bnext.com.tw/article/85050/google-finance-innovative-features-deep-search-market-predictions) |
| 2026-04-08 | 擴展到 100 多個國家，支援當地語言 | [PPC Land](https://ppc.land/google-finance-ai-tools-reach-100-countries-with-local-language-support/) |
| 2026-05-05 | 圖表加入「key moments」：用 AI 說明某天為什麼漲跌，可以點進來源或接著追問 | [Robby Stein（Google）在 X 上的貼文](https://x.com/rmstein/status/2051716535392350426)（日期由貼文 ID 換算） |
| 2026-06-25 | 正式版推出；投資組合全球開放；新增任務與簡報；推出 Android app；iOS「今年稍晚」 | [Google 部落格](https://blog.google/products-and-platforms/products/search/google-finance-updates-june-2026/)、[TechCrunch](https://techcrunch.com/2026/06/25/google-finance-gets-a-dedicated-app-for-android/)、[PPC Land](https://ppc.land/google-finance-exits-beta-with-portfolios-ai-tasks-and-an-android-app/) |
| 2026-07-23 | 舊版入口消失，AI 版成為唯一版本 | 【單一來源】[Business Finance News](https://businessfinance.news/the-new-google-finance-is-no-longer-optional-inside-googles-ai-first-rebuild-of-the-worlds-most-used-stock-page/)；Google 沒有公告 |
| 截至 2026-11 | 搜尋結果中沒有看到 iOS app 上線 | 未確認 |

### 1.2 舊版（2020 ~ 2026-07）：搜尋框加 3–4 個目的地

- **頂部列**：選單圖示、Logo、置中的大搜尋框（"Search for stocks, ETFs & more"）。搜尋是主要入口。【記憶，搜尋結果的頁面片段也一致】
- **左側導覽（可收合抽屜）**：Home、Market trends、Portfolios、Watchlists。【單一來源：搜尋到的頁面快照】
- **首頁**：右欄是「Your watchlists」，可以從這裡新增自選清單和投資組合（官方說明寫的是「On the right, click New portfolio」）。下方有 Market trends 頁籤（Market indexes、Most active、Gainers、Losers、Climate leaders、Crypto、Currencies）、"Most followed on Google"、財報行事曆、新聞。【事實：[Google 說明：投資組合](https://support.google.com/websearch/answer/11330383?hl=en)、[Google 說明：追蹤證券](https://support.google.com/finance/answer/71893)】
- **個股頁**：只有一頁，往下捲：報價、走勢圖（1D／5D／1M／6M／YTD／1Y／5Y／Max）、關鍵數據放右欄、新聞、財報（季／年）、公司簡介。印象中沒有頁籤。【記憶】
- **要點**：頂層目的地很少。投資組合和自選清單在首頁右欄就看得到，不需要另一個頁面。

### 1.3 AI 版（2025-08 測試 → 2026-06 正式）：AI 放在三個位置，導覽沒有變多

| AI 位置 | 具體內容 | 驗證程度 |
|---|---|---|
| **① 搜尋框也能提問** | 頂部搜尋框原本只能找股票，現在也可以輸入金融問題。搜尋框下方可以選 **Deep Search**，產生詳細研究報告 | 【事實】[Google 說明 16490185](https://support.google.com/websearch/answer/16490185?hl=en)；[Android Authority 實測](https://www.androidauthority.com/google-finance-ai-page-testing-usa-3592257/)（2025-08） |
| **② 常駐 Research 面板** | 實測者在**右側**看到 Research 區塊：今日市場摘要和引用網站清單，回答時來源也列在右邊。面板右上角有 **Threads & tasks**（研究紀錄和排程任務），可以從面板「Create a task」；任務完成的通知會出現在面板裡 | 【事實】說明頁；位置描述屬【單一來源】（Android Authority） |
| **③ 依情境進入** | 頁面上的「Dive deeper on this topic with AI」會打開 Research 面板；圖表上的 **key moments** 說明某天的漲跌原因，可以接著追問；個股 Overview 分頁有 AI 寫的近期表現與市場情緒摘要 | 【事實】說明頁、Robby Stein 貼文 |
| **④ AI 負責建立投資組合** | 投資組合可以上傳 CSV、PDF、券商截圖，或直接用文字描述來建立（說明頁範例："Create a new portfolio and add 50 shares of GOOG and 100 shares of SPY"）；研究工具會把自選或持股當作背景 | 【事實】多家媒體引用 Google 部落格與說明頁：[TheNextWeb](https://thenextweb.com/news/google-finance-android-app-portfolios-ai-research-tool)、[PPC Land](https://ppc.land/google-finance-exits-beta-with-portfolios-ai-tasks-and-an-android-app/) |
| **⑤ 排程任務與簡報** | 用一句話建立重複執行的任務，例如每天盤前簡報、每週一追蹤 IPO，結果送到 app 或 Research 面板 | 【事實】說明頁；任務與 Deep Search 目前只在網頁版 |

- **目的地數量**：網頁版的導覽沒有因為 AI 而增加。AI 的歷史紀錄和任務都收在面板裡。【事實，依據同上】
- **評價**：有評論說桌面版 AI 面板一直佔畫面約三分之一，而且無法收起；新版投資組合拿掉了交易明細與排序；也有 Change.org 請願要求恢復舊版。【單一來源／偏主觀：[classicviewfinance](https://classicviewfinance.com/new-google-finance-review)、[Folivue](https://folivue.com/new-google-finance)、[請願](https://www.change.org/p/restore-the-classic-version-of-google-finance)】
  → 【推論】Google 的投資組合偏輕量，**「正確的台股帳本」仍然是 Forliosa 可以和它做出差異的地方**；常駐 AI 面板一定要能收起。
- **免責聲明**：AI 摘要標示「可能有錯，不是買賣建議」。【單一來源，引用自評論】

### 1.4 第一屏內容

- **首頁（AI 版）**：頂部是搜尋兼提問框（下方有 Deep Search），主區是市場概況、走勢圖、即時新聞流，右側是 Research（今日市場摘要和來源）。Search Engine Journal 把頁面歸納成三塊：Research、圖表工具、即時數據與新聞。【單一來源組合：[Android Authority](https://www.androidauthority.com/google-finance-ai-page-testing-usa-3592257/)、[SEJ](https://www.searchenginejournal.com/google-is-testing-an-ai-powered-finance-page/553333/)，都是 2025-08 的版本，正式版可能已改】
- **個股頁（AI 版）**：頂部是價格、漲跌、圖表（含 key moments 標記），Overview 分頁有 AI 摘要，另有 Earnings 等分頁。【事實：Overview 與 Earnings 分頁；其他分頁名稱（Chart、News）屬單一來源】

### 1.5 手機

- **Android app（2026-06）**：4 個底部分頁 **Markets／Lists／History／Ask**。Lists 放自選清單和投資組合，History 是過去的 AI 對話，Ask 是 AI 對話。【單一來源：[Talk Android](https://www.talkandroid.com/527422-google-finance-android-app/)；另一篇寫成 Watchlist／Smart Portfolios／News／Markets，兩者矛盾】上線時 app 還沒有投資組合、任務和通知，說是之後補上。【事實：多家報導引用說明頁】
- **手機網頁版**：沒找到可靠的描述。iOS 使用者目前只能用手機網頁版。【單一來源】
- 【推論】手機 app 的 4 個分頁裡有 2 個給 AI（Ask、History），代表 Google 在手機上把 AI 提升到頂層，在桌面則放在側邊面板。

---

## 2. AI-first 投資產品：AI 放在資訊架構的哪裡（2025–2026）

| # | 模式 | 例子（含來源、日期） | 對 Forliosa 的意義（推論） |
|---|---|---|---|
| P1 | **搜尋框也能提問**：同一個輸入框可以輸入代號，也可以輸入問題 | Google Finance 搜尋框（2025-08 起，見 1.3）；Yahoo Scout 的介面就是一個搜尋列，2026-06 引進 Yahoo Finance（[Axios 2026-01-27](https://www.axios.com/2026/01/27/yahoo-scout-ai-search-launch)、[Axios 2026-06-03](https://axios.com/2026/06/03/yahoo-scout-ai-sports-finance)）；Perplexity Finance 的個股頁頂部是搜尋列，回答附引用（[Techpoint 評測](https://techpoint.africa/guide/perplexity-finance-review/)，單一來源） | 現有的 ⌘K 搜尋可以直接升級成「搜尋、提問、下指令」三用 |
| P2 | **常駐助理面板／下拉喚出** | Google Finance 的 Research 面板；Revolut AIR 在首頁**往下滑**就能叫出，可以查支出、追蹤投資、凍結卡片（2026-04-09，[Revolut 官方](https://www.revolut.com/news/revolut_enters_new_era_of_money_intelligence_with_launch_of_ai_assistant/)、[IT Brief](https://itbrief.co.uk/story/revolut-launches-ai-assistant-as-banks-shift-to-chat)）；Public 的 Alpha 在 app 個股頁往下滑、網頁版滑過價格圖就會出現（[Public 說明](https://help.public.com/en/articles/9354354-what-is-alpha)；Alpha 2023 年推出 **（舊）**） | 桌面用側欄，手機用底部抽屜（bottom sheet）或下滑手勢；面板要能收起 |
| P3 | **在數字和圖表旁直接說明「為什麼」** | Google 的 key moments（2026-05）；Public 在價格圖上嵌入 AI 寫的漲跌原因（同上說明頁）；Robinhood Cortex Digests 放在個股頁（[Robinhood 說明](https://robinhood.com/us/en/support/articles/cortex-digests)、[英國上線 2025-08-19](https://robinhood.com/us/en/newsroom/digests-by-robinhood-cortex-uk)） | 今日損益、「今天誰影響最大」、河流圖現在的位置，都很適合加「為什麼？」 |
| P4 | **主動摘要（投資組合／每一檔）** | Robinhood 2025-12-16 宣布投資組合層級的 Digests，並說 Cortex 會「嵌入整個 app」（[Robinhood YES/NO 發表會](https://robinhood.com/newsroom/robinhood-presents-yes-no-event/)）；eToro 2026-07-07 重寫 app，以會主動推送的 Tori 為核心（持股更新、市場訊號、漲跌原因），也能在 WhatsApp、Apple Watch 使用（[eToro 新聞稿](https://www.etoro.com/news-and-analysis/press-releases/etoro-launches-new-app-ai-first-smart-and-social/)、[FinTech Global](https://fintech.global/2026/07/08/etoro-unveils-ai-first-app-with-proactive-agent-tori/)）；Yahoo 股市 2026-06 為 VIP 推出「AI 自選股摘要」，依高、中、低影響分類（[工商時報](https://www.ctee.com.tw/news/20260610701300-430503)、[旺得富](https://wantrich.chinatimes.com/news/20260609900739-420101)） | 對應 spec 已有的「AI 今日重點」和「盤後報告」；問題在於它是首頁的一張卡，還是首頁本身（見候選 C） |
| P5 | **AI 先準備草稿，使用者確認後才執行** | Robinhood Cortex Assistant 遇到下單需求時，會帶出**預先填好的委託單或確認畫面**，不會自己下單（[Cortex 揭露文件](https://cdn.robinhood.com/assets/robinhood/legal/cortex_assistant_disclosure.pdf)、[說明頁](https://robinhood.com/us/en/support/articles/cortex/)）；Google Finance 用截圖或文字建立投資組合；Revolut AIR 的敏感動作要生物辨識（單一來源）。**反例**：Public Agents（2026-03-31）和 Robinhood Agentic Trading（2026-05-27）只在設定時授權一次，之後**不會逐筆確認**（[Public 條款摘要](https://public.com/disclosures/agenticterms)、[TheNextWeb](https://thenextweb.com/news/robinhood-is-letting-ai-agents-trade-stocks-and-spend-money-on-your-credit-card)） | Forliosa 不下單，AI 能做的事是寫入帳本（記交易、匯入、設警示）。適合用「草稿卡、確認、可撤銷」，不適合全自動 |
| P6 | **用一句話建立排程任務** | Google Finance tasks（「Track new IPOs and notify me each Monday」，2026-06）；富邦「AI PRO」每天由 AI 主播播報盤前焦點（[經濟日報](https://money.udn.com/money/amp/story/5607/9174543)，2025-12） | 盤後報告、到價警示、每週健檢都可以合成同一種「任務」 |
| P7 | **對話是一個分頁，另有歷史紀錄** | Google Finance Android 的 Ask 和 History 分頁；Robinhood Cortex 右上角有歷史圖示，對話閒置 2 小時後存檔，紀錄可看 30 天；Revolut AIR 所有對話都在**同一條**長串裡，有 UX 顧問批評這樣使用者看不到其他功能（[Craft Innovations](https://craftinnovations.global/revolut-air-ux-analysis/)，業者行銷文） | 如果有「AI 紀錄」，報告、對話、任務可以放在同一個地方 |

**來源、時間與免責的常見做法**【事實，取自上表來源】
- Google Deep Search 會列出報告是怎麼查出來的（研究步驟和引用）。Fiscal.ai（原 FinChat，2025-06 改名）每個回答都附引用（[WallStreetZen 評測](https://www.wallstreetzen.com/blog/finchat-io-fiscal-ai-review/)）。
- Robinhood Digests 公開說明方法和涵蓋範圍（[methodology](https://robinhood.com/us/en/support/articles/cortex-digests-methodology)）。
- 免責都很簡短，放在答案附近。eToro 和 Public 都在產品敘述裡明說「不是投資建議」。

**手動和 AI 並存**【推論，依據上述產品】：沒有一家把手動入口拿掉。AI 是比較快的路，手動頁面還在；用 AI 做的動作，最後還是落在原本的手動介面上（例如委託單、投資組合頁）。

---

## 3. 「台灣預設」：台股 App 的共通樣貌

**已查證的資料**
- **外包同源**：三竹替約 47 家券商、約 91% 業者開發和維運手機看盤 App（[股感](https://www.stockfeel.com.tw/看盤軟體-電腦看盤軟體-看盤app/)，數字約為 2020 年 **（舊）**；2021 年報導寫市占 90.57%，[科技新報](https://finance.technews.tw/2021/09/27/mitake-app/) **（舊）**）。→ 結構高度一致是產業結構造成的。
- **券商 App 的骨架**：玉山證券 App 手冊的章節是「首頁、行情、自選、下單」，加上獨立的「帳務」（帳務總覽、庫存明細、交割金額）（[玉山手冊 PDF](https://www.esunsec.com.tw/-/media/EsunSec/Files/Trade-Platforms/Esunsec-App-guide_v2.pdf)，沒有日期，可能是舊版）。台新 PhoneEZ 的帳務是委託回報、成交回報、庫存、未實現損益（App Store 頁面）。
- **個股頁頁籤很多**：Yahoo 股市個股頁的選單有走勢圖、技術分析、成交彙整、籌碼（法人、主力、資券、大戶）、估價（本益比與股價淨值比河流圖）、股利、財務、基本、同業比較、健診、行事曆、新聞（[tw.stock.yahoo.com 頁面選單](https://tw.stock.yahoo.com/quote/2330.TW/news)）。財報狗的個股分析也是一長串選單（[財報狗](https://statementdog.com/analysis/1707/pe)）。
- **密度太高，開始分版本**：元大「投資先生」2026-07 推出「簡易版」，可以一鍵切換回專業版（[中央社](https://www.cna.com.tw/business/chinese/439195)）。富果的特色是可以自己決定要顯示哪些卡片（[數位時代](https://www.bnext.com.tw/article/78847/fugle-digital-transformation)），下單要按中間的按鈕進入交易頁（[富果客服](https://support.fugle.tw/?p=6739)）。
- **AI 是加上去的「功能」**：群益「AI 問問」輸入代號就能看重點（2025-09，[科技新報](https://finance.technews.tw/2025/09/18/ai-qa/)）；富邦「AI PRO」有 AI 投資助理、法說會重點、AI 主播（2025-12）；Yahoo 股市有 AI 自選股摘要（VIP）和 AI 事件整理（2026-06）。各家券商普遍內建「AI 選股」。→ 光是「有 AI」已經不算差異，**AI 放在哪裡、能替使用者做什麼**才是。
- **社群是公開討論**：CMoney 股市爆料同學會的社團、P 幣、徽章；Yahoo 股市 2025-05 推出個股漲跌投票、多空指標、ETF 篩選器（[yam](https://n.yam.com/Article/20250516645160)）。

**「台灣預設」清單**（以下合併事實與【觀察】；分頁名稱沒有逐一驗證）
1. 底部 4–5 個分頁，以**行情、自選、下單、帳務、我的／更多**為骨幹；中間按鈕常是「下單」。
2. 首頁是**大盤指數加自選報價表**（代號、名稱、成交價、漲跌、漲跌幅、成交量）；以市場為中心，不是以「我的錢」為中心。【觀察】
3. 個股頁頂部是報價，下面是**一排 8–12 個頁籤**，每個頁籤是一張表或一張圖。
4. 紅漲綠跌、▲▼、萬／億、深色看盤主題。【慣例／觀察】
5. 「帳務」只看單一券商的庫存和未實現損益，不含股利、不跨券商（對照 PRODUCT.md 的定位）。
6. 用「多頁籤、多表格」來達成高密度；覺得太複雜時，就另外做「簡易版」。
7. AI 是某一頁裡的一個按鈕或一張卡（AI 選股、AI 摘要），不是頂層。
8. 社群是公開的論壇、社團或投票，不是熟人之間的私人比較。
9. 介面上常有開戶、活動、VIP 付費牆。【觀察】

---

## 4. 對 Forliosa 的意涵（**本節全部是推論**）

### 4.1 前提

- 產品負責人想要的三件事：減少頂層分頁（參考 Google Finance）、AI 放在最上層、和台灣預設有明顯差異但維持高密度。
- Forliosa 有一個天生的差異：**不下單**。台灣預設裡最重要的「下單」分頁，在 Forliosa 不存在，這個位置可以讓給 AI。
- 現在的 10 個項目可以照「名詞」和「動詞」分成兩類：
  - **名詞（地方）**：總覽、持股、自選、績效、群組、個股頁。
  - **動詞（動作）**：交易（記一筆）、匯入、AI 助理、報告（AI 的產出）、設定。
  - 動詞適合交給 AI 加上全域動作入口，名詞才需要導覽位置。

### 4.2 三個候選 IA

#### 候選 A：「Google Finance 型」3 個目的地加常駐 AI 面板

| | 內容 |
|---|---|
| 頂層 | **首頁**（今天）／**我的投資**（頁籤：持股、交易、績效、配置）／**群組**。自選放在首頁右欄，加上「我的投資」裡的清單，和 Google 的「Your lists」一樣 |
| AI 入口 | 頂部搜尋框也能提問；桌面右側有**可收合**的 AI 面板，面板內有「對話／報告／任務」三個分頁（原本的「報告」併進這裡）；個股頁和持股列上有「問 AI」，會自動帶入目前的標的 |
| 動作 | 頂部有「記一筆」，下拉選單可選手動輸入或匯入對帳單；也可以把檔案拖到 AI 面板 |
| 設定 | 頭像選單（隱私模式、紅綠、張／股、帳戶） |
| 手機 | 底部 4 個分頁：首頁／我的投資／**AI**（置中）／群組；頂部放搜尋；AI 用底部抽屜（Vaul，可停在半開或全開） |
| 優點 | 最接近產品負責人給的參考，學習成本低；手動路徑清楚；左側欄可以拿掉 |
| 缺點 | AI 還是在「旁邊」，不算真正的最上層；右面板會吃掉寬度（Google 被批評的就是這點）；「我的投資」有 4 個頁籤，層級變深；和 Google 很像，等於換了一個參考對象 |

#### 候選 B：「全域指令列」：AI 不是一個頁面，而是一個到處都在的輸入框

| | 內容 |
|---|---|
| 頂層 | **今天**／**投資組合**（持股、交易、績效）／**研究**（自選加個股頁）／**群組**，共 4 個 |
| AI 入口 | 一條**常駐的「搜尋・提問・指令」列**。桌面放在頂部中央（⌘K 叫出），手機固定在底部分頁列正上方，像訊息輸入框。輸入代號就跳到個股頁；輸入問句時，答案用**卡片直接顯示在目前頁面**（例如在持股頁問「哪檔拖累最多」，卡片就釘在表格上方），要展開才進入完整對話 |
| 動作 | 「買 0050 2 張 185」會產生**交易草稿卡**，預估好稅費，按確認才入帳；丟入 CSV、PDF 或截圖會出現**匯入預覽**；「2330 跌破 2,000 提醒我」會產生**警示草稿**。每一個動作都還有手動入口 |
| 報告 | 收進輸入框旁邊的「AI 紀錄」（對話、報告、任務），不佔導覽位置 |
| 手機 | 底部 4 個分頁加上固定在上方的輸入框；個股頁輸入框會自動帶入該檔標的 |
| 優點 | AI 真正在最上層，而且每一頁都用同一套方式；**和台灣預設差異最大**（台灣沒有以輸入框為主的看盤工具）；適合鍵盤使用者；把 spec 原本的 ⌘K 自然升級 |
| 缺點 | 意圖判斷（代號、問句、指令）要做得好，判斷錯會傷信任；手機上輸入框加分頁列會吃掉垂直空間；M4 之前 AI 還沒做好，輸入框要先只做「搜尋加指令」，之後再加問答；常駐輸入框會鼓勵使用，要先設計好額度提示 |

#### 候選 C：「AI 簡報當首頁」：首頁是一份每天更新的簡報

| | 內容 |
|---|---|
| 頂層 | **簡報**（首頁）／**投資組合**／**研究**／**群組** |
| 首頁 | 頂部仍然是總資產和今日損益（守住 PRODUCT.md「一眼看懂今天」原則）；下面是 AI 寫的**今日簡報**：「今天誰影響最大，為什麼」、法人動向、即將除權息、觸發的警示、**待你確認的事**（例如 AI 在對帳單裡找到 2 筆差異）。每段都夾著即時數字和小圖，並附「問更多」和「開啟持股」 |
| AI 入口 | 簡報本身就是 AI 的輸出；在簡報底下接著問，就是對話；其他頁面用 B 案的輸入框或 A 案的面板 |
| 手機 | 最適合「盤中、收盤後快速看一眼」：打開就是今天的簡報 |
| 優點 | 和台灣預設（指數加報價表）、Google Finance（市場加新聞）都明顯不同；最符合「AI 在最上層」；家人朋友一看就懂 |
| 缺點 | M4 前沒有 AI，需要不靠 AI、用規則產生的簡報當替代；每人每天都要產生內容，有成本（可以和盤後報告共用批次與快取）；容易變成新聞動態，密度下降；整份由 AI 寫，信任與免責壓力最大 |

#### 三案的項目對照

| 現有項目 | A | B | C |
|---|---|---|---|
| 總覽 | 首頁 | 今天 | 簡報 |
| 持股／績效 | 我的投資（頁籤） | 投資組合 | 投資組合 |
| 交易 | 我的投資頁籤加「記一筆」 | 指令加草稿卡，或手動 | 同 B |
| 自選 | 首頁右欄加清單 | 研究 | 研究 |
| AI 助理 | 右側面板／手機 AI 分頁 | 全域輸入框 | 首頁加輸入框 |
| 報告 | AI 面板的「報告」分頁 | AI 紀錄 | 簡報封存加 AI 紀錄 |
| 群組 | 頂層 | 頂層 | 頂層 |
| 匯入 | 記一筆選單／拖進 AI 面板 | 把檔案丟進輸入框 | 同 B |
| 設定 | 頭像選單 | 頭像選單 | 頭像選單 |

> 三案可以組合。一個可以討論的方向：B 的全域輸入框，加上 C 的首頁簡報段落，再加上 A 的「可收合面板」，用來看長對話和深度報告。

### 4.3 不分方案都適用的互動原則

1. **一個輸入框，三種用途**：搜尋（代號、中文名）、提問、指令。拖入檔案就進入匯入流程。Google 用截圖或文字建立投資組合，證明這條路行得通。
2. **AI 動作一律是「草稿、確認、可撤銷」**：交易、匯入、警示由 AI 建立時，先產生預填好的卡片（含預估稅費和資料日期），使用者按確認才寫入；之後在交易列表標示「由 AI 建立」，並能一鍵復原。**分享與群組設定不讓 AI 代改**，只能帶使用者到設定畫面，以符合 spec 硬性原則第 6 條。
3. **數字旁邊的「為什麼？」**：今日損益、每一檔今天的影響、河流圖現在的位置、績效和 0050 的差距，都可以點開看 AI 解釋，類似 Google key moments 和 Robinhood Digests。圖上的異常日可以加標記。
4. **每張 AI 卡片都有出處**：資料時間（例如 11/11 13:30 收盤）、用了哪些資料（持股、FinMind 法人資料…），可以展開「怎麼算的」；免責一行，放在卡片底部。
5. **任務統一**：盤後報告、到價警示、每週健檢、群組週報都是「任務」，可以用一句話建立，也可以手動設定；結果送到 AI 紀錄和 Telegram／Discord。
6. **手動永遠找得到**：每個 AI 能做的事都有手動入口；AI 額度用完或模型拒答時，介面要能完全退回手動。

### 4.4 怎麼維持高密度，又不像台灣預設（只談結構）

- **以「我的錢」為中心，不以「行情表」為中心**：首頁第一屏是我的損益和原因，不是大盤加自選報價表。
- **用「數字加一句話」做出密度**：表格上方放一句 AI 結論（例如「今天 +2.84%，七成來自台積電」），欄位設計成能回答問題，而不是一直加頁籤。
- **個股頁減少頁籤**：可以考慮舊版 Google Finance 的「單頁捲動加段落索引」，或把頁籤收成 4 個左右（概覽／估值／財務與籌碼／我在這檔），頂部放 AI 摘要；台灣預設是 8–12 個頁籤。
- **桌面以鍵盤操作為主**：⌘K、表格上下移動、快速鍵記一筆。台灣看盤網頁很少這樣做。【觀察】
- **社群做成私人圈子**：群組是熟人之間、可控制分享範圍的比較，不是公開的論壇或投票。這本身就是差異，所以群組值得保留為頂層目的地。

### 4.5 建議帶到討論的問題

1. AI 的位置要選「旁邊」（A）、「上面」（B），還是「取代首頁」（C）？
2. 手機要給 AI 一個底部分頁（A，類似 Google Android），還是一條固定在上方的輸入框（B）？
3. 自選是不是頂層？要獨立成「研究」，還是像 Google 一樣放在首頁右欄？
4. 個股頁要維持 Yahoo 式的多頁籤，還是改成單頁捲動加 AI 摘要？
5. M4 之前 AI 沒有內容時，A、B、C 各自要怎麼降級？（B 先只做搜尋加指令，C 需要規則產生的簡報。）
6. AI 能不能直接寫入帳本？建議只能透過草稿卡確認後寫入，需要產品負責人拍板。

---

## 5. 來源日期速查（不含已在上文標示的項目）

- 早於 2025 年 **（舊）**：9to5Google 2020-09（Google Finance 舊版改版）、Public Alpha（2023 推出）、三竹市占（約 2020／2021）、玉山 App 手冊（沒有日期）、富果卡片式介面（數位時代，日期不明）。
- 2025：TechCrunch／Android Authority／SEJ（2025-08）、Google Deep Search（2025-11-06）、Robinhood Cortex（2025-03 宣布；Digests 英國 2025-08-19；HOOD Summit 2025-09-10；YES/NO 2025-12-16）、Public Generated Assets（2025-05-14，[Finance Magnates](https://www.financemagnates.com/forex/public-debuts-ai-powered-index-generator-benchmarking-sp-500/)）、Fiscal.ai 改名（2025-06）、群益 AI 問問（2025-09-18）、富邦 AI PRO（2025-11～12）、Yahoo 股市新功能（2025-05）。
- 2026：Yahoo Scout（01-27）、Public Agents（03-31，[AI News](https://www.ainews.com/p/public-com-launches-ai-investing-agents-bringing-agentic-trading-to-retail-investor)）、Perplexity Portfolio（約 03，[Plaid 部落格](https://plaid.com/blog/powering-intellligent-finance-with-perplexity/)）、Revolut AIR（04-09）、Google 擴展 100 國（04-08）、Google key moments（05-05）、Robinhood Agentic Trading（05-27，[The Block](https://www.theblock.co/post/402729/robinhood-ai-powered-crypto-trading-launching-agentic-stock-trading-beta)）、Yahoo Finance 引進 Scout（06-03）、Yahoo 股市 AI 自選股摘要（06-09）、Google Finance 正式版與 Android app（06-25）、eToro 新 app（07-07）、元大簡易版（07）、Google 舊版下架（07-23，單一來源）。
- 沒有日期的官方說明頁（2026-11 透過搜尋讀取）：Google 說明 [16490185](https://support.google.com/websearch/answer/16490185?hl=en)、[11330383](https://support.google.com/websearch/answer/11330383?hl=en)；Robinhood [Cortex](https://robinhood.com/us/en/support/articles/cortex/)；Public [Alpha](https://help.public.com/en/articles/9354354-what-is-alpha)。
