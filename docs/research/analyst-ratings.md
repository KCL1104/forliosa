# 法人評級與目標價：能不能合法取得、顯示？

> 撰寫：2026-11-12（研究子代理）。問題：Forliosa 能不能在個股頁顯示國內外機構對台股（上市／上櫃）與美股的**評級與目標價**，前提是產品負責人的決定「只用可合法商用的資料」，而且 App 以後可能公開、收費。
>
> **這不是法律意見。** 第 4、6 節的法律整理只是研究摘要。公開收費前，請律師看過「新聞衍生資料」和「投顧法」兩部分。
>
> **標示**（和 `data-sources-licensing.md` 相同）
> - 【事實】這次直接讀到原文，或是本 repo 的程式碼。
> - 【單一來源】只有搜尋引擎摘要或單一第三方來源，原文沒有打開。
> - 【記憶】研究者的印象或法條記憶，這次沒有核對原文。
> - 【推論】研究者自己的判斷。
>
> **研究限制**（請先看）
> - 這次只直接讀到**證交所與櫃買的 OpenAPI swagger**（2026-11-12 用 curl 下載）。WebFetch 試過的外部網站全部無法解析：`www.tej.com.tw`、`www.tejwin.com`、`finnhub.io`、`mcp.tipranks.com`、`www.lib.nccu.edu.tw`。curl 被代理拒絕的有：`twse-regulation.twse.com.tw`、`unpkg.com`、`site.financialmodelingprep.com`、`finnhubio.github.io`。證交所 `staticFiles` 的函文頁回「網站維護中」。
> - 所以，除非另外標示，各家**資料商的條款與價格都只來自搜尋摘要**（【單一來源】）。上線或簽約前，每一項都要讀原文或向業者確認。
> - 相關文件：[`data-sources-licensing.md`](./data-sources-licensing.md)（§4 爬蟲與網站條款、§4.2 台灣法律考量）、[`claude-platform-fit.md`](./claude-platform-fit.md)（網頁搜尋必須顯示引用）、[`stock-page-research.md`](./stock-page-research.md)（「EPS 對分析師預估」列為 C 級、「研究報告（券商）」列為 D 級）。

---

## 0. 一頁結論

1. **官方來源都沒有評級、目標價或共識預估，台美皆然。**
   - 證交所 OpenAPI 143 個端點、櫃買 OpenAPI 225 個端點，沒有一個是分析師評等、目標價或共識預估【事實】。
   - 官方最接近的是公開資訊觀測站的「券商對媒體轉載澄清或說明」：券商在這裡澄清媒體轉載它的研究報告【單一來源】。
   - SEC EDGAR 只有公司自己的財報與財測（8-K Item 2.02／7.01），沒有任何評級【單一來源】。
2. **台股的評級與目標價只有商業來源**，而且沒有一家公開「App 對外顯示」的授權價格：
   - 台灣資料商：TEJ（有「券商預測」類資料）、CMoney（籌碼K線「法人目標價」）、鉅亨（「鉅亨速報－FactSet 最新調查」系列，以及外資評等頁）、嘉實 XQ／MoneyDJ。
   - 國際資料商：FactSet、LSEG I/B/E/S、S&P Capital IQ、Bloomberg、Visible Alpha。
   - 每一家都要**詢價、簽對外顯示（display／redistribution）授權**【單一來源＋推論】。
3. **美股 API 的平價方案幾乎都只限個人使用，「顯示給 App 的其他使用者」要另簽商用授權。**
   - Finnhub：免費與自助方案只限個人；商用要談 Enterprise【單一來源】。
   - FMP（含 TipRanks 資料）：顯示或轉發要簽「Data Display and Licensing Agreement」，即使是免費公開網站也算顯示【單一來源：FMP 官方頁】。
   - Massive（前 Polygon）＋Benzinga：Individual 方案明說不能用在 App；商用要 Business 方案【單一來源：Massive 知識庫】。
   - TipRanks API：禁止再散布、再發布、轉授權【單一來源】。
   - Alpha Vantage：個人、非商業【單一來源】。
   - Tiingo：沒有分析師資料。Yahoo：不可用。
4. **新聞衍生的「某券商調升某股目標價至 X 元」，比較安全的做法是即時查詢＋附引用，不建資料庫。**
   - 單一事實（機構、評等、目標價、日期）本身通常不受著作權保護。美國也有判例：據實報導券商的評等調整，「熱門新聞」主張被著作權法排除（*Barclays v. Theflyonthewall.com*，2d Cir. 2011）【單一來源】。
   - 但有三個風險：
     - 網站條款禁止爬取。
     - 有系統地搬運別人整理好的資料，可能構成公平法第 25 條的「搭便車」。
     - 2014 年起，台灣規定券商報告要標「非經同意不得轉載」，券商同意媒體轉載時，內容也**不得含目標價**。也就是說，媒體報導的目標價通常**沒有得到券商同意**【單一來源】。
   - **最安全的模式**：
     - 使用者按下按鈕，AI 才用網頁搜尋找近期報導。
     - 每筆附來源連結與日期，用自己的話寫一句。
     - 只做同一檔、同一天的短期快取，不累積成歷史資料庫。
     - 不算共識數字，不做「上漲空間排行」。
5. **使用者自己券商的研究報告只能本人看**。不能轉給其他使用者，也不能拿來做共用摘要【推論＋各券商聲明【單一來源】】。
6. **投顧法的風險在「Forliosa 自己推介」，不在「標示出處地引用別人的看法」。**
   - 投信投顧法第 4 條：收取報酬並「提供分析意見或推介建議」，就是證券投資顧問；未經許可經營，依第 107 條最重 5 年【單一來源】。
   - Forliosa 收費後，如果把法人目標價做成「建議買進」「上漲空間排行」「看多 x 家」，就接近推介。
   - 只並列各家看法並標明出處，風險較低，但仍要在收費前請律師確認【推論】。
7. **建議**：
   - **現在**：不買資料。個股頁做一張「法人觀點」卡，AI 依使用者需要即時查詢，附引用、標日期，標明是第三方意見，不彙總成共識數字。估計每月 US$25–100（家人朋友）到 US$400–1,500（公開、每天約 300 檔）【推論】。
   - **之後**：要做「共識目標價」「評級變動時間軸」「EPS 對預估」時，再向 TEJ、CMoney、鉅亨（FactSet）詢價台股授權；美股買 Benzinga（經 Massive Business 或直簽）或 FMP 顯示授權。

---

## 1. 問題 1：官方或開放來源

### 1.1 台灣

| 來源 | 有沒有評級、目標價、共識預估 | 相鄰的資料 | 標示 |
|---|---|---|---|
| **證交所 OpenAPI**（[swagger](https://openapi.twse.com.tw/v1/swagger.json)，143 端點） | **沒有**。用「目標、評等、評級、預估、分析師、研究、法說、共識、預測、券商、投顧」搜尋 summary／description，只找到券商基本資料、人數、月計表，以及下面兩項 | `t187ap14_L`「上市公司各產業 EPS 統計資訊」（實際數）；`t187ap16_L`「當季綜合損益經會計師查核（核閱）數與當季預測數差異達 10% 以上者」（**公司自己的財務預測**，不是分析師的） | 【事實】2026-11-12 下載並以程式檢索 |
| **櫃買 OpenAPI**（[swagger](https://www.tpex.org.tw/openapi/swagger.json)，225 端點） | **沒有** | `tpex_esb_recommended_dealer`「興櫃推薦證券商與推薦之股票」：這是興櫃掛牌制度的推薦券商，**不是投資評等**；`tpex_esb_eps_rank`（興櫃 EPS 排名，實際數） | 【事實】同上；「推薦證券商不是評等」是【推論】 |
| **公開資訊觀測站：法說會** | 沒有評等。法說會資料是公司自己的簡報與說明；公司公告常寫「請至公開資訊觀測站法人說明會一覽表查閱」 | 公司財測、營運展望（著作權屬公司，見 `stock-page-research.md`） | 【單一來源：[Yahoo 轉載的公司公告](https://tw.stock.yahoo.com/news/%E5%A4%A7%E6%8B%93-ky-12-16%E5%8F%83%E5%8A%A0%E5%BA%B7%E5%92%8C%E8%AD%89%E5%88%B8%E8%88%89%E8%BE%A6%E4%B9%8B%E7%B7%9A%E4%B8%8A%E6%B3%95%E8%AA%AA%E6%9C%83-074900576.html)】＋【推論】 |
| **公開資訊觀測站：「券商對媒體轉載之澄清或說明」** | 不是評等資料，是**券商澄清媒體轉載**的申報專區。證交所 103-09-18 臺證輔字第 1030019044 號函：為「提升證券商澄清其研究報告經轉載之相關內容機制之功效」，把澄清平台從券商公會網站移到公開資訊觀測站，103-09-19 起實施；券商登入申報系統，在「券商對媒體轉載之澄清或說明申報作業」輸入個股代碼與內容 | 可以連結過去，讓使用者看某則媒體目標價是否被券商澄清 | 【單一來源：[證交所函](https://www.twse.com.tw/staticFiles/marketAnnounce/setAnnounce/1030019044.htm) 搜尋摘要；這次開啟只得到「網站維護中」】 |
| **政府資料開放平臺**（data.gov.tw） | 搜尋「分析師、目標價、投資評等、盈餘預估」沒有相關資料集；學術研究用的分析師資料都取自商業平台 | — | 【單一來源：搜尋摘要】 |
| **投信投顧公會（SITCA）** | 沒找到評等或目標價資料。公會有《證券投資顧問事業從事廣告及營業活動行為規範》，只約束**持牌投顧** | — | 【單一來源：[SITCA 規範檔](https://www.sitca.org.tw/opf/i0000/files/%E7%9B%B8%E9%97%9C%E6%B3%95%E8%A6%8F/%E7%9B%B8%E9%97%9C%E5%AD%90%E6%B3%95/%E5%85%AC%E6%9C%83%E8%A6%8F%E7%AF%84/%E5%85%AC%E6%9C%83%E8%A6%8F%E7%AF%84%E6%AA%94/48-1.%E6%8A%95%E9%A1%A7%E5%BB%A3%E5%91%8A%E8%A1%8C%E7%82%BA%E8%A6%8F%E7%AF%84(94.03.28).doc)（94-03-28 版）搜尋摘要】 |
| **金管會證期局** | 只有法令函釋與新聞稿，沒有評等資料 | — | 【推論】 |
| **證交所「前瞻產業研究報告」** | 證交所與台經院、資策會合作，2026-03 起每月發布 3–5 篇**產業**研究報告，放在創新板官網。是產業研究，**不是個股評等或目標價**；授權條款沒查到 | — | 【單一來源：[經濟日報](https://money.udn.com/money/amp/story/5613/9783448)】 |

**小結**：台灣沒有任何官方或開放授權的評級、目標價或共識預估資料。證交所反而把媒體轉載券商報告當成要**澄清**的事（見 4.5）【推論】。

### 1.2 美國

| 來源 | 內容 | 標示 |
|---|---|---|
| **SEC EDGAR** | 沒有分析師評級、目標價。相鄰的資料：公司在 8-K **Item 2.02**（營運結果，財報新聞稿通常放在 Exhibit 99.1）與 **Item 7.01**（Regulation FD 揭露，財測更新常放在這裡）提供的**公司自己**的財測；兩者都是 furnished、不是 filed | 【單一來源：[edgar.tools 8-K 項目說明](https://app.edgar.tools/tools/8-k-items)、[FORM Holdings 8-K 範例](https://www.sec.gov/Archives/edgar/data/0001410428/000114420417038185/v471500_8k.htm)】 |
| Regulation FD | 禁止公司選擇性地把重大未公開資訊只告訴分析師或機構投資人 | 【單一來源：[ai-analytics.org](https://ai-analytics.org/writing/sec-8k-material-events/)】＋【記憶】 |
| EDGAR 的使用條件 | 免費、可商用；上限 10 次／秒，User-Agent 要寫明身分 | 見 `data-sources-licensing.md` §2.3【單一來源】 |

**小結**：美股官方也沒有評級。可以合法顯示的是**公司自己的財測**，附 EDGAR 連結【推論】。

---

## 2. 問題 2：商業資料商（台股為主）

> 共通結論：沒有一家公開「顯示給 App 使用者」的價格或標準授權。下表的欄位多半是從媒體或產品介紹反推的。

| 資料商 | 提供的欄位（已知部分） | 台股涵蓋 | API | 價格 | 對外顯示、再散布授權 | 標示 |
|---|---|---|---|---|---|---|
| **TEJ 台灣經濟新報** | 資料庫分類有「財務預測」；成大的 TEJ 簡介列出「**券商預測**」與「TEJ 專家財測應用系統」、「月盈餘概估」。是否含目標價、評等、券商名稱，不確定 | 上市櫃全面【記憶】 | TEJ API、TQuant Lab（「目前資料庫僅支援台灣市場」） | 無公開價目 | TEJ 講義：內容著作權歸 TEJ，「未經書面授權，不得以任何形式轉載、複製、引用、公開傳輸、改作或散布」 | 【單一來源：[成大 TEJ 簡介](https://libapp.lib.ncku.edu.tw/libref/chinese/talk/TEJ/TEJ_intro_%20ncku.doc)、[TQuant 手冊](https://tejtw.github.io/TQuant-manual/how-to/data/ingest-tej-fundamental)、[政大 TEJ 講義](https://www.lib.nccu.edu.tw/var/file/0/1000/img/101/TEJ_20250321.pdf) 搜尋摘要】 |
| **CMoney**（籌碼K線、投資決策支援系統） | 籌碼K線「法人目標價」：各券商目標價分布圖、歷來目標價、券商「準確度」排名（CMoney 自己計算）、「報告摘要」（由 CMoney 研究員依報告編撰）。另有每日「券商評等報告彙整」文章，例如「M31（6643）今日有 3 家券商發布績效評等報告…目標價區間為 745～1,525 元」 | 上市櫃 | 法人版「投資決策支援系統」有 300 個資料模組，客戶是投信、投顧、銀行、保險；對外 API 授權沒查到 | 無公開價目 | 沒查到 | 【單一來源：[CMoney 文章](https://www.cmoney.tw/notes/note-detail.aspx?nid=406212)、[券商評等彙整](https://www.cmoney.tw/notes/note-detail.aspx?nid=813697)、[決策系統頁](https://www.cmoney.tw/app/itemcontent.aspx?id=1940)】 |
| **財報狗** | 沒找到法人目標價或共識功能；有 PE／PB 區間評價（自己算的） | — | — | — | — | 【單一來源：[財報狗部落格](https://statementdog.com/blog/archives/tag/pe)】 |
| **嘉實資訊 XQ／MoneyDJ** | 有部落格文章說可用 XQ 查「法人推薦股」；欄位與授權沒查到 | 上市櫃 | XQ 是看盤軟體；資料 API 沒查到 | — | 沒查到 | 【單一來源：[玩股網文章](https://www.wantgoo.com/blog/196558/post/7)、[遠見](https://www.gvm.com.tw/article/125407)】 |
| **Goodinfo** | 沒找到評等或目標價頁面 | — | — | — | 條款見 `data-sources-licensing.md` §4.1 | 【單一來源】 |
| **鉅亨網（cnyes／Anue）** | ①「外資評等」個股頁（`cnyes.com/twstock/foreignrating.aspx?code=…`）；②「鉅亨速報 - Factset 最新調查」系列：分析師家數、當年 EPS 預估的中位數（上修／下修）、最高、最低、平均、**預估目標價**，並列營收預估，文末「資料來源：Factset，數據僅供參考」。例：「共 14 位分析師，對智原（3035-TW）做出 2025 年 EPS 預估：中位數由 5.61 元上修至 5.7 元…預估目標價為 211 元」 | 上市櫃（有 FactSet 涵蓋者） | 沒查到對外 API | — | 鉅亨著作權聲明：未經書面授權不得以任何形式利用、轉載、散布（`data-sources-licensing.md` §2.4）。和 FactSet 的授權關係沒找到公告；顯示鉅亨是 FactSet 授權用戶【推論】 | 【單一來源：[foreignrating 頁](https://www.cnyes.com/twstock/foreignrating.aspx?code=2454)、[鉅亨速報（Yahoo 轉載）](https://tw.stock.yahoo.com/news/%E9%89%85%E4%BA%A8%E9%80%9F%E5%A0%B1-factset-%E6%9C%80%E6%96%B0%E8%AA%BF%E6%9F%A5-%E6%99%BA%E5%8E%9F-3035-021027449.html)】 |
| **FactSet** | 共識 EPS（含家數、高低、中位數）、目標價；同類報導也出現在 Longbridge（例：2026-04 健鼎 3044-TW，9 位分析師） | **有台股**（媒體報導證實） | FactSet API／feed【記憶】 | 企業報價 | 沒找到條款；對外顯示需另外授權【記憶＋推論】 | 【單一來源：[Longbridge](https://longbridge.com/en/news/281971405.md)】 |
| **LSEG I/B/E/S** | 逐家券商的 EPS 等預估、共識（平均、中位數、高、低）、評等、目標價【單一來源：[uanalyze 介紹](https://uanalyze.com.tw/index.php/articles/3874239629)】；全球 22,000+ 家公司、90+ 市場、950+ 家券商貢獻 | 亞太有涵蓋，台灣家數沒查到 | Realtime feed、API、Snowflake、雲端 | 企業報價 | 沒查到 | 【單一來源：[LSEG Broker Estimates](https://www.lseg.com/en/data-catalogue/company-data/ibes-estimates/broker-estimates)】 |
| **S&P Capital IQ Estimates** | 20,000+ 家公司、600+ 家貢獻券商、3–5 年預估；資料取自券商報告或券商直接提供的 feed；**使用者要有特定券商的權限才看得到該券商的預估** | 全球（舊新聞稿說 100 國） | Capital IQ Pro、Xpressfeed、Snowflake | 企業報價 | 沒查到 | 【單一來源：[S&P 產品頁](https://www.spglobal.com/market-intelligence/en/solutions/capital-iq-estimates)、[Marketplace](https://www.marketplace.spglobal.com/datasets/s-p-capital-iq-estimates-(1))】 |
| **Bloomberg BEst** | 共識預估 | 全球 | Data License | 企業報價；業界報導指 Data License 曾提出**再散布費**，並把部分資料的散布權綁在新計價模式 | 要另外授權 | 【單一來源：[WatersTechnology](https://www.waterstechnology.com/node/2140473)】 |
| **Visible Alpha**（S&P Global） | 取得券商**原始模型**（不是報告），有所有細項預估；7,000+ 家公司、250+ 家券商；S&P 2026-08 的聯發科分析使用其共識 | 有台股（聯發科） | feed | 企業報價 | 沒查到 | 【單一來源：[Visible Alpha](https://visiblealpha.com/?p=9920)、[S&P 2026-08-26](https://www.spglobal.com/market-intelligence/en/news-insights/research/2026/08/mediatek-s-ai-asics-growth-to-offset-smartphone-weakness)】；屬 S&P Global【記憶】 |

**補充**【記憶＋推論】
- 國際資料商的**逐家券商**評等與目標價，常受貢獻券商的限制（例如 Capital IQ 要看使用者有沒有該券商的權限），能對外顯示的多半只有**共識數字**。所以就算付費，「列出每家外資的目標價」也不一定能拿到顯示權，要在詢價時特別問。
- 台灣資料商（TEJ、CMoney、鉅亨）的目標價，最終也來自券商報告。券商報告聲明禁止轉載（見 4.4），資料商轉授權給第三方 App 的範圍要寫進合約。

---

## 3. 問題 3：美股 API

| 服務 | 資料 | 台股（.TW）涵蓋 | 價格 | 能不能在 App 裡顯示給其他使用者 | 標示 |
|---|---|---|---|---|---|
| **Finnhub** | Estimates 類：Recommendation trends、Price Target（高、中位數、更新日期）、Upgrade/Downgrade、EPS estimates | 沒查到 | 免費 60 次／分（個人）；有第三方說公開價目只有 Free 或 All-In-One US$3,500／月；也有人說 fundamentals 每市場 US$50–200／月 | **不行（自助方案）**。多個第三方說「所有自助方案都只限個人」，個人方案不能給任何企業使用，即使內部也要書面同意；商用只有 Enterprise。哪些估計端點免費：印象是推薦趨勢免費、目標價與升降評要付費【記憶】 | 【單一來源：[sentisense](https://sentisense.ai/blog/market-data-api-commercial-use/)、[roic.ai](https://www.roic.ai/blog/finnhub-alternative-roic-ai-vs-finnhub-api)、[apicostcalc](https://apicostcalc.com/finnhub.html)；**Finnhub 條款原文沒讀到**】 |
| **Financial Modeling Prep（FMP）** | price-target（逐筆：分析師、日期）、price-target-summary／consensus（平均、高、低、中位數）、grades（升降評）、analyst estimates；**TipRanks 資料集**（依個股／分析師／券商的評等摘要、point-in-time 評等與目標價；目標價預設換成 USD，`nonadjusted=true` 回原幣） | 原幣參數暗示有非美股；.TW 沒確認 | 個人方案有公開價（這次沒取得數字）；商用要 Enterprise 報價 | **個人方案不行**。官方定價頁：「Displaying or redistributing data sourced from FMP requires a specific Data Display and Licensing Agreement with FMP」；官方 FAQ：公開網站或 App 上線前要先簽，**免費公開網站也算顯示**，付個人方案也不改變這點；條款：個人授權「strictly for their own personal, non-business and non-commercial purposes」 | 【單一來源：[FMP 定價](https://site.financialmodelingprep.com/developer/docs/pricing)、[FMP FAQ](https://site.financialmodelingprep.com/insights/platform/can-you-use-fmp-data-in-a-public-app-website-or-client-dashboard)、[條款](https://site.financialmodelingprep.com/terms-of-service)、[TipRanks 資料集](https://site.financialmodelingprep.com/datasets/analyst-ratings-tipranks)】 |
| **Massive（前 Polygon）＋ Benzinga** | `/benzinga/v1/ratings`：評等動作、目標價變動（raises／lowers／maintains…）、`price_target`、券商（`benzinga_firm_id`）、分析師；另有共識評等、Analyst Insights；13 年以上歷史 | **只有美股**（9,000+ 檔） | Individual 加購 Benzinga「從 US$99／月起」（2025-06 部落格）；Business 方案找業務報價 | **Individual 不行**。Massive 知識庫：Individual 是個人授權，「does not extend to an app」，API 不會擋，但不改變授權範圍；商用或專業用途要 Business 產品；Business 條款 2026-10-06 更新 | 【單一來源：[Massive 文件](https://massive.com/docs/rest/partners/benzinga/analyst-ratings)、[Benzinga 合作公告](https://massive.com/blog/benzingadata-partnership)、[知識庫：App 要哪個方案](https://massive.com/knowledge-base/article/which-plan-do-i-need-to-show-massive-data-in-my-app)、[Individuals 條款](https://massive.com/legal/individuals-terms-of-service)】 |
| **Benzinga（直簽）** | 同上；美股，2013 年起 | 只有美股 | 授權團隊報價 | **授權後可以**：產品頁說授權允許顯示彙總的評等與目標價，以及每一筆升評、降評、首評、維持 | 【單一來源：[Benzinga Analyst Ratings API](https://www.benzinga.com/apis/analyst-ratings-api/)、[docs](https://docs.benzinga.com/introduction/introduction)】 |
| **Alpha Vantage** | `OVERVIEW` 的 `AnalystTargetPrice`（平均目標價）與 Strong Buy～Strong Sell 家數 | 沒查到 | 免費 25 次／日；付費 US$49.99–249.99／月（`data-sources-licensing.md`） | **不行**：條款授權限個人、非商業，除非另有書面協議 | 【單一來源：[條款](https://alphavantage.co/terms_of_service)、[macroption](https://www.macroption.com/alpha-vantage-company-overview/)】 |
| **Tiingo** | **沒有分析師資料**（基本面來自 SEC 申報） | — | — | 「使用者自帶 token」模式在 Tiingo 是允許的，但沒有評級資料可用 | 【單一來源：[Tiingo 基本面](https://api.tiingo.com/products/fundamental-data-api)】 |
| **Zacks**（Nasdaq Data Link、Intrinio） | 共識評等（Strong Buy～Strong Sell 家數）、EPS 預估、目標價；約 4,500 檔美股＋700 檔加股；Intrinio 說 5,000+ 家美加公司 | 無 | 沒查到 | 沒查到（要問 Nasdaq Data Link 或 Intrinio） | 【單一來源：[Zacks 機構服務](https://www.zacks.com/help/institutional.php)、[Intrinio](https://docs.intrinio.com/documentation/web_api/get_zacks_analyst_ratings_v2)】 |
| **TipRanks API／MCP** | 評等、目標價、Smart Score | 沒查到 | 機構產品報價；也透過 FMP、Nasdaq Data Link 供應 | **不行（自助）**。MCP／API 條款：有限、可撤銷的授權，只能「build and operate your own applications and internal workflows」；不得「redistribute, resell, republish, or sublicense the data to any third party」，也不得做成公開 feed、資料集或 API；不得用來訓練 AI | 【單一來源：[TipRanks MCP 條款](https://mcp.tipranks.com/terms) 搜尋摘要；「own applications」是否涵蓋顯示給 App 使用者，要問】 |
| **MarketBeat** | 沒找到官方 API，只有第三方爬蟲 | — | — | **不行** | 【單一來源：搜尋結果只有 Apify 爬蟲】 |
| **Yahoo Finance** | 有 .TW 的分析師頁 | 有 | — | **不行**：repo 既有結論是條款禁止轉發 | 【事實：`README.md`】（`data-sources-licensing.md` §4.1） |
| **Twelve Data**（補充） | `price_target`、`recommendations`、`earnings_estimate`；「analyst ratings light」支援美國以外市場 | 可能有，沒確認 | 沒查到 | 沒查到 | 【單一來源：[Twelve Data 公告](https://twelvedata.com/news/twelve-data-unveils-analysis-data-with-estimations-and-recommendations)】 |
| **EODHD**（補充） | 基本面含 .TW、.TWO；`AnalystRatings` 欄位在台股有沒有值沒確認 | 基本面有 | 商用內部約 US$399／月起（`data-sources-licensing.md` §2.3） | 顯示給他人屬商用，要事先書面同意 | 【單一來源】 |

**小結**【推論】
- 美股評級可以買到結構化資料，但**最便宜的合法顯示路線也要談商用合約**。Benzinga 經 Massive Business 或直簽、FMP 的 Data Display 協議，都沒有公開價格。
- 「使用者自帶 API 金鑰」只在 Tiingo 明文允許，而 Tiingo 沒有評級資料。Finnhub、FMP 的個人授權能不能讓使用者在**收費的第三方 App** 裡用自己的金鑰，沒有看到明文，要先問。

---

## 4. 問題 4：從新聞取得「外資調升某股目標價至 X 元」

### 4.1 新聞裡有什麼

- 財經媒體天天報導這類事實，例如經濟日報整理「頎邦…野村維持『買進』評等，目標價由 171 元調升至 270 元」【單一來源：[經濟日報](https://money.udn.com/money/amp/story/5607/9765424)】。
- 鉅亨的 FactSet 系列會報導共識數字（見第 2 節）。
- 一則典型報導含：**機構名稱、評等、目標價（舊→新）、日期、理由摘要**。

### 4.2 著作權：事實 vs. 表達

| 法域 | 規範與判例 | 對「機構 X、評等、目標價、日期」的意義【推論】 | 標示 |
|---|---|---|---|
| 台灣 | 著作權法第 9 條第 1 項第 4 款：「單純為傳達事實之新聞報導所作成之語文著作」不受保護；立法理由是這類報導要快速傳播，通常沒有思想或感情的原創表達 | 「某券商把某股目標價調到 X 元」這個事實不受保護；但新聞的分析、評論、整篇文字仍受保護 | 【單一來源：[法律百科](https://www.legis-pedia.com/article/Intellectual-property-rights/488)】；第 9 條原文見 `data-sources-licensing.md` §4.2【事實】 |
| 台灣 | 第 10 條之 1：只保護表達，不保護思想、概念、發現 | 目標價是一個數字，表達空間極小，很難單獨受保護 | 【記憶】 |
| 台灣 | 第 7 條：資料的選擇及編排有創作性，可成為編輯著作；台灣沒有歐盟式的資料庫特別權 | 整批搬別人整理好的「目標價彙整表」，可能侵害對方的編輯著作；自己逐筆蒐集、自己編排則風險較低 | 【記憶】；`data-sources-licensing.md` §4.2 |
| 台灣 | 第 61 條：刊登在新聞紙、雜誌或網路上、有關政治、經濟或社會時事問題的**論述**，得由其他媒體轉載或在網路上公開傳輸，「但經註明不許轉載…者，不在此限」；智慧局：註明人須是權利人，方式要讓利用人客觀上能知道；利用時仍須依第 64 條註明出處 | 財經媒體幾乎都註明「未經授權不得轉載」（鉅亨、經濟日報），**不能靠第 61 條轉載全文** | 【單一來源：[植根法律網函釋](https://www.rootlaw.com.tw/LetterContent.aspx?LCode=13&SOID=251813)】 |
| 台灣 | 第 52 條合理引用、第 65 條合理使用（四項判斷基準） | AI 用自己的話寫一句、附連結，比較接近「引用事實並註明出處」，但收費服務會讓「營利目的」這項判斷基準不利 | 【記憶】 |
| 美國 | *Feist v. Rural*（1991）：事實不受保護，編排要有最低限度的創作性 | 同上 | 【記憶】 |
| 美國 | *CCC Information Services v. Maclean Hunter*（2d Cir. 1994）：Red Book 的中古車估價「不是歷史市價…而是編輯對未來六週價值的預測」，第二巡迴法院認為受保護的範圍比地院認定的大 | **預測性數字的彙編**可能受保護，所以不要整批複製別人的目標價表 | 【單一來源：[Justia](https://law.justia.com/cases/federal/appellate-courts/F3/44/61/513081)】 |
| 美國 | *Barclays Capital v. Theflyonthewall.com*（650 F.3d 876，2d Cir. 2011-06-20）：Barclays、Merrill Lynch、Morgan Stanley 告 Fly 在開盤前發布它們的個股建議；二審認為「熱門新聞（hot news）盜用」主張被著作權法排除，撤銷禁制令；Fly 有標明是哪家券商發的 | **據實、標出處地報導「某券商調升評等」是新聞，券商很難禁止**；但判決範圍窄、看個案事實 | 【單一來源：[DMLP](https://www.dmlp.org/blog/2011/second-circuit-rules-hot-news-claims-preempted)、[Skadden](https://www.skadden.com/insights/publications/2011/06/second-circuit-redefines-elements-of-hot-news-misa)、[White & Case](https://www.whitecase.com/sites/default/files/files/download/publications/alert_court_rejects_hot_news_protection.pdf)】 |

### 4.3 契約與爬蟲：比著作權更實際的風險

詳見 `data-sources-licensing.md` §4。摘要如下：
- 鉅亨、經濟日報都聲明未經書面授權不得轉載；Google News RSS 只限個人使用【單一來源】。
- 違反網站條款大量抓取，台灣曾有一審認定構成刑法第 359 條的「無故取得電磁紀錄」（Lawsnote 案，2025-06，上訴中）【單一來源】。
- 有系統地搬運他人網站資料、取代原網站瀏覽，公平會曾以公平法第 25 條處分（豬豬快租案，2017）【單一來源】。
- 【推論】對目標價來說，CMoney、鉅亨、TEJ 都把這些資料當**付費商品**。我們有系統地從它們的頁面或新聞累積成資料庫，最容易被主張「搭便車」。

### 4.4 券商研究報告的轉載限制（原文舉例）

| 券商 | 聲明（節錄） | 標示 |
|---|---|---|
| Goldman Sachs | 「No part of this material may be (i) copied, photocopied or duplicated in any form by any means or (ii) redistributed without our prior written consent.」 | 【單一來源：[GS disclosures](https://www.goldmansachs.com/what-we-do/FICC-and-equities/business-groups/sts-folder/gsci/disclosures.html) 搜尋摘要】 |
| J.P. Morgan | 研究報告頁尾：「may not be reprinted, sold or redistributed without the written consent of J.P. Morgan」；另一份聲明：「may not be reproduced, redistributed or disseminated, in whole or in part, without the prior written consent of J.P. Morgan」 | 【單一來源：[JPM material disclaimer](https://www.jpmorgan.com/pages/disclosures/materialdisclaimer)、研究報告 PDF 搜尋摘要】 |
| Morgan Stanley | 沒找到研究報告聲明逐字原文。官網條款：電子訊息「may not be reproduced, redistributed or disseminated, without the prior written consent of Morgan Stanley」；研究揭露頁說部分研究透過第三方供應商提供給**客戶** | 【單一來源：[MS terms](https://www.morganstanley.com/disclaimers/terms)、[research disclosures](https://www.morganstanley.com/eqr/disclosures/webapp/generalresearch)】 |
| 元大（元大銀行研究報告；元大投顧原文沒找到） | 「本報告受中華民國著作權法保護為元大銀行所有，非經本行同意，不得將本報告內容之一部或全部加以複製、轉載或散布。」 | 【單一來源：[元大銀行報告 PDF](https://www.yuantabank.com.tw/bankwebIMG/dwn/DWN_5f5d9f7742000000ef3d9b62981fdecd.pdf)】 |
| 凱基（香港） | 「只作一般資料及參考用途」；報告只供閱覽，未經凱基書面同意不得擅自以任何方式使用（摘要被截斷）；「凱基概不就因任何使用本報告或其內容而產生的任何損失承擔任何責任」 | 【單一來源：[KGI 台股策略報告](https://www.kgi.com.hk/zh-hk/-/media/files/kgishk/research-reports/tw-reports/taiwan-2026-strategy_20251121.pdf)】 |
| 富邦 | 沒找到 | — |

【推論】這些聲明約束的是**拿到報告的人**（客戶），不直接約束看到新聞的第三人。但它表示：①Forliosa 不能拿到報告後轉載；②媒體轉述的目標價，券商通常不會替它的完整性背書。

### 4.5 台灣特有：2014 年起，券商同意媒體轉載時不得含目標價

- 金管會與證交所 2014 年修正《證券商推介客戶買賣有價證券管理辦法》，103-09-19 起實施，國內券商也適用。重點如下：
  - 研究報告要標示「非經同意不得轉載」。
  - 券商可以同意媒體轉載，但轉載內容**不得預測個股目標價、未來營收、每股盈餘，也不得提及支撐或壓力點**。
  - 媒體轉載的內容與報告有出入、或未經同意轉載，券商要到**公開資訊觀測站澄清**。
  - 【單一來源：[中央社 2014-09-18](https://www.chinatimes.com/realtimenews/20140918005273-260410)、[自由財經](https://ec.ltn.com.tw/article/paper/814596)、[工商時報 2014-07-31](https://www.ctee.com.tw/news/20140731700053-439901)、[證交所函](https://www.twse.com.tw/staticFiles/marketAnnounce/setAnnounce/1030019044.htm)】
- 金管會一度考慮要外資券商主張著作權，隔天就改口，理由是怕媒體引用會被告【單一來源：[中央社 2014-07-30](https://www.chinatimes.com/realtimenews/20140730005180-260410)、[今周刊](https://www.businesstoday.com.tw/article/category/80392/post/201408070011/)】。
- 新制後，巴克萊兩位分析師在 2015-09 被分別停職 1 個月、2 個月【單一來源：同上搜尋摘要】。
- 現行條文這次讀不到（證交所法規庫連不到），只確認植根法律網收錄的 113-12-31 版本仍有「研究報告發布後二小時內不得買賣」等規定【單一來源：[植根](https://www.rootlaw.com.tw/LetterContent.aspx?LCode=31&SOID=175172)】。

【推論】
- 這套規定約束的是**證券商**，不是媒體，也不是 Forliosa。
- 但它說明兩件事：①台灣媒體上的目標價，大多**沒有得到券商同意轉載**；②主管機關認為目標價在媒體上「滿天飛」容易誤導投資人。
- 所以 Forliosa 顯示目標價時要：標「據媒體報導」、附日期和連結、提醒「可能不完整、券商可能已澄清」，不要把它包裝成權威數據。

### 4.6 四種做法比較

| 做法 | 怎麼做 | 著作權 | 條款、爬蟲 | 公平法、搭便車 | 投顧法 | 判定【推論】 |
|---|---|---|---|---|---|---|
| **A. 只放連結** | 個股頁放「查看鉅亨外資評等」「查看公開資訊觀測站券商澄清」等外部連結 | 無 | 無 | 無 | 無 | ✅ 最安全，但體驗差 |
| **B. AI 即時查詢＋引用（建議）** | 使用者點「法人觀點」→ Claude 網頁搜尋（Anthropic 代為搜尋，不是我們爬）→ 以自己的話列出 3–5 筆「機構、動作、評等、目標價、日期」＋每筆來源連結；同一檔同一天共用一份快取，24 小時後丟棄 | 只取事實、不複製文章、附出處 | Forliosa 不爬網站；Claude 網頁搜尋規定回答顯示給使用者時要附可點擊的引用【單一來源：[Claude 網頁搜尋文件](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)；`claude-platform-fit.md`】 | 低：依需要、零星、導流回原網站 | 只要不轉成自己的推介，風險低 | ✅ 現在可用（收費前請律師確認） |
| **C. 把 AI 抓到的事實存成資料表** | 每次查到就寫入 `analyst_actions` 資料表，累積歷史、做時間軸、算共識 | 事實本身 OK；累積後成為**我們自己的**編輯著作 | 資料仍來自付費媒體與資料商的成果 | **中到高**：等於免費重建 CMoney、鉅亨、FactSet 的付費產品 | 算共識、排行時風險升高 | ⚠️ 不建議；要做就買授權 |
| **D. 爬新聞網站建資料庫** | 程式定期爬鉅亨、經濟日報等 | 同 C | **違反條款**；刑法第 359 條風險 | 高 | 同 C | ❌ 不可以 |

**B 的界線**【推論】
- 快取是「同一份 AI 回答給多人看」的成本優化，內容就是那則附引用的回答，**不另外做結構化資料表**，不能搜尋、匯出、排行，過期就刪。
- 要做歷史時間軸或共識，就改走授權資料（第 8 節）。
- Anthropic 對「儲存網頁搜尋結果」有沒有額外限制，這次沒找到。內容的權利仍屬原網站，儲存全文或長摘錄不建議【推論】。

---

## 5. 問題 5：使用者自己券商的研究報告

- 券商把研究報告提供給**開戶客戶**，是《證券商推介客戶買賣有價證券管理辦法》下的「推介」，報告要標「非經同意不得轉載」【單一來源，見 4.5】。
- 元大「投資先生」App 列出「專業研究報告」功能【單一來源：[App Store](https://apps.apple.com/us/app/%E6%8A%95%E8%B3%87%E5%85%88%E7%94%9F/id1382114621?l=ar)】，但會員專屬內容的使用條款沒查到。
- 永豐 Shioaji、富邦 Neo 等券商 API 是行情與交易 API，【記憶】沒有提供研究報告。

| 情境 | 判定【推論】 |
|---|---|
| Forliosa 顯示「某使用者的券商報告」給**其他**使用者，或拿來做共用摘要 | ❌ 違反券商聲明（再散布） |
| 使用者自己上傳報告 PDF，AI 只為**他本人**做摘要，不保存或私人保存，不與他人共用、不進共用快取 | ⚠️ 大概可以（等於本人閱讀），但伺服器處理、收費服務是否仍算個人使用，要看券商條款；建議先問券商 |
| 個股頁放「到你的券商 App 看研究報告」深層連結 | ✅ 可以 |
| 用使用者的券商帳號，由伺服器代為登入抓報告 | ❌ 不要做（等於替使用者爬券商網站；`data-sources-licensing.md` §3 的行情結論同理） |

---

## 6. 問題 6：法規（投顧法）

### 6.1 規範

| 條文、文件 | 內容 | 標示 |
|---|---|---|
| 證券投資信託及顧問法第 4 條第 1 項 | 「本法所稱證券投資顧問，指直接或間接自委任人或第三人取得報酬，對有價證券、證券相關商品或其他經主管機關核准項目之投資或交易有關事項，提供分析意見或推介建議。」第 2 項：證券投資顧問事業是經許可、以此為業的機構 | 【單一來源：[6laws 收錄全文](https://6laws.net/6law/law/證券投資信託及顧問法.htm)（修正日期 112-05-30）】 |
| 第 6 條第 1 項 | 「非依本法不得經營證券投資信託、證券投資顧問及全權委託投資業務。」 | 【單一來源：同上】 |
| 第 107 條第 1 款 | 違反者「最重處 5 年以下有期徒刑，或併科 100 萬到 5,000 萬罰金」（媒體轉述）；法院的判斷要件：未經許可、就投資事項提供分析意見或推介建議、**從中取得報酬** | 【單一來源：[自由時報（大萌妹子案）](https://ec.ltn.com.tw/article/breakingnews/3999895)、[新北地院判決](https://judgment.judicial.gov.tw/FILES/PCDM/112%2c%e9%87%91%e8%a8%b4%2c778%2c20240227%2c1.pdf)】 |
| 金管會立場 | 「倘若民眾自行招收會員、收取報酬，並對股票提供分析意見或推介建議為其業務者，即屬非法經營投顧業務」；用 LINE 等社群推薦飆股屬違法 | 【單一來源：[鉅亨](https://news.cnyes.com/news/id/5384442)】 |
| 2024-03 | 金管會主委表示投信投顧法「管不到財經網紅」，當時改用公平會的廣告不實規定與公會自律處理；之後的修法狀態沒確認 | 【單一來源：同上搜尋摘要】 |
| 證交所《證券商推介…管理辦法》 | 見 4.5：約束券商，不約束媒體與 App | 【單一來源】 |
| 美國 *Lowe v. SEC*（472 U.S. 181，1985） | 一般發行、定期出刊、內容不為個人量身打造的出版品，屬「bona fide publication」排除，不算投資顧問；「刊物含有對特定證券的建議與評論，並不因此具有個人化性質」 | 【單一來源：[Cornell LII](https://www.law.cornell.edu/supremecourt/text/472/181)】；Forliosa 不以美國使用者為對象，僅供參考 |

### 6.2 對 Forliosa 的意義【推論】

- **風險高的做法**（收費之後）：
  - 「外資看好股」清單。
  - 依「目標價上漲空間」排序。
  - 「X 家看多、Y 家看空」的評分。
  - AI 說「法人普遍看好，可以考慮買進」。
  - 根據持股推播「某券商調升你的持股目標價」並附買進暗示。
- **風險低的做法**：
  - 像新聞一樣並列「某機構某日報告：評等○○、目標價 X 元（來源）」。
  - 不加 Forliosa 自己的結論，多空並陳。
  - 不針對個別使用者的持股給建議。
- **repo 現況**：AI 系統提示明寫「只做分析與整理，不保證報酬，不下買進或賣出的指令，也**不給目標價**」【事實：`apps/api/src/forliosa/ai/prompts.py:44`】。
  - 「法人觀點」功能要允許 AI **引用第三方已公開的目標價並附出處**，同時維持「AI 自己不給目標價」。
  - 這是產品負責人要決定的規則變更，提示文字要寫清楚兩者的分別。
- **收費前要問律師的題目**：
  - 收費 App 以「附出處的新聞摘要」顯示第三方目標價，是否屬投顧法第 4 條的「提供分析意見或推介建議」？
  - 依持股推播第三方評等變動，是否改變判斷？
  - 免責文字與呈現方式要怎麼寫？

---

## 7. 綜合比較表

判定：✅ 現在可用　💰 付費並簽約後可用　⚠️ 有條件　❌ 不可用

| 來源 | 涵蓋 | 欄位 | 費用 | App 內對外顯示授權 | 判定 |
|---|---|---|---|---|---|
| 證交所／櫃買 OpenAPI、data.gov.tw、SITCA、證期局 | TW | 沒有評級資料 | 免費 | — | ❌（沒有這種資料） |
| 公開資訊觀測站「券商對媒體轉載澄清」 | TW | 券商澄清 | 免費 | 網站條款禁止未經同意爬取 | ⚠️ 只放連結或由 AI 搜尋引用 |
| 公開資訊觀測站法說會、`t187ap16_L` | TW | **公司自己**的財測 | 免費 | OpenAPI 可商用；簡報著作權屬公司 | ✅（不是分析師資料） |
| SEC EDGAR 8-K 2.02／7.01 | US | 公司財測 | 免費 | 可商用 | ✅（不是分析師資料） |
| TEJ（券商預測） | TW | 券商預估（是否含目標價、評等待確認） | 詢價 | 需書面授權 | 💰 要問 |
| CMoney（法人目標價） | TW | 逐家目標價、準確度、報告摘要 | 詢價 | 沒查到 | 💰 要問 |
| 鉅亨（外資評等、FactSet 共識） | TW（＋US） | 共識 EPS、家數、預估目標價、評等 | 詢價 | 條款禁止，除非簽約 | 💰 要問 |
| 嘉實 XQ／MoneyDJ | TW | 法人推薦等 | 詢價 | 沒查到 | 💰 要問 |
| 財報狗、Goodinfo | — | 沒找到這類功能 | — | — | ❌ |
| FactSet、LSEG I/B/E/S、S&P CIQ、Bloomberg、Visible Alpha | TW＋US | 完整（逐家、共識、目標價、評等） | 企業報價（推估很高） | 要另簽顯示授權；逐家券商資料可能受貢獻券商限制 | 💰 貴 |
| Finnhub | US（國際？） | 推薦趨勢、目標價、升降評、EPS 預估 | 免費／Enterprise | 自助方案限個人 | ❌ 自助；💰 Enterprise |
| FMP（含 TipRanks） | US（國際可能） | 目標價逐筆與共識、升降評、預估 | 個人方案便宜；顯示協議報價 | 要簽 Data Display and Licensing Agreement | 💰 |
| Massive＋Benzinga | US | 評等、目標價、券商、分析師 | Individual US$99+（不可用於 App）；Business 報價 | 要 Business | 💰 |
| Benzinga 直簽 | US | 同上 | 報價 | 授權後可顯示 | 💰 |
| Alpha Vantage | US | 平均目標價、評等家數 | US$49.99+ | 要書面協議 | 💰 |
| Zacks（Nasdaq Data Link、Intrinio） | US＋CA | 共識評等、預估、目標價 | 沒查到 | 沒查到 | 💰 要問 |
| TipRanks API／MCP | US | 評等、目標價、Smart Score | — | 禁止再發布、轉授權 | ❌（除非另談） |
| Tiingo | — | 沒有 | — | — | ❌ |
| MarketBeat、Yahoo | US（Yahoo 有 TW） | 有 | — | 沒有官方授權管道／條款禁止 | ❌ |
| Twelve Data | US＋國際（light） | 目標價、推薦、EPS 預估 | 沒查到 | 沒查到 | ❓ 要問 |
| **AI 即時網頁搜尋＋引用（4.6 B）** | TW＋US | 新聞報導過的評等、目標價、日期、來源 | 每次約 US$0.06–0.22（第 8 節） | 事實＋引用＋導流；Claude 規定要顯示引用 | ✅（收費前請律師確認） |
| 把新聞事實存成資料庫（4.6 C） | TW＋US | 同上 | 低 | 搭便車風險 | ⚠️ 不建議 |
| 爬新聞網站（4.6 D） | — | — | — | 違反條款 | ❌ |
| 使用者自己的券商研究報告 | 依券商 | 報告全文 | — | 只限本人 | ⚠️ 只限本人、只放連結 |

---

## 8. 建議做法

### 8.1 現在（只用可商用資料、不付授權費）

1. **不做任何共識數字**（平均目標價、看多家數、評等分布），也不做「EPS 對預估」。`stock-page-research.md` 已建議改成「對去年同季」，維持。
2. 個股頁加一張「**法人觀點**」卡，使用 4.6 B 模式：
   - 預設收合；使用者點「查看近期法人觀點」才觸發。同一檔當天第一次有人點時生成，當天其他人共用，隔天作廢。
   - 用 Claude 網頁搜尋（`allowed_domains` 限定信譽良好的財經媒體與官方網站），請 AI 用**結構化輸出**回傳最多 5 筆。每筆含 `institution`、`action`（調升／調降／維持／首評）、`rating_text`（原文評等）、`target_price` 與幣別、`date`（報告或報導日期）、`source_title`、`url`；沒有日期或來源的不收。
   - 畫面只顯示這份回答和引用，**不另存成資料表**。
3. **美股也用同一模式**。EDGAR 的公司財測（8-K 2.02／7.01）可以另外做成「公司財測」區塊，附連結。
4. **系統提示改寫**（產品負責人決定）：保留「AI 自己不給目標價、不給買賣建議」；新增「可以引用第三方**已公開**的評等與目標價，每筆要附機構、日期與來源；不要彙總成共識，不要評論誰對誰錯，不要據此建議買賣」。
5. **收費前**：拿第 6.2 節的題目請律師看。

### 8.2 之後（要做結構化法人資料時）

| 目標 | 建議來源 | 要先問的事 |
|---|---|---|
| 台股共識目標價、EPS 預估、家數 | 依序詢價 **TEJ**（券商預測）、**CMoney**、**鉅亨**（是否能轉授權 FactSet 台股共識）、**FactSet 台灣**直簽 | ①App 內顯示給註冊使用者（含收費）是否允許；②逐家券商名稱與目標價能不能顯示，還是只能顯示共識；③歷史資料能不能保存；④要不要標示來源與免責文字；⑤依使用者數或曝光量計價的方式；⑥AI 能不能讀這些資料再回答使用者 |
| 美股評級變動時間軸、目標價 | **Benzinga**（經 Massive Business 或直簽，美股 9,000+ 檔）或 **FMP Data Display Agreement**（可能涵蓋部分國際股） | 同上，加：⑦能不能把資料送進 LLM 產生摘要（TipRanks 條款禁止 AI 訓練，類似條款要問清楚） |

### 8.3 預估月成本【推論】

**現在：AI 即時查詢**

單次生成的假設：
- 2–4 次網頁搜尋：每 1,000 次 US$10（事實：[Claude 定價](https://platform.claude.com/docs/en/about-claude/pricing)、`claude-platform-fit.md`），約 US$0.02–0.04。
- 含搜尋結果約 2–4 萬輸入 token、約 800 輸出 token。

| 模型 | 每次生成 | 家人朋友（每天約 20 檔 × 22 天） | 公開（每天約 300 檔 × 22 天） |
|---|---|---|---|
| 高階（Opus 5.5：US$4／US$20 每百萬 token） | 約 US$0.12–0.22 | 約 **US$50–100／月** | 約 **US$800–1,500／月** |
| 中階（Sonnet 5.5：US$2／US$10） | 約 US$0.06–0.11 | 約 **US$25–50／月** | 約 **US$400–750／月** |

省錢做法：
- 只在使用者點擊時生成。
- 自選股的「法人觀點」用 Message Batches 盤後預先生成（token 5 折，批次也能用網頁搜尋）。
- 同一檔當天共用，不要每人各生成一次。
- 實際數字要上線後量測；模型選擇由產品負責人決定（預設高階）。

**之後：授權資料**

| 項目 | 估計 |
|---|---|
| 台股共識或逐家目標價 | 沒有公開價目，要詢價。國際資料商與台灣資料商的對外顯示授權通常是年約、依使用者數計價【記憶】；先抓**每月 NT$30,000 以上**當詢價的心理準備【推論，沒有任何報價支持】 |
| 美股（Benzinga／FMP 顯示授權） | 沒有公開價目，要詢價。Massive Individual 的 Benzinga 加購（US$99+／月）**不能**用在 App |
| 合計 | 現在：US$25–1,500／月（依使用量）。之後：再加授權費，詢價後再算 |

---

## 9. 個股頁 UX 建議：「法人觀點」卡

```
┌ 法人觀點 ─────────────────────────────── 第三方意見 ┐
│ 近期媒體報導的機構看法（最多 5 筆，依日期新→舊）              │
│                                                              │
│ ・11/10  外資 A　維持「優於大盤」，目標價 1,500→1,650 元        │
│          來源：〔媒體名稱〕〔連結〕                             │
│ ・11/05  本土投顧 B　首次評等「買進」，目標價 1,480 元           │
│          來源：〔媒體名稱〕〔連結〕                             │
│ ・10/28  外資 C　調降至「中立」，目標價 1,300 元                 │
│          來源：〔媒體名稱〕〔連結〕                             │
│                                                              │
│ ⓘ 以上為第三方機構意見，經媒體報導整理，非 Forliosa 建議；       │
│   可能不完整、已更新，或未經券商同意轉載。以原始來源為準。       │
│   券商澄清：公開資訊觀測站〔連結〕　　　查詢時間 11/12 14:05     │
└──────────────────────────────────────────────────────────────┘
```

> 卡片中的機構代號、評等、目標價都是版面示意，不是真實資料。

設計原則【推論】：
- **每筆都要有日期與來源連結**。沒有來源的不顯示；超過 90 天的標「舊資料」或不顯示。
- **不顯示**：平均或中位數目標價、「上漲空間 %」、多空家數、紅綠燈、星等、排行榜。授權資料到手前，這些都不做。
- **語氣中立**：照抄評等原文（例如「優於大盤」「Overweight」），不翻譯成「看好」「建議買進」。多空並陳，不挑選。
- **不個人化推介**：不依持股推播「你的股票被調升目標價」。若要做提醒，只做「有新的法人觀點報導」這種中性通知，而且要先問律師。
- **AI 對話中**：使用者問「外資怎麼看台積電」時走同一套查詢與快取。回答仍不寫 Forliosa 自己的目標價；`DISCLAIMER` 照常顯示（`prompts.py`）。
- **資料來源與授權頁**：說明這張卡是「AI 依需要搜尋公開報導、附原始連結」，不是授權資料庫。

---

## 10. 無法查證的事

1. TEJ「券商預測」的實際欄位（有沒有目標價、評等、券商名稱）、對外顯示授權與價格（TEJ 網站連不到）。
2. CMoney「法人目標價」資料能不能授權給第三方 App、價格多少。
3. 鉅亨與 FactSet 的授權關係，以及鉅亨能不能轉授權；鉅亨外資評等頁的資料來源。
4. 嘉實 XQ／MoneyDJ 有沒有評等或目標價資料產品。
5. FactSet、LSEG、S&P、Bloomberg、Visible Alpha 的**台股涵蓋家數**、對外顯示授權費，以及逐家券商資料的顯示限制。
6. Finnhub 條款原文；評級相關端點各屬哪個方案；國際（.TW）涵蓋。
7. FMP 個人方案價格；TipRanks 資料集是否涵蓋台股；Data Display 協議價格。
8. Massive Individual 條款中關於顯示的逐字條文；Benzinga Business 價格。
9. TipRanks MCP／API 條款全文，以及「your own applications」是否允許顯示給 App 使用者。
10. Zacks 在 Nasdaq Data Link 的價格與授權；Twelve Data 的台股涵蓋與顯示授權；EODHD `AnalystRatings` 在台股有沒有值。
11. 《證券商推介客戶買賣有價證券管理辦法》**現行條文**中關於媒體轉載與目標價的條號與文字，以及 2014 年規定是否仍有效（證交所法規庫連不到）。
12. 投信投顧法第 107 條原文；有沒有金管會函釋談到「App 或網站轉述第三方評等、目標價」是否屬投顧業務。
13. Anthropic 對儲存網頁搜尋結果有沒有額外規定（沒找到）。
14. 公開資訊觀測站「券商對媒體轉載澄清」專區的實際網址與使用條款。
15. Morgan Stanley 研究報告聲明的逐字原文；元大投顧、富邦投顧報告的聲明原文。
16. 公平法第 25 條在「依需要、附引用、不建資料庫」模式下的適用（沒有直接相關的案例）。

---

## 11. 主要來源（讀取或搜尋日期 2026-11-12）

- **直接讀取**：[證交所 OpenAPI swagger](https://openapi.twse.com.tw/v1/swagger.json)、[櫃買 OpenAPI swagger](https://www.tpex.org.tw/openapi/swagger.json)；本 repo `apps/api/src/forliosa/ai/prompts.py`、`docs/research/data-sources-licensing.md`、`docs/research/claude-platform-fit.md`、`docs/research/stock-page-research.md`。
- **搜尋摘要**：各表格中標【單一來源】的連結。重要的幾項：
  - 規範：[證交所函 1030019044](https://www.twse.com.tw/staticFiles/marketAnnounce/setAnnounce/1030019044.htm)、[中央社 2014-09-18](https://www.chinatimes.com/realtimenews/20140918005273-260410)、[自由財經](https://ec.ltn.com.tw/article/paper/814596)、[投信投顧法（6laws）](https://6laws.net/6law/law/證券投資信託及顧問法.htm)。
  - 美國判例：[*Barclays v. Theflyonthewall.com*（DMLP）](https://www.dmlp.org/blog/2011/second-circuit-rules-hot-news-claims-preempted)、[*CCC v. Maclean Hunter*（Justia）](https://law.justia.com/cases/federal/appellate-courts/F3/44/61/513081)。
  - 美股資料商：[FMP 公開 App FAQ](https://site.financialmodelingprep.com/insights/platform/can-you-use-fmp-data-in-a-public-app-website-or-client-dashboard)、[Massive 知識庫](https://massive.com/knowledge-base/article/which-plan-do-i-need-to-show-massive-data-in-my-app)、[TipRanks MCP 條款](https://mcp.tipranks.com/terms)。
  - 國際資料商：[LSEG I/B/E/S](https://www.lseg.com/en/data-catalogue/company-data/ibes-estimates/broker-estimates)、[S&P Capital IQ Estimates](https://www.spglobal.com/market-intelligence/en/solutions/capital-iq-estimates)。
  - Claude：[網頁搜尋文件](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)。
