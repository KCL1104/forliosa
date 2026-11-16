# 法人評等、目標價與新聞資料的詢價信（信件草稿：8 封）

> **草稿，尚未寄出。** 撰寫：2026-11-16。
> 依據：產品負責人 2026-11-16 對〈法人評等、目標價與新聞〉備忘錄回「照建議」，其中：
> 決定 8（新聞搜尋先不換 Brave API，先寫信問保存條款）、決定 9（現在不買付費資料，先寫信問價）、決定 10（我擬稿，你寄出）。
> 十項決定的全文：`docs/pending-decisions.md`「2026-11-16 法人評等與新聞來源（照建議）」。
> 背景研究：`docs/research/analyst-ratings.md`、`docs/research/news-and-external-sources.md`、`docs/research/us-market-data.md`。
> **收件窗口與廠商條款大多只看過搜尋摘要，沒打開原網頁**（研究用的沙盒連不到這些網站）。寄出前請到對方官網確認窗口。
> 寄件人資料一律用〔〕佔位：你從自己的信箱寄，不要把個人信箱寫進 repo。

## 寄之前（每封都一樣）

- 補上〔姓名〕；電話可填可不填。
- 信裡的人數與用量都是估計：使用者「數十人以內」、開放註冊後第一年「數百到一千人」、每天被查看的股票 20–300 檔。和實際不符就改。
- **只問價，不簽約、不付款。** 對方要先簽保密協議（NDA）、試用合約，或要你先買方案，先把文件轉給我看。
- 對方問公司名稱或統一編號：目前是個人經營、還沒登記（`PRODUCT.md`「群組加值包」的「登記」）。照實說即可。
- 對方問售價：個人會員預計 NT$490／月、NT$4,900／年，**還沒開始收費**（`PRODUCT.md`「會員方案」）。
- 拿到書面答覆以前，不用這些資料。試用的金鑰只拿來看欄位和範例，不放進正式環境，也不給使用者看。
- 收到回覆：轉給我，或存到 `docs/research/`。我整理成一張比較表，再請你決定要不要付費（備忘錄第三階段）。

## 一覽

| # | 對象 | 寄到 | 語言 | 問什麼 |
|---|---|---|---|---|
| 1 | TEJ 台灣經濟新報 | tej@tej.com.tw | 中文 | 「券商投資建議」「券商分析師盈餘預估」兩張表 |
| 2 | CMoney | csservice@cmoney.com.tw（請轉企業窗口） | 中文 | 「法人目標價」：各券商的評等、目標價 |
| 3 | 鉅亨（Anue） | b2b-sales@anuegroup.com.tw | 中文 | FactSet 共識預估、目標價；台股新聞標題（選填） |
| 4 | 中央社 | sales@cna.com.tw | 中文 | 財經新聞的企業授權，含 AI 讀取（AskCNA） |
| 5 | Benzinga | licensing@benzinga.com | 英文 | 美股評等、目標價變動（Analyst Ratings API） |
| 6 | Financial Modeling Prep（FMP） | info@financialmodelingprep.com | 英文 | 目標價、評等的 Data Display and Licensing Agreement |
| 7 | Twelve Data | 業務表單 https://twelvedata.com/contact | 英文 | 商業方案的目標價、建議分數 |
| 8 | Brave | searchapi-support@brave.com | 英文 | 新聞搜尋 API：存標題和網址算不算「保存」 |

六個共同問題（備忘錄第 4 節第二階段）：
① 能不能給登入、付費的使用者看；② 能顯示各家券商的名稱，還是只能顯示共識；③ 能不能保存歷史；
④ AI 能不能讀、能不能在回答裡引用；⑤ 台股有沒有資料（含上櫃小型股；美國廠商問 AAPL、NVDA）；⑥ 來源要怎麼標示。
新聞的兩封（中央社、Brave）照新聞的情況改寫了問法。

**範例股票**：2330 台積電、2308 台達電、7799 禾榮科、6643 M31。
備忘錄只列了前三檔，但 7799 是 2025 年才**上市**的小型股，不是上櫃股。所以多加了上櫃小型股 6643 M31（2026-11-16 實測：近 90 天只有一篇「日系外資」報導）。

---

## 1. TEJ 台灣經濟新報

- **寄到**：tej@tej.com.tw；總機 02-8768-1088。
  - 來源：網路搜尋（一篇 2026 年 TEJ 文章附的聯絡方式），未查證。寄前到 https://www.tej.com.tw 的「聯絡我們」確認。
- **參考**：
  - 表名出自 TEJ 收錄清單（2025）：https://home.lib.fju.edu.tw/TC/sites/default/files/Database_file/TEJ%E6%94%B6%E9%8C%84%E6%B8%85%E5%96%AE(2025).pdf
  - TQuant Lab 個人方案：https://tquant.tejwin.com/product-category/plan-1/
- **給你**：不用附件。想讓對方看呈現方式，可以附一張個股頁「法人觀點」卡片的截圖（用 2330，不要截到持股金額）。打電話也可以，說「想詢問券商投資建議、盈餘預估資料給 App 顯示的授權與報價」。

**收件人**：tej@tej.com.tw
**主旨**：詢問「券商投資建議」與「券商分析師營收、盈餘預估」資料於投資記帳 App 中顯示之授權與報價

TEJ 台灣經濟新報 業務部 您好：

我們是 Forliosa（https://forliosa.trade）的開發團隊。Forliosa 是台灣的小型投資記帳 web app：使用者登入後記錄自己的台股、美股交易，查看持股、報酬與個股資訊，也可以問 App 裡的 AI 助理。目前只開放給少數註冊使用者（數十人以內，以親友為主），免費使用；之後計畫推出付費會員（屆時屬商業使用）。App 不提供下單，也不提供投資建議；畫面上每一筆資料都標示來源。

個股頁有一張「法人觀點」卡片，列出券商、投顧最近對這檔股票的評等與目標價。現在的資料是 AI 從公開新聞報導整理、附上原文連結。大型股還算完整，小型股常常找不到。因此想了解貴公司的資料能否以正式授權的方式使用。

**我們想使用的資料**

- 「券商投資建議」（SP）：券商名稱、報告日期、評等、目標價。
- 「券商分析師營收、盈餘預估」（PS）：各券商的 EPS、營收預估，以及共識值。
- 想先了解這兩張表實際有哪些欄位、每天什麼時候更新、用什麼方式取得（TEJ API 或檔案）。
- 也想確認：TQuant Lab 個人方案是否包含這兩張表？我們的理解是個人方案只限個人研究，不能顯示給 App 的使用者，對嗎？

**預計的用法與用量**

- 個股頁「法人觀點」卡片：每檔最多 8 筆（券商、日期、評等、目標價），標示「資料來源：TEJ」。
- AI 助理：使用者問「這檔有哪些法人的目標價」時，讀這些資料回答，並標示來源。
- 每天更新一次就夠，不需要即時。範圍是上市櫃全部個股；每天實際被查看的約 20–300 檔（估計）。
- 使用者目前數十人；開放註冊後第一年，預估數百到一千人（估計）。
- 不提供下載、不轉售、不提供 API 給第三方，也不拿資料訓練或微調任何 AI 模型。
- 取得書面同意前，我們不會以程式擷取貴公司網站。

**想請教的問題**

1. **顯示**：能不能在 App 裡顯示給登入的註冊使用者？之後開始收費（付費會員）時，條件或價格有沒有不同？
2. **券商名稱**：能不能逐筆顯示券商（投顧）的名稱、評等與目標價？還是只能顯示共識（例如平均目標價、家數）？
3. **保存**：能不能把資料存在我們的資料庫、保留歷史（例如畫出目標價的變化）？合約結束後要刪除到什麼程度？
4. **AI**：App 的 AI 助理能不能讀這些資料，並在回答裡引用（例如「某投顧 11/12 目標價 950 元，資料來源：TEJ」）？AI 由 Anthropic 的 Claude API 執行，產生回答時相關資料會送進該服務；我們不會用這些資料訓練或微調模型。
5. **涵蓋範圍**：上市、上櫃都有嗎？上櫃小型股的資料有多完整？能否提供 2330 台積電、2308 台達電、7799 禾榮科、6643 M31（上櫃）近 90 天的範例資料或筆數？
6. **標示**：來源要怎麼寫（文字、連結、標誌、免責聲明）？
7. **價格**：以上面的用量，費用與計價方式為何（月費或年費、按使用者數或按檔數）？有沒有試用？

若此詢問應改洽其他窗口，也請不吝告知。謝謝您撥冗回覆。

Forliosa 開發團隊　〔姓名〕〔電話（選填）〕

---

## 2. CMoney（全曜財經資訊）

- **寄到**：沒找到企業合作或資料授權的窗口。
  - 先寄客服 csservice@cmoney.com.tw，請他們轉給法人業務。來源：CMoney 自己的客服頁（網路搜尋），未查證。
  - 也可以從「投資決策支援系統」介紹頁找聯絡方式：https://www.cmoney.tw/app/itemcontent.aspx?id=1940
- **參考**：「法人目標價」功能的報導 https://money.udn.com/money/story/5607/9613288
- **給你**：不用附件（可附「法人觀點」卡片截圖）。客服信箱多半處理會員問題，所以信的第一句就請他們轉寄。一週沒回，打客服電話問「法人或資料授權的業務窗口」。

**收件人**：csservice@cmoney.com.tw
**主旨**：〔請轉法人業務〕詢問「法人目標價」資料於投資記帳 App 中顯示之授權與報價

CMoney 客服 您好：

這是一封企業資料授權的詢問。如果不是由客服處理，麻煩幫我們轉給負責法人或資料授權的同仁，謝謝。

我們是 Forliosa（https://forliosa.trade）的開發團隊。Forliosa 是台灣的小型投資記帳 web app：使用者登入後記錄自己的台股、美股交易，查看持股、報酬與個股資訊，也可以問 App 裡的 AI 助理。目前只開放給少數註冊使用者（數十人以內，以親友為主），免費使用；之後計畫推出付費會員（屆時屬商業使用）。App 不提供下單，也不提供投資建議；畫面上每一筆資料都標示來源。

個股頁有一張「法人觀點」卡片，列出券商、投顧最近對這檔股票的評等與目標價。現在的資料是 AI 從公開新聞報導整理、附上原文連結。大型股還算完整，上櫃小型股常常找不到。我們知道貴公司「籌碼K線」的「法人目標價」收錄了國內投顧的報告，因此想了解能否以正式授權的方式使用。

**我們想使用的資料**

- 「法人目標價」：各券商、投顧對個股的評等、目標價與報告日期，以及歷次的目標價。
- 只需要這些事實欄位，不需要報告摘要、準確度排名等貴公司自己撰寫或計算的內容。若這些也能一起授權，也想知道價格。
- 取得方式依貴公司指定（API 或每日檔案）。

**預計的用法與用量**

- 個股頁「法人觀點」卡片：每檔最多 8 筆（券商、日期、評等、目標價），標示「資料來源：CMoney」。
- AI 助理：使用者問「這檔有哪些法人的目標價」時，讀這些資料回答，並標示來源。
- 每天更新一次就夠，不需要即時。範圍是上市櫃全部個股；每天實際被查看的約 20–300 檔（估計）。
- 使用者目前數十人；開放註冊後第一年，預估數百到一千人（估計）。
- 不提供下載、不轉售、不提供 API 給第三方，也不拿資料訓練或微調任何 AI 模型。
- 取得書面同意前，我們不會以程式擷取貴公司網站或 App。

**想請教的問題**

1. **顯示**：能不能在 App 裡顯示給登入的註冊使用者？之後開始收費（付費會員）時，條件或價格有沒有不同？
2. **券商名稱**：能不能逐筆顯示券商（投顧）的名稱、評等與目標價？還是只能顯示共識（例如平均目標價、家數）？
3. **保存**：能不能把資料存在我們的資料庫、保留歷史（例如畫出目標價的變化）？合約結束後要刪除到什麼程度？
4. **AI**：App 的 AI 助理能不能讀這些資料，並在回答裡引用（例如「某投顧 11/12 目標價 950 元，資料來源：CMoney」）？AI 由 Anthropic 的 Claude API 執行，產生回答時相關資料會送進該服務；我們不會用這些資料訓練或微調模型。
5. **涵蓋範圍**：上市、上櫃都有嗎？上櫃小型股的資料有多完整？能否提供 2330 台積電、2308 台達電、7799 禾榮科、6643 M31（上櫃）近 90 天的範例資料或筆數？
6. **標示**：來源要怎麼寫（文字、連結、標誌、免責聲明）？
7. **價格**：以上面的用量，費用與計價方式為何（月費或年費、按使用者數或按檔數）？有沒有試用？

若此詢問應改洽其他窗口，也請不吝告知。謝謝您撥冗回覆。

Forliosa 開發團隊　〔姓名〕〔電話（選填）〕

---

## 3. 鉅亨（Anue，資料來自 FactSet）

- **寄到**：b2b-sales@anuegroup.com.tw。來源：鉅亨 OpenAPI 頁的公告「自 2026 年 1/1 不再提供免費申請 OPEN API 服務」附的窗口（https://openapi.api.cnyes.com/swagger-ui.html，搜尋摘要）。
- **參考**：
  - 「鉅亨速報－Factset 最新調查」範例：https://news.cnyes.com/news/id/6534591
  - 外資評等頁：https://www.cnyes.com/twstock/foreignrating.aspx?code=2344
  - 使用條款：https://www.cnyes.com/cnyes_about/cnyes_sos05.html
- **給你**：不用附件。對方如果說 FactSet 的資料不能轉授權，請他們給 FactSet 台灣的窗口，或說明要怎麼找 FactSet。

**收件人**：b2b-sales@anuegroup.com.tw
**主旨**：詢問 FactSet 共識預估與目標價（及台股新聞標題）於投資記帳 App 中顯示之授權與報價

鉅亨網 企業業務 您好：

我們是 Forliosa（https://forliosa.trade）的開發團隊。Forliosa 是台灣的小型投資記帳 web app：使用者登入後記錄自己的台股、美股交易，查看持股、報酬與個股資訊，也可以問 App 裡的 AI 助理。目前只開放給少數註冊使用者（數十人以內，以親友為主），免費使用；之後計畫推出付費會員（屆時屬商業使用）。App 不提供下單，也不提供投資建議；畫面上每一筆資料都標示來源。

個股頁有一張「法人觀點」卡片，列出券商最近對這檔股票的評等與目標價。現在的資料是 AI 從公開新聞報導整理、附上原文連結。我們看到貴網站「鉅亨速報－Factset 最新調查」有台股的共識預估與目標價；也看到貴公司的免費 OpenAPI 自 2026/1/1 起停止申請，因此來信詢問企業授權。

**我們想使用的資料**

1. FactSet 共識：EPS 預估（中位數、最高、最低）、分析師人數、平均或中位數目標價、評等分布、更新日期。台股為主，美股也想一併了解。
2. 若有逐家券商的評等與目標價，也想了解。
3. （選填）台股個股新聞的標題、時間與連結（不需要內文），用在個股頁「新聞報導」，連回貴網站原文。

**預計的用法與用量**

- 個股頁「法人觀點」卡片：顯示一行共識（例如「FactSet 調查：12 位分析師，目標價中位數 X 元」），標示「資料來源：鉅亨網／FactSet」。
- AI 助理：使用者問到這檔的共識預估或目標價時，讀這些資料回答，並標示來源。
- 每天更新一次就夠，不需要即時。範圍是上市櫃全部個股；每天實際被查看的約 20–300 檔（估計）。
- 使用者目前數十人；開放註冊後第一年，預估數百到一千人（估計）。
- 不提供下載、不轉售、不提供 API 給第三方，也不拿資料訓練或微調任何 AI 模型。
- 取得書面同意前，我們不會以程式擷取貴公司網站或未公開的 API。

**想請教的問題**

1. **顯示**：能不能在 App 裡顯示給登入的註冊使用者？之後開始收費（付費會員）時，條件或價格有沒有不同？貴公司是否有權把 FactSet 的資料轉授權給第三方 App 顯示？
2. **券商名稱**：只能顯示共識（家數、中位數）嗎？還是也能逐筆顯示券商名稱、評等與目標價？
3. **保存**：能不能把資料存在我們的資料庫、保留歷史（例如畫出共識目標價的變化）？合約結束後要刪除到什麼程度？
4. **AI**：App 的 AI 助理能不能讀這些資料，並在回答裡引用（例如「FactSet 調查 12 位分析師，目標價中位數 X 元，資料來源：鉅亨網」）？AI 由 Anthropic 的 Claude API 執行，產生回答時相關資料會送進該服務；我們不會用這些資料訓練或微調模型。
5. **涵蓋範圍**：台股有多少檔有 FactSet 共識？上櫃小型股有沒有？能否提供 2330 台積電、2308 台達電、7799 禾榮科、6643 M31（上櫃）的範例資料（沒有資料也請告知）？
6. **標示**：來源要怎麼寫（文字、連結、標誌、免責聲明）？
7. **價格**：以上面的用量，共識資料與（選填的）新聞標題各自的費用與計價方式為何？有沒有試用？

若此詢問應改洽其他窗口（例如 FactSet），也請不吝告知。謝謝您撥冗回覆。

Forliosa 開發團隊　〔姓名〕〔電話（選填）〕

---

## 4. 中央社（新聞企業授權）

- **寄到**：sales@cna.com.tw（事業部業務行銷中心：廣告、企業合作、新聞授權）；總機 02-2505-1180，分機 718、792、797、798。
  - 來源：`docs/research/news-and-external-sources.md` 的中央社一列，以及中央社聯絡頁 https://www.cna.com.tw/about/contact.aspx（搜尋摘要）。
- **參考**：
  - RSS 條款（只限個人、非營利）：https://www.cna.com.tw/about/rss.aspx
  - AskCNA 註冊條款：https://ask.cna.com.tw/ask/signup
  - 產品與服務（代理 AP、法新社、路透）：https://www.cna.com.tw/about/product.aspx
- **給你**：不用附件。對方如果推薦 AskCNA MCP 個人版（NT$200／月），回說要用在多人使用的 App，需要企業授權。

**收件人**：sales@cna.com.tw
**主旨**：詢問中央社財經新聞於投資記帳 App 中使用之企業授權與報價（含 AI 讀取）

中央通訊社 業務行銷中心 您好：

我們是 Forliosa（https://forliosa.trade）的開發團隊。Forliosa 是台灣的小型投資記帳 web app：使用者登入後記錄自己的台股、美股交易，查看持股、報酬與個股資訊，也可以問 App 裡的 AI 助理。目前只開放給少數註冊使用者（數十人以內，以親友為主），免費使用；之後計畫推出付費會員（屆時屬商業使用）。App 不提供下單，也不提供投資建議；畫面上每一筆資料都標示來源。

個股頁有「新聞報導」與「法人觀點」兩塊：新聞列出跟這檔股票有關的報導標題，連回媒體原文；法人觀點列出券商最近的評等與目標價，附上報導連結。我們希望加入中央社的財經報導（包括法說會與個股新聞）。我們看過貴社 RSS 的條款，只限個人、非營利使用；也看到 AskCNA 的個人方案不能用在多人使用的服務。因此來信詢問企業授權。

**我們想使用的內容**

1. 台股相關的財經報導：標題、發布時間、連結（連回中央社網站）。如果授權包含摘要，也想知道。
2. AI 讀取：使用者在 App 裡問個股問題時，AI 助理搜尋、閱讀中央社的報導（例如透過 AskCNA MCP 的企業方案），在回答裡引用並附上連結。
3. （選填）貴社代理的 AP、法新社、路透美股新聞，用在美股個股頁。

**預計的用法與用量**

- 個股頁「新聞報導」：只顯示標題、時間、「中央社」與連結，不顯示內文。
- 使用者持有或關注的個股約 100–300 檔；每檔每天取幾則相關報導。
- 使用者目前數十人；開放註冊後第一年，預估數百到一千人（估計）。
- 不轉載全文、不轉售，也不拿報導訓練或微調任何 AI 模型。
- 取得書面同意前，我們不會以程式擷取貴社網站。

**想請教的問題**

1. **顯示**：能不能在 App 裡顯示標題、時間與連結給登入的註冊使用者？之後開始收費（付費會員）時，條件或價格有沒有不同？如果要顯示摘要，條件為何？
2. **券商名稱**：報導常寫到券商名稱與目標價（例如「某外資調升台達電目標價」）。我們能不能把「券商、日期、目標價」這幾個事實整理成「法人觀點」卡片的一行，並附上中央社原文連結？
3. **保存**：我們把標題與連結存在資料庫 30 天（用來排序、去除重複）；「法人觀點」的一行最多保存 180 天。這樣可以嗎？能不能保存更久？
4. **AI**：AI 助理能不能讀中央社的報導、在回答裡引用並附上連結？是否要用 AskCNA MCP 的企業方案？AI 由 Anthropic 的 Claude API 執行，產生回答時相關內容會送進該服務；我們不會用這些內容訓練或微調模型。
5. **涵蓋範圍**：上市、上櫃個股（包括上櫃小型股）的報導量大概多少？能否提供 2330 台積電、2308 台達電、7799 禾榮科、6643 M31（上櫃）近 90 天的報導筆數或範例？
6. **標示**：來源要怎麼寫（「中央社」文字、連結、標誌）？
7. **價格**：以上面的用量，費用與計價方式為何？有沒有試用？

若此詢問應改洽其他窗口，也請不吝告知。謝謝您撥冗回覆。

Forliosa 開發團隊　〔姓名〕〔電話（選填）〕

---

## 5. Benzinga（美股評等與目標價）

- **寄到**：licensing@benzinga.com；電話 +1 877-440-9464。
  - 來源：Benzinga 文件的聯絡區（https://docs.benzinga.com/introduction/introduction，搜尋摘要）。
  - 備案：經 Massive 購買，寄 sales@massive.com（https://massive.com/partners/business-benzinga）。
- **參考**：https://www.benzinga.com/apis/analyst-ratings-api/ ；https://massive.com/docs/rest/partners/benzinga/analyst-ratings
- **給你**：不用附件。對方如果建議經 Massive 買，請他們把兩種買法的報價都給。

**To**: licensing@benzinga.com
**Subject**: Licensing and pricing enquiry: Analyst Ratings API for a small investment-ledger app

Hello Benzinga licensing team,

Forliosa (https://forliosa.trade) is a small investment-ledger web app based in Taiwan. Registered users log in to record their own Taiwan and US stock trades and see their holdings, returns and stock information, and they can ask an in-app AI assistant about their holdings. Today a few dozen registered users, mostly friends and family, use it free of charge. We plan to introduce paid membership plans. We do not offer trading, brokerage or investment advice, and we show the source of every number.

Each stock page has an "Analyst views" card that lists recent ratings and price targets from named firms. Today an AI assistant compiles it from public news articles, with links. For US stocks we would like to replace this with licensed data, and your Analyst Ratings API looks like the best fit.

**Data we are interested in**
- Analyst rating actions: date, firm, analyst, action (upgrade, downgrade, initiate, maintain), rating, and price target old → new.
- If available: consensus ratings and price-target consensus.
- US stocks only.

**Intended use and volume**
- The "Analyst views" card shows up to 8 recent actions per stock, labelled "Source: Benzinga".
- Our AI assistant reads the same rows when a user asks "what do analysts say about NVDA?" and cites Benzinga.
- About 100–300 US stocks and ETFs that our users hold or watch. One update a day is enough; we do not need real-time data.
- One to two years of history, for a simple ratings timeline. Well under 10,000 API calls a month.
- A few dozen users today; we estimate a few hundred to about a thousand in the first year after we open sign-ups.
- No downloads, no resale, and no API for third parties. We will never use the data to train or fine-tune AI models.

**Questions**
1. **Display**: May we show the data to logged-in registered users, and later to paying members? Do the terms or price change once we charge?
2. **Firm names**: May we show each action with the firm and analyst names and the price targets, or only consensus figures?
3. **Storage**: May we store the data in our database and keep history? What must we delete if the contract ends?
4. **AI**: May our AI assistant read the data and quote it in answers with attribution (for example, "Firm X raised its NVDA price target from $A to $B on Nov 12. Source: Benzinga")? The assistant runs on Anthropic's Claude API, so the relevant rows are sent to that service when an answer is generated. We do not use the data to train or fine-tune models.
5. **Coverage**: Could you share sample records for AAPL and NVDA from the last 90 days? Do you also cover TSM (TSMC's ADR) or any Taiwan-listed stocks?
6. **Attribution**: What attribution or notice do you require?
7. **Price**: What would this cost at our size, and is it different if we buy directly from Benzinga or through a partner such as Massive? Is there a trial?

Thank you for your time.

Best regards,
〔Name〕
Forliosa (https://forliosa.trade)

---

## 6. Financial Modeling Prep（FMP）

- **寄到**：info@financialmodelingprep.com，或聯絡表單 https://site.financialmodelingprep.com/contact。來源：FMP 聯絡頁（搜尋摘要）。
- **參考**：
  - 顯示要另簽協議的 FAQ：https://site.financialmodelingprep.com/insights/platform/can-you-use-fmp-data-in-a-public-app-website-or-client-dashboard
  - 商業方案：https://site.financialmodelingprep.com/pricing-plans?planType=commercial
  - TipRanks 資料集：https://site.financialmodelingprep.com/datasets/analyst-ratings-tipranks
- **給你**：用表單的話，把主旨貼在第一行。不要先買個人方案：個人方案不能用在 App。

**To**: info@financialmodelingprep.com
**Subject**: Data Display and Licensing Agreement enquiry: analyst price targets and grades in a small investment-ledger app

Hello FMP team,

Forliosa (https://forliosa.trade) is a small investment-ledger web app based in Taiwan. Registered users log in to record their own Taiwan and US stock trades and see their holdings, returns and stock information, and they can ask an in-app AI assistant about their holdings. Today a few dozen registered users, mostly friends and family, use it free of charge. We plan to introduce paid membership plans. We do not offer trading, brokerage or investment advice, and we show the source of every number.

Each stock page has an "Analyst views" card that lists recent ratings and price targets from named firms. Today an AI assistant compiles it from public news articles, with links. We understand from your FAQ that showing FMP data in an app needs a Data Display and Licensing Agreement, even on a free site, and that a personal plan does not cover it. So we are asking about that agreement before we sign up.

**Data we are interested in**
- Price targets by analyst and firm, and the price-target consensus (high, low, median, average).
- Grades (upgrades and downgrades) and the grades consensus.
- Analyst estimates (EPS and revenue).
- Possibly the TipRanks analyst-ratings dataset, and stock news.

**Intended use and volume**
- The "Analyst views" card shows up to 8 recent items per stock, labelled "Source: Financial Modeling Prep".
- Our AI assistant reads the same rows when a user asks about analyst views, and cites FMP.
- About 100–300 US stocks and ETFs that our users hold or watch; Taiwan stocks too, if you cover them. One update a day is enough; we do not need real-time data.
- One to two years of history. Well under 10,000 API calls a month.
- A few dozen users today; we estimate a few hundred to about a thousand in the first year after we open sign-ups.
- No downloads, no resale, and no API for third parties. We will never use the data to train or fine-tune AI models.

**Questions**
1. **Display**: Under the Data Display and Licensing Agreement, may we show the data to logged-in registered users, and later to paying members? Do the terms or price change once we charge?
2. **Firm names**: May we show each price target and grade with the firm and analyst names, or only consensus figures?
3. **Storage**: May we store the data in our database and keep history? What must we delete if the agreement ends?
4. **AI**: May our AI assistant read the data and quote it in answers with attribution? The assistant runs on Anthropic's Claude API, so the relevant rows are sent to that service when an answer is generated. We do not use the data to train or fine-tune models.
5. **Coverage**: Could you share sample price-target and grade records for AAPL and NVDA from the last 90 days? Do the analyst endpoints return data for Taiwan stocks such as 2330.TW (TSMC), 2308.TW (Delta Electronics), 7799.TW, or the TPEx small cap 6643.TWO?
6. **Attribution**: What attribution or notice do you require? Your TipRanks dataset page says the data "can be used for commercial purposes". Does showing it in our app still need the display agreement, and does TipRanks require its own attribution?
7. **Price**: What would the display agreement cost at our size? Is there a trial?

Thank you for your time.

Best regards,
〔Name〕
Forliosa (https://forliosa.trade)

---

## 7. Twelve Data

- **寄到**：業務表單 https://twelvedata.com/contact；或 support@twelvedata.com（客服信箱，不確定會不會轉業務）。來源：Twelve Data 定價頁與客服文章（搜尋摘要）。
- **參考**：
  - 商業方案：https://twelvedata.com/pricing-business
  - 商業與個人使用：https://support.twelvedata.com/en/articles/5332349-commercial-and-personal-usage
  - price_target 文件：https://twelvedata.com/docs/analysis/price-target
- **給你**：表單如果問公司規模，選最小的。不要先付費升級。它是表中唯一有公開價、而且含對外顯示的廠商（每月 US$149–499），所以這封主要是確認「哪一級才有分析資料」。

**To**: Twelve Data sales (contact form), or support@twelvedata.com
**Subject**: Business plan enquiry: analyst price targets and recommendations with external display

Hello Twelve Data team,

Forliosa (https://forliosa.trade) is a small investment-ledger web app based in Taiwan. Registered users log in to record their own Taiwan and US stock trades and see their holdings, returns and stock information, and they can ask an in-app AI assistant about their holdings. Today a few dozen registered users, mostly friends and family, use it free of charge. We plan to introduce paid membership plans. We do not offer trading, brokerage or investment advice, and we show the source of every number.

Each stock page has an "Analyst views" card that lists recent ratings and price targets. Today an AI assistant compiles it from public news articles, with links. Your business pricing page says business plans include external display, so we would like to confirm which plan fits before we subscribe.

**Data we are interested in**
- price_target (high, low, median, average) and recommendations (average and score).
- analyst_ratings (light or full), if they include firm names.
- earnings_estimate, if included.

**Intended use and volume**
- The "Analyst views" card shows the consensus target and recent ratings for each stock, labelled "Source: Twelve Data".
- Our AI assistant reads the same data when a user asks about analyst views, and cites Twelve Data.
- About 100–300 US stocks and ETFs that our users hold or watch; Taiwan stocks too, if you cover them. One update a day is enough; we do not need real-time data.
- A few dozen users today; we estimate a few hundred to about a thousand in the first year after we open sign-ups.
- No downloads, no resale, and no API for third parties. We will never use the data to train or fine-tune AI models.

**Questions**
1. **Display**: May we show the data to logged-in registered users, and later to paying members? Which business plan (Venture or Enterprise) unlocks the analysis endpoints above? Your documentation seems to differ on this.
2. **Firm names**: Does analyst_ratings include firm names, and may we show them? Or may we show only the consensus figures?
3. **Storage**: May we store the data in our database and keep history? What must we delete if we cancel?
4. **AI**: May our AI assistant read the data and quote it in answers with attribution? The assistant runs on Anthropic's Claude API, so the relevant data is sent to that service when an answer is generated. We do not use the data to train or fine-tune models.
5. **Coverage**: Could you share sample responses for AAPL and NVDA? Do the analysis endpoints return data for Taiwan stocks, such as 2330, 2308 and 7799 on TWSE, and 6643 on TPEx?
6. **Attribution**: What attribution or notice do you require?
7. **Price**: Which plan and price would cover this use? Is there a trial of the analysis endpoints?

Thank you for your time.

Best regards,
〔Name〕
Forliosa (https://forliosa.trade)

---

## 8. Brave（Search API 的新聞搜尋：保存權）

- **寄到**：searchapi-support@brave.com。來源：Brave Search API 說明頁，大型或客製需求（含儲存權）找這個信箱（搜尋摘要）。
- **參考**：
  - 條款（不能轉售；長期保存要另買「儲存權」）：https://api-dashboard.search.brave.com/terms-of-service
  - 新聞搜尋 API：https://api-dashboard.search.brave.com/api-reference/news/news_search/get
- **給你**：不用附件。對方如果問現在怎麼搜新聞，照實說：用 GDELT 和自架的搜尋，打算換成有正式授權的 API。這封的重點是第 3 題：存標題和網址 30 天，算不算要另外買的「保存」。

**To**: searchapi-support@brave.com
**Subject**: Search API (News) for a small investment app: storage rights for headline and URL rows

Hello Brave Search API team,

Forliosa (https://forliosa.trade) is a small investment-ledger web app based in Taiwan. Registered users log in to record their own Taiwan and US stock trades and see their holdings, returns and stock information, and they can ask an in-app AI assistant about their holdings. Today a few dozen registered users, mostly friends and family, use it free of charge. We plan to introduce paid membership plans. We do not offer trading, brokerage or investment advice, and we show the source of every number.

Each stock page has a "News" section: a list of recent headlines about that stock, each linking to the publisher's article. We are considering the Brave Search API news endpoint (country=TW, search_lang=zh-hant, and English for US stocks) to find these headlines. Your terms say that storing results needs a plan with storage rights, so we would like to check our case before we switch.

**How we would use the results**
- A background job queries the news endpoint for each tracked stock (for example "台達電 2308" or "NVIDIA stock").
- From each matching result we keep only four things: the headline, the outlet name, the publication time and the URL. We do not keep descriptions, snippets or thumbnails.
- We keep these rows in our news table for 30 days. We use them to remove duplicates, sort, and show the headline list. Each headline links to the publisher.
- Volume: roughly one query per tracked stock per day, for about 100–150 stocks today. That is about 3,000–5,000 queries a month at first, with a hard monthly cap in our code.
- No resale or redistribution of results, and no model training.

**Questions**
1. **Display**: May we show these headlines and links to logged-in registered users, and later to paying members? Which plan covers this?
2. **Headline text**: Headlines often name a brokerage and a price target (for example, "Goldman raises Delta Electronics target"). May we show the headline text as it is, or must we show it in a particular format?
3. **Storage**: Does keeping the headline, outlet, time and URL for 30 days count as "storing results" that needs a storage-rights plan? If it does, what does that plan cost at our volume? Would a shorter period, such as 7 days or 24 hours, be allowed without it?
4. **AI**: May our AI assistant read the results at query time (title and description) and cite them with links in an answer? The assistant runs on Anthropic's Claude API, so the results are sent to that service when an answer is generated. Does this need a different plan?
5. **Coverage**: Do you have any known limits for Traditional Chinese news from Taiwan? We will test queries for 2330 (TSMC), 2308 (Delta Electronics), 7799 and the TPEx small cap 6643 ourselves with the free credit, and AAPL and NVDA in English.
6. **Attribution**: What attribution do you require or recommend in the app?

Thank you for your time.

Best regards,
〔Name〕
Forliosa (https://forliosa.trade)

---

## 收到回覆後

| 回覆 | 要做的事 |
|---|---|
| 可以顯示，也有報價 | 回覆存檔（`docs/research/`）。我整理成比較表（價格、能顯示什麼、能不能給 AI 讀、台股有多完整），你再決定要不要付費（備忘錄第三階段）。**決定買了才改程式**：在 `datapolicy` 登記新資料集、「法人觀點」卡片標示新來源、AI 工具改讀新資料 |
| 只能顯示共識，不能逐家列出 | 卡片加一行共識（例如平均目標價、家數）；逐家的評等仍用 AI 搜新聞＋附出處 |
| 可以顯示，但不能給 AI 讀 | 只顯示在卡片；AI 工具不讀，回答時只說「請看個股頁的法人觀點」 |
| Brave：存標題和網址不算保存，或儲存權的價格可以接受 | 回來決定要不要把自架搜尋（SearXNG）換成 Brave API（決定 8 的第二步）。換的話照回覆的條件存（多久、存哪些欄位） |
| Brave：要另買儲存權，而且很貴 | 再請你選：維持現狀；或改成只在查詢當下用 Brave 的結果、不存 |
| 價格超出預算、不同意或沒有回覆 | 維持現在的做法：AI 搜新聞＋附出處，查不到時老實說，並附官方法說會連結 |
