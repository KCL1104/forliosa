# UI 重設計研究（第二輪）：持倉優先、親友群組、完整 AI

> 撰寫：2026-11-12（研究子代理）。用途：第二輪重設計討論材料。
> 範圍：只談**結構、導覽、AI 的位置與行為、群組、簡化手法**，不談色彩、字型等視覺風格。
>
> **這一輪的前提（產品負責人 2026-11-12 最新說法，覆蓋先前的選擇）**
> - 主軸是**持倉管理、分析、親友群組**，加上**完整的 AI**：AI 盡量替使用者做事，一律先出草稿、使用者確認才生效；手動操作保留。
> - 要**簡單**、**持倉優先**；不是行情或新聞產品。
> - 喜歡 Google Finance 的部分元素（左「清單」欄、中間內容、右側會隨頁面換建議的「研究」面板），但**不要照抄 Google 的格式**。
> - 看 Google Finance 時視線先到「自己的投資組合」，再到「AI 研究區問今天的問題」。**首頁不要 AI 每日簡報區塊。**
> - 不能像傳統券商或銀行，也不能像模板套出來的後台。
>
> **和第一輪的分工**：第一輪（[ui-redesign-research.md](ui-redesign-research.md)）已整理 Google Finance 的資訊架構、AI 在投資產品裡的放法（P1–P7）、「台灣預設」。本篇不重複，需要時寫「第一輪 P5」這類引用。
>
> **標示說明**（與第一輪相同）
> - 【事實】官方文件，或多個可靠來源一致的說法。
> - 【單一來源】只有一個來源，或來源是第三方評論、行銷頁、使用者貼文，未能交叉驗證。
> - 【記憶】研究者的印象，這次沒找到文件佐證。
> - 【推論】研究者自己的推論。第 5 節全部是推論。
> - **（舊）** 表示來源早於 2025 年。
>
> **研究限制**：WebFetch 在這個環境對 `www.getquin.com`、`linear.app`、`cdn.jsdelivr.net` 都解析失敗（網路政策擋住），之後就不再嘗試其他網域。下文所有內容來自搜尋引擎擷取的官方頁面摘要、媒體報導與使用者評論，**沒有實際操作任何一個 app**。各 app 的畫面配置多半來自說明頁摘要，細節可能和目前版本不同。若要逐畫面確認，需要開放這些網域，或請產品負責人提供截圖。

---

## 0. 一頁摘要

**1. 持倉型產品怎麼做到簡單**
- 首頁第一眼幾乎都是「**一個主數字＋一條走勢＋持股清單**」，沒有一個持倉型產品把市場概況放在第一屏。【推論，依據第 1 節】
- 簡化靠的是「**可以調整**」，不是「拿掉」：Sharesight 欄位可自選、圖表可隱藏，隱藏後版面自動變緊湊（2026-02、03）；Trade Republic 的圖表要按住才出現座標；Delta 搖一下手機就把金額換成百分比。【事實】
- Trading 212 在 2025-12 把持股藏到搜尋列後面、改成留白很大的泡泡卡片，被使用者抗議後宣布撤回。**簡化時不能把主數字或持股藏到下一層。**【事實】
- Wealthfolio 3.3 讓 AI 匯入的交易落在**和手動匯入同一個審核表格**裡。這是「草稿→確認」最好的參考做法。【單一來源】

**2. 親友小圈子**
- 公開的投資社群在退場或轉型：Public 在 2025-06 關掉社群動態，理由是 AI 已經能取代動態原本的用途；Commonstock 在 2023 年被 Yahoo 收購（舊）。Robinhood Social（2026-03 beta）是公開的交易者網路，不是親友圈。【事實／單一來源】
- 「**只顯示百分比**」是各家的共同語言：getquin 的追蹤者只看得到相對數字；Delta、Robinhood 小工具都有只顯示 % 的模式；Commensa 永遠不顯示金額。【事實／單一來源】
- Robinhood 的家庭中心（2026-03）讓使用者逐一選擇哪些帳戶給家人看，而且**家人不會知道哪些帳戶被隱藏**；官方的說法是「看得到不等於能操作」。【事實】
- 對 Forliosa 的意涵【推論】：群組的價值在於關係，不在於資訊。群組預設只顯示 %；排行榜可以關掉；用一張只含 % 的分享卡取代站內動態，方便貼到 LINE。

**3. AI 不只是側邊聊天**
- 2026 年的金融 AI 都是「AI 先準備、你按送出」：Wealthsimple Penny（2026-11-05）、Robinhood Cortex 的預填委託單、eToro Tori。【事實】
- 非金融工具裡最值得借的四個機制：
  - **建議貼在物件上，可以接受、拒絕或查看原因**（Linear）。
  - **AI 寫的字是灰色，你一編輯就變黑色**（Granola）。
  - **逐條核准修改提議**（Notion，2026-08）。
  - **回答用真正的介面元件呈現，可以展開成整頁**（ChatGPT Apps、Gemini Dynamic View）。
  【事實】
- 主動提醒應該**掛在相關的物件上，過時就消失**（ChatGPT Pulse 的卡片 24 小時後過期），不要做成首頁的簡報區塊。【推論】

**4. 四個結構概念**（第 5 節，全部是推論）

| 概念 | 一句話 | 版面 | AI 的位置 |
|---|---|---|---|
| **A 一本帳** | 首頁就是持倉帳本，AI 寫在每一列旁邊的「旁註」和灰色草稿列裡 | 單欄＋旁註，不是三欄 | 依附在每一列上 |
| **B 清單與焦點** | 左邊並列你的投資組合、群組、觀察；右邊顯示選中的那一個，頂端一條「問這個」 | 兩欄主從式 | 附在選中的物件上，回答在原地展開 |
| **C 說了就做** | 一個輸入框是主要操作方式；答案是可以釘選的 Forliosa 元件卡，釘選的卡組成首頁 | 單欄 | **AI 是主要操作方式** |
| **D 今天時間軸** | 左邊是持倉，右邊是以「今天」為中心的時間軸；AI 草稿放在事情發生的日期上 | 兩欄 | 放在時間上 |

---

## 1. 以持倉為主、介面簡單的產品

### 1.1 七個重點產品

#### getquin（德國：持倉追蹤＋社群＋AI）

- **首頁**：2.220.0 版的新首頁把五種內容合在一起：
  - AI 分析：列出能提高你「分數」的建議
  - 觀察清單
  - 支出
  - 建議
  - 社群動態
  淨資產區可以在投資組合和現金帳戶之間切換。【單一來源：[getquin 說明 13609828](https://help.getquin.com/en/articles/13609828)，未標日期，2026-11 透過搜尋讀取】
- **導覽**：底部 4 個分頁 Home／Net Worth／Analytics／Wealth。AI 對話原本是浮動按鈕，改版後移到 Wealth 分頁，而且需要付費訂閱 getquin Wealth。【單一來源：同上；[getquin Wealth 說明](https://help.getquin.com/en/articles/11706719-getquin-wealth)，未標日期】
- **AI**：
  - 「財務健康分數」由費用、分散度、風險曝險、目標一致性組成，使用者可以看到分數怎麼隨自己的動作變化。【單一來源：[Sagard 訪談](https://www.sagard.com/blog/2026/03/24/sagard-ai-x-getquin/)，2026-03-24】
  - 官網說分析涵蓋分散、風險、費用、總經四個面向，資料不會拿去訓練 AI。【事實：[getquin 投資組合分析頁](https://www.getquin.com/portfolio-analysis/)，未標日期】
  - 有使用者覺得 AI 分析「沒什麼新發現」。【單一來源：[Mustachian Post 論壇](https://forum.mustachianpost.com/t/anybody-knows-getquin/12355)，日期不明】
- **隱私**：
  - 公開檔案只顯示持股和**相對數值**（權重、報酬 %）。追蹤者看不到股數和投入金額。
  - 只有在你自己產生 dashboard 連結時，才能選擇要不要公開絕對金額。
  【事實：[getquin 隱私設定說明](https://help.getquin.com/en/articles/6817049-privacy-settings)，未標日期】
- **對 Forliosa 的意涵**【推論】：
  - 可以借：「分數＋可執行的建議」和「追蹤者只看相對數字」。
  - 方向相反：getquin 把社群動態放在首頁，把 AI 對話收進付費分頁。
  - 首頁一次塞五種內容，正好是產品負責人說「要簡單」的反例。

#### Sharesight（紐西蘭、澳洲：稅務算對的帳本，最接近 Forliosa「帳本」的定位）

- **Investments 分頁**：
  - 2026-02 把原本的 Overview 改名為 Investments，全面上線。新增圖表類型、可自訂欄位、可自訂日期區間、可加「平均買入價」欄。【事實：[Sharesight 2026-02 更新](https://www.sharesight.com/blog/sharesight-product-updates-february-2026/)】
  - 2026-03 依回饋調整：可以在「Edit table」隱藏 logo；隱藏圖表時版面自動變緊湊。【事實：[2026-03 更新](https://www.sharesight.com/blog/sharesight-product-updates-march-2026/)】
- **報表**：
  - Performance report 用 treemap 呈現各持股在一段期間內的表現，可以和超過 50 萬檔證券比較。【事實：[Sharesight 部落格](https://sharesight.com/blog/performance-report)，未標日期】
  - 2025 年新增三種報表：Drawdown Risk、Exposure（可看穿 ETF 成分）、重做的 Future Income（三年預估）。【單一來源：[Capitally 的評測](https://capitally-website.vercel.app/blog/sharesight-review)，競品撰寫】
- **導覽**：頂部導覽分成投資組合與報表兩層；交易和股利放在個別持股頁裡，不是頂層。【記憶；[help.sharesight.com 的頁面名稱](https://help.sharesight.com/portfolio-holding-page/) 與此一致】
- **AI**：2025-12 的更新頁連到一篇「Sharesight MCP AI portfolio story」；社群有人要求以唯讀方式把投資組合分享給 Perplexity、ChatGPT。【單一來源：[2025-12 更新](https://www.sharesight.com/blog/product-updates-december-2025/)只看到標題；[社群貼文](https://community.sharesight.com/t/portfolio-sharing-with-ai-tools-perplexity-chatgpt-etc/2116)】
  - 【推論】Sharesight 的方向是把帳本開放給外部 AI，而不是自己做 AI 介面。
- **對 Forliosa 的意涵**【推論】：Sharesight 用「欄位自選＋圖表可藏＋報表放另一層」維持密度又不雜亂，是最直接可以借的範例。

#### Snowball Analytics（以股利為核心）

- **導覽與首頁**：
  - 首頁是 Dashboard，快速看投資組合績效。
  - Analytics 底下分 Common、Dividends、Metrics 等分頁。
  - Report 從 Portfolio 選單或 Analytics 進入。
  【單一來源：[Snowball 概覽文](https://snowball-analytics.com/blog/snowball-analytics-overview)、[說明中心](https://help.snowball-analytics.com/)，未標日期】
- **持股表欄位**：股數、成本、市值、股利、殖利率、總損益、權重。【單一來源：同上】
- **股利**：
  - 有未來股利行事曆。
  - 「Dividend Rating」標示哪些公司比較可能維持配息、哪些可能減少或停發。
  【事實：[App Store 說明](https://apps.apple.com/app/snowball-analytics/id6463484375)，2025–2026】
  - 使用者稱讚 dashboard 好懂，也可以建立不同的 dashboard 版型。【單一來源：[Trustpilot](https://www.trustpilot.com/review/snowball-analytics.com?page=3)，2025】
- **痛點**：多則 2025 年評論說券商同步後數字錯誤或缺漏；官方回應是 SnapTrade（第三方同步服務）的問題。【單一來源：同上】
  - 【推論】資料錯一次，介面再簡單也沒用。對 Forliosa 來說，「數字先對」比畫面重要。
- **手機**：iOS、Android 都有桌面小工具顯示投資組合數字。【單一來源：[Snowball 部落格](https://snowball-analytics.com/blog/snowball-updates-introducing-the-report-ios-widgets-mobile-enhancements)】

#### Delta（eToro 旗下，以手機為主的多資產追蹤）

- **評價**：iOS 約 1.1 萬則評價，平均 4.7 顆星。【單一來源：[AppFollow](https://apps.appfollow.io/ios/delta-by-etoro/1288676542?country=us)，最後更新 2025-04】
  - eToro 在 2019 年收購 Delta。**（舊）**
- **導覽**：在投資組合畫面點左上角的漢堡選單，打開側欄切換投資組合；總值旁有「眼睛」可以隱藏金額。【事實：[Delta 支援頁](https://support.delta.app/en/articles/1467773-how-to-hide-your-balances)，未標日期】
- **簡化手法**：
  - 開啟設定後，**搖一下手機就把金額切換成百分比**。【事實：同上】
  - 總覽顯示價值與淨投入金額的走勢、簡單報酬率、淨現金流。
  - Portfolio Insights 模組（分散度、交易統計、交易所、市值）可依月、季、年查看。
  【事實：[Delta 功能頁](https://delta.app/en/features/track/portfolio-insights)】
- **限制**：Mac 版不能新增帳戶，只能在手機上加。【單一來源：[MacHow2](https://machow2.com/delta-investment-tracker-review/)，日期不明】
- **對 Forliosa 的意涵**【推論】：「一個動作就換成只看 %」很適合 Forliosa 的隱私模式，因為使用者常截圖傳到 LINE。

#### Kubera（淨資產追蹤）

- **介面像試算表**：資產頁預設有「投資／不動產／其他」幾張工作表，可以新增、改名、排序，表內再分區塊。【單一來源：[WalletHacks 2026 評測](https://wallethacks.com/kubera-review/)等多篇評測】
- **Dashboard 與 Recap**：
  - Dashboard 一眼看到總資產、負債、淨值。
  - Recap 看資產成長和配置。
  - 可以把某張工作表的折線圖「加到 Dashboard」，首頁內容由使用者自己決定。
  【事實：[Kubera 說明：自訂 Dashboard](https://help.kubera.com/article/100-customize-the-dashboard-add-remove-and-rearrange-the-charts)，未標日期】
- **評價**：「跟試算表一樣簡單，但資料會自動更新」；沒有預算功能；價格偏高（約每年 US$150–249，各來源說法不同）。【單一來源：評測】
- **對 Forliosa 的意涵**【推論】：「一張表＋分區小計」比「多個頁籤」簡單；首頁要釘哪些圖，可以交給使用者。

#### Wealthfolio（開源，有桌面版與行動版，強調隱私；AGPL，只參考，不複製程式碼）

- **2.x**：
  - 2.0 加入行動版和 Docker 部署。【單一來源：[Show HN](https://hn.svelte.dev/item/46006016)，約 2025 下半年，依貼文編號推估】
  - 2.1 加入可調整的導覽，以及 dashboard 的「前幾大持股」小工具。【單一來源：[v2.1.0 版本說明](https://newreleases.io/project/github/afadil/wealthfolio/release/v2.1.0)彙整】
- **3.x**：
  - 3.3 把 dashboard 的前幾大持股從 5 檔增加到 7 檔。
  - 3.5.3 在帳戶頁加入 Activities 分頁，可以在表格裡直接編輯、刪除。
  【單一來源：[v3.3.0](https://newreleases.io/project/github/afadil/wealthfolio/release/v3.3.0)、[v3.5.3](https://newreleases.io/project/github/wealthfolio/wealthfolio/release/v3.5.3) 版本說明彙整，2026，日期未確認】
- **AI**：
  - 3.0 內建對話助理，可以**用自然語言記交易**、在對話裡匯入 CSV；支援本機 Ollama 和多家雲端模型。【單一來源：[v3.0.0](https://newreleases.io/project/github/afadil/wealthfolio/release/v3.0.0)】
  - 3.3 起，**AI 在對話中匯入時，用的是和手動匯入精靈同一個審核表格**，可以批次略過或強制匯入。
  - 3.3 起，AI 也能讀 Health Center（資料問題清單），引導使用者修正。
  【單一來源：v3.3.0 版本說明】
- **導覽**：側欄 Dashboard／Holdings／Performance／Activities／Settings。【記憶】
- **對 Forliosa 的意涵**【推論】：
  - AI 草稿和手動操作共用同一個確認畫面，使用者只要學一次。
  - Health Center 這種「帳本健康清單」很適合 Forliosa 的對帳。

#### Trade Republic（德國券商：兩個大分頁加左右滑動）

- **分頁**：新設計把錢分成 **Wealth（投資）** 和 **Cash（現金）**，兩者加總的總額放在左上頭像進入的 Profile 裡。三個畫面用左右滑動切換。【事實：[官方說明：新設計](https://support.traderepublic.com/en-sk/1602-What-has-changed-in-the-new-app-design-)、[官方說明：新 Profile](https://support.traderepublic.com/en-gr/2904-What-has-changed-in-the-new-Profile)，未標日期】
- **圖表**：**按住圖表才會顯示歷史數值、參考線和座標軸**；另外有紅綠色的「績效模式」。【事實：同上】
- **其他**：
  - 交易時間軸移到 Cash 底下的 Transactions。
  - 搜尋放在 Browse 裡，搜尋列在畫面底部。
  【事實：同上】
- **評價**：
  - 有德國媒體說新設計「表面更簡單，用起來更麻煩」。【單一來源：[mobiflip](https://www.mobiflip.de/shortnews/verschlimmbessert-trade-republic-hat-ein-neues-design/amp/)，日期不明】
  - 2023 年改版時被批評沒有選單、圖表難懂。【單一來源：[basic thinking 2023-09](https://www.basicthinking.de/blog/2023/09/18/trade-republic-vergrault-kunden-mit-neuer-app/) **（舊）**】
- **對 Forliosa 的意涵**【推論】：
  - 可以借：「按住才出現座標」能讓圖表保持乾淨。
  - 要避免：總額收在頭像裡，違反 Forliosa「一眼看懂今天」的原則。

### 1.2 其他值得一看的產品

- **Copilot Money**：
  - 投資分頁頂部是所選期間的報酬和漲跌最多的持股，配置圖在持股清單上方。【單一來源：[Money with Katie](https://moneywithkatie.com/how-im-using-copilots-new-investments-feature-to-understand-my-performance/)，Web 版推出前寫的】
  - 2025-12 推出 Web 版，設計和 iOS 很像，但評測說在手機瀏覽器上不方便。【單一來源：[9to5Mac 2026-01-01](https://9to5mac.com/2026/01/01/copilot-money-brings-clarity-to-your-finances-now-on-the-web/)、[Copilot 說明](https://help.copilot.money/en/articles/11780342-copilot-money-for-web)】
  - 【推論】手機網頁要當成主要平台來設計，不能只是把桌面版縮小。
- **Wealthsimple**：
  - 2025-09 改成三個主分頁：Home（跨帳戶總財富）、Spend、Invest。【單一來源：[iPhone in Canada 2025-09-25](https://www.iphoneincanada.ca/2025/09/25/wealthsimple-ends-1-debit-cash-back-heres-what-you-get-instead/)】
  - 2026-11-05 宣布 2027 年初推出重寫的 app：**首頁可以依淨資產、投資績效或支出自訂**；可以**釘選持股**；滑一下就能下單。【事實：[iPhone in Canada 2026-11-05](https://www.iphoneincanada.ca/2026/11/05/wealthsimple-fey-uikit-trading-app-sneak-peek/)、[Wealth Professional](https://www.wealthprofessional.ca/news/industry-news/wealthsimple-launches-ai-assistant-penny-in-sweeping-product-push/393960)】
  - 2025-08 收購以「清楚、簡單」著稱的研究工具 Fey。【事實：[BetaKit 2025-08](https://betakit.com/wealthsimple-acquires-fey-to-bolster-its-investment-research-capabilities/)】
- **Capital.com**（2026-05 上線）：
  - 公司說新 app 的每個元素都用同一個問題檢驗：「能不能幫客戶在行動前理解自己的部位？」不能就拿掉。
  - 首頁把部位、自選、行情合在一個畫面。
  【單一來源：公司說法，[Finance Magnates 2026-06-01](https://www.financemagnates.com/forex/brokers/capitalcom-rebuilds-its-trading-app-around-slower-decisions/)】
- **Simply Wall St**：
  - 2026-02 推出「Portfolio Command Center」，把績效、風險、機會放在同一處。【事實：[官方 What's New](https://support.simplywall.st/hc/en-us/articles/7894830045199)】
  - 「Portfolio Snowflake」把各持股的基本面依權重合成一個圖形。【事實：[官方說明](https://support.simplywall.st/hc/en-us/articles/360001740916)】
  - 【推論】合成成一個圖形是很強的簡化，但也可能過度簡化，所以要能展開看組成。
- **Ghostfolio**（開源）：
  - 有 **Zen Mode**，只看重點、沒有干擾。
  - 有 X-ray，依可調整的規則檢查集中度、資產類別失衡等問題。
  【單一來源：[README 鏡像](https://cdn.jsdelivr.net/gh/ghostfolio/ghostfolio@main/README.md)、第三方介紹】
- **Finary**（法國）：
  - 2025-12 重做預算功能，官方說是為「稅務與 AI agent」打底。【事實：[Finary 2025-12 更新](https://finary.com/en/product-updates/december-2025)】
  - 2026 年股東信提到 AI 理財夥伴「Guidance」。【事實：[股東信](https://finary.com/en/product-updates/shareholder-letter-2026)】
- **Apple 股市**：沒有找到持股功能，仍然是報價、自選、新聞。【單一來源：搜尋結果，2026】
  - 獨立 app Summit 主打「一個簡單的 dashboard：全部投資、價值走勢、今日變動」。【單一來源：[9to5Mac 2026-02-21](https://9to5mac.com/2026/02/21/indie-app-spotlight-summit-stock-portfolio-tracker/)】
- **Stock Events**：用「事件行事曆」（財報、除息、配息）組織持股，有桌面小工具和到價提醒。【單一來源：[App Store](https://apps.apple.com/us/app/-/id1488720155)，部分商店頁面是 2024 年的 **（舊）**】

### 1.3 反例：Trading 212（2025）

- **2025 年初的首頁改版**：
  - 自選清單收進畫面底部的抽屜，要往上拉才展開。
  - 使用者抱怨往下滑時一半機率會把整個抽屜拉下來，而且一次能看到的清單變少。
  - 官方建議改用「Advanced view」。
  【事實：[官方社群公告](https://community.trading212.com/t/your-home-screen-just-got-a-new-look/87886)，2025】
- **2025-12 的投資組合改版**：
  - 改成圓角泡泡卡片和上拉選單，**持股藏到搜尋列後面**，顯示的資訊變少。
  - 使用者大量抗議，有人揚言換券商。
  - 官方 2025-12-24 宣布 2026-01 恢復舊版；沒有查到後來是否真的恢復。
  【事實：[Finance Magnates 2025-12](https://www.financemagnates.com/forex/brokers/trading-212-reverses-interface-redesign-users-warn-theyll-switch-brokers-its-like-youre-intentionally-trying-to-anger-users)、[官方社群](https://community.trading212.com/t/portfolio-redesign-update/89501)】
- 【推論】當「簡單」被做成「藏起來、多點一下、留白很大」，重視持倉的使用者會反彈。Forliosa 的簡單應該是**內容種類少，但數字不少**。

### 1.4 小結【推論】

1. **首頁**：持倉型產品的第一屏是「主數字＋走勢＋持股」，沒有市場概況。
2. **導覽**：頂層通常只有 3–5 個目的地。**交易紀錄很少是頂層**，通常放在帳戶或個別持股底下（Trade Republic、Wealthfolio 3.5、Sharesight）。
3. **股利**：通常做成「行事曆」或「未來收入」（Snowball、Sharesight Future Income、Stock Events），而不只是一張表。
4. **簡化手法**：欄位可選、圖表可藏、首頁可自訂、按住才出現細節、一鍵換成百分比。
5. **失敗的簡化**：把主數字或持股藏到下一層，例如 Trade Republic 的總額收在頭像裡、Trading 212 的持股藏在搜尋後面。

---

## 2. 親友小圈子的社交投資

### 2.1 公開社群在退場或轉型

- **Public**：2025-06 關閉社群動態和社交交易。理由是動態原本的主要用途（分享法說會重點、每日市場更新）已經由 AI 工具 Alpha 和 Generated Assets 取代。【事實：[Finance Magnates 2025-06](https://www.financemagnates.com/forex/publiccom-terminates-social-trading/)，引用 Public 的「Sunsetting Social」文章】
- **Commonstock**：以券商帳戶驗證身分的投資社群，2023-08 被 Yahoo 收購，要整合進 Yahoo Finance。沒找到獨立 app 的現況。【單一來源：[Dealroom](https://app.dealroom.co/companies/commonstock) **（舊）**】
- **Robinhood Social**：
  - 2025-09-10 宣布，2026-03-18 開始限量 beta。
  - 以 KYC 驗證身分，交易和損益經過驗證。
  - **個人檔案必須顯示績效統計**。
  - 可以手動照著別人下單，但不能設定自動跟單。
  【事實：[Robinhood newsroom 2026-03-18](https://robinhood.com/us/en/newsroom/robinhood-social-beta)、[Fortune 2026-03-18](https://fortune.com/2026/03/18/robinhood-rolls-out-long-awaited-social-feature-to-let-users-track-and-copy-other-traders/)、[Robinhood 說明：Social](https://robinhood.com/us/en/support/articles/social-trading/)】
  - 這是公開的交易者網路，不是親友圈。
- **eToro**：2026-07-07 推出的新 app 主打「AI-first, smart and social」。【事實：[eToro 新聞稿](https://www.etoro.com/news-and-analysis/press-releases/etoro-launches-new-app-ai-first-smart-and-social/)】
  - 搜尋摘要中有一篇報導提到可以和朋友討論策略的「Circles」，但找不到原文。【單一來源，未能確認】
- **Blossom**（加拿大）：
  - 連結券商帳戶驗證持股，使用者以化名分享。
  - App Store 頁面標示「Apple 2025 年度 Top 25 App」。【事實：[App Store](https://apps.apple.com/us/app/blossom-social-investing/id1592237485)】
  - 有評測說分享的是實際金額，不只是百分比。【單一來源：[Milesopedia](https://milesopedia.com/en/personal-finance/investing/review-application-blossom-social/)，日期不明】

### 2.2 小圈子與家人

- **Robinhood 家庭中心**（2026-03-04 宣布，年內陸續推出）：
  - 使用者**逐一選擇哪些帳戶給家人看，以及哪些帳戶（如果有）讓家人操作**。
  - **家人不會知道哪些帳戶被隱藏了。**
  - 官方的說法是「看得到不等於能操作」。
  【事實：[Robinhood newsroom 2026-03-04](https://robinhood.com/us/en/newsroom/robinhood-unveils-the-future-of-family-finance-at-robinhood-presents-take-flight)、[Axios 2026-03-05](https://www.axios.com/2026/03/05/robinhood-prediction-markets)】
- **Commensa**（個人的小專案）：
  - 只分享百分比，網站上寫「永遠不顯示金額：不顯示你持有什麼、付了多少、有多少錢」。
  - 只能用邀請連結加入，沒有公開檔案、探索功能、追蹤者。
  - **一進來看到的不是排行榜**，而是「朋友最近做了什麼」。
  - 數字全部手動輸入。
  【單一來源：[Commensa 官網自述](https://commensa.wolschon.dedyn.io/en)，日期不明】
- **私人群組類 app**：
  - Waddle：私人群組、朋友交易時通知、每日漲跌最多的人。
  - Sirius 的 Pods：和群組聊天綁在一起比報酬。
  - Blotta：連結券商、驗證交易、排行榜。
  【單一來源：[Waddle](https://www.producthunt.com/posts/waddle)、[Sirius](https://apps.apple.com/us/app/id6762199450)、[Blotta](https://www.producthunt.com/products/blotta) 的商店或 Product Hunt 頁面，日期不明】
  - 這類 app 規模都小，沒有找到成效資料。
- **台灣**：
  - 台股記帳 App 大多是個人用途。「存股筆記」可以分開記錄自己和家人的帳戶，但不是互相分享。【單一來源：[App Store](https://apps.apple.com/tw/app/%E5%AD%98%E8%82%A1%E7%AD%86%E8%A8%98/id6747595539)，2025–2026】
  - 社群仍以公開社團為主（見第一輪第 3 節）。

### 2.3 隱私控制的做法

| 做法 | 產品 | 驗證程度 |
|---|---|---|
| 追蹤者只看得到相對數值（權重、報酬 %）；金額要另外選擇才公開 | getquin | 事實（官方說明） |
| 分享連結預設關閉；可以隱藏金額只剩 %；可以加密碼 | Parqet（[舊說明頁](https://help-en.portfoliodividendtracker.com/article/149-share-your-portfolio)） | 單一來源 |
| 一鍵或搖一下手機，把金額換成 % | Delta | 事實（支援頁） |
| 桌面小工具「只顯示百分比」 | Robinhood iOS 小工具（[說明](https://www.robinhood.com/gb/en/support/articles/ios-widgets/)） | 事實 |
| 逐一選擇哪些帳戶給家人看；被隱藏的帳戶家人不知道 | Robinhood 家庭中心 | 事實 |
| 永遠只有 %、邀請制、入口不是排行榜 | Commensa | 單一來源 |
| 個人檔案必須顯示績效 | Robinhood Social | 事實 |
| 分享實際金額 | Blossom | 單一來源 |

### 2.4 什麼有效、什麼失敗【推論】

1. **群組的價值在關係，不在資訊。** 公開動態的資訊價值正在被 AI 取代，Public 已經明說。親友群組的價值是一起看、互相打氣、聊同一檔股票。
2. **百分比是預設的語言。** getquin、Delta、Parqet、Commensa、Robinhood 小工具都把「只看 %」做成一級選項。Forliosa spec 的四個分享開關（預設只開「報酬率 %」）方向一致。
3. **排行榜有好有壞。** Commensa 刻意不把排行榜放在入口。家人群組（長輩、配偶）要的是安心，不是比輸贏。建議：
   - 排行榜讓群組擁有者可以關掉。
   - 群組首頁預設顯示「大家這個月的 %」和「共同持股」。
4. **不要讓人看出誰隱藏了什麼。** 參考 Robinhood 家庭中心：群組裡只顯示成員有分享的部分，不要出現「某某未分享持股」這類標籤。
5. **用分享卡取代站內動態。** 台灣使用者會截圖到 LINE，與其做站內動態，不如一鍵產生「只含 % 的分享卡」（圖片或連結）。
   - LINE Notify 已在 2025-03-31 停止服務【記憶】，所以推播仍走 spec 的 Telegram、Discord；LINE 只用在「分享出去」。
6. **群組不必獨立成長。** 私人群組 app 很多，但都做不大。群組在 Forliosa 只是一個目的地，靠持倉帳本把人帶進來。

---

## 3. AI 原生互動：不只是側邊聊天

### 3.1 金融產品：第一輪之後的新資訊

- **Robinhood Cortex Assistant**：
  - 2026 年初推出第一版，可以回答持股問題、做研究、下單、帶你到某個頁面、回答客服問題，也會監控可能影響你持股的新聞。【事實：[Robinhood Cortex 說明](https://robinhood.com/us/en/support/articles/cortex/)】
  - 下單時會帶出**預先填好的委託單**，最後一步一定要使用者確認。【事實：[Cortex 揭露文件](https://cdn.robinhood.com/assets/robinhood/legal/cortex_assistant_disclosure.pdf)】
  - 工程部落格提到，後來從十個專門 agent 改成單一 agent，所有工具集中在一處定義。【單一來源：[Robinhood 工程部落格 2026-08-25](https://robinhood.com/us/en/careers/blog/loop-stays-dumb-so-the-model-can-be-smart/)，只讀到摘要】
  - 2026-06 擴大到投資顧問，官方說已有超過一百萬名散戶用過 Cortex。【事實：[InvestmentNews 2026-06](https://www.investmentnews.com/transformation/robinhood-brings-ai-powered-cortex-to-rias-on-tradepmr/266861)】
- **Wealthsimple Penny**（2026-11-05 宣布）：
  - 可以**準備**轉帳、匯款、股票交易、退休帳戶提撥規劃、付帳單，也會找出重複刷卡、做再平衡。
  - **沒有使用者確認，不會動錢也不會下單**。官方原話是「按下送出只有使用者能做」。
  - 不連外部網路。預計 2026 年底或 2027 年初全面開放。
  【事實：[MoneySense](https://www.moneysense.ca/news/wealthsimple-launches-ai-banking-assistant-that-can-help-move-money-place-trades/)、[BetaKit](https://betakit.com/wealthsimple-unveils-ai-assistant-and-major-product-expansion-in-latest-showcase/)，皆 2026-11-05】
- **eToro Tori**（2026-07-07）：
  - 主動推送持股更新、市場訊號、漲跌原因。
  - 可以在 WhatsApp、Telegram、Apple Watch 上使用；交易需要使用者核准。
  【事實：[eToro 新聞稿](https://www.etoro.com/news-and-analysis/press-releases/etoro-launches-new-app-ai-first-smart-and-social/)、[MarketBeat 2026-07-10](https://www.marketbeat.com/instant-alerts/etoro-group-unveils-ai-trading-push-with-tori-agent-new-app-and-desktop-platform-2026-07-10/)】
  - 現有客戶從 2026-10-04 起移到新 app。【事實：[Finance Magnates 2026-09](https://www.financemagnates.com/forex/brokers/etoro-to-move-existing-clients-to-ai-centred-app-from-4-october/)】
- **Revolut AIR**（2026-04-09）：
  - 介面是對話，加上建議問題、語音輸入、附件。
  - 敏感動作要用生物辨識確認。
  - 不保留對話紀錄，只讀使用者本來就看得到的資料。
  【單一來源：[Craft Innovations UX 分析](https://craftinnovations.global/revolut-air-ux-analysis/)（顧問公司行銷文）、[Crowdfund Insider 2026-04](https://www.crowdfundinsider.com/2026/04/272459-digital-bank-revolut-introduces-ai-tools-to-streamline-money-management/)】
- **Perplexity Finance Portfolio**：
  - 2026-03 開始透過 Plaid 連結券商帳戶，持股、餘額、交易資料可以用在對話裡。【事實：[Plaid 部落格](https://plaid.com/blog/powering-intellligent-finance-with-perplexity/)】
  - 2026-04-09 擴大到銀行、信用卡、貸款。【單一來源】
- **Fiscal.ai**：每個回答都附引用；2026-05 加入券商連線。【單一來源：[WallStreetZen 評測](https://www.wallstreetzen.com/blog/finchat-io-fiscal-ai-review/)】
- **getquin**：把 AI 對話從浮動按鈕移到一個分頁（見 1.1）。
  - 【推論】浮在畫面角落的「AI 泡泡」可能不是好入口。

### 3.2 非金融工具

- **Linear**：
  - Triage Intelligence（2025-08 預覽）在 issue 上顯示建議，包括團隊、負責人、標籤、可能重複的 issue。使用者可以**接受、拒絕，或滑過去看「為什麼這樣建議」**。
  - 2025-09 起可以設定某些屬性自動套用，例如「團隊和負責人自動套用，標籤只有 bug 自動套用」。
  【事實：[Linear 文件](https://linear.app/docs/triage-intelligence)、[changelog 2025-08-14](https://linear.app/changelog/2025-08-14-product-intelligence-technology-preview)】
  - Linear Agent（2026-03-24）：桌面版右下角或按 ⌘J 打開對話，也可以在任何留言裡 @Linear。2026-04-30 起可以操作 issue 草稿；對話可以開成最大化的覆蓋層。【事實：[changelog 2026-03-24](https://linear.app/changelog/2026-03-24-introducing-linear-agent)、[2026-04-30](https://linear.app/changelog/2026-04-30-releases)】
- **Notion**：
  - 3.0（2025-09-18）的 agent 可以連續執行多個步驟，最長約 20 分鐘，所有改動都能復原。【事實：[the-decoder](https://the-decoder.com/notion-3-0-introduces-ai-agents-for-documents-workflows-and-team-automation/)】
  - 2026-08-28 起 agent 可以**只「提議修改」，由使用者由上到下逐條核准**；核准前頁面不會變。【事實：[Notion 版本說明 2026-08-28](https://www.notion.com/releases/2026-08-28)】
- **Superhuman**：
  - Email Assistant 會自動分類郵件、**用你的語氣先寫好回覆，放在草稿匣**，也會提醒你還沒回的信。
  - 不會自動寄出。
  【事實：[Superhuman 說明](https://help.superhuman.com/hc/en-us/articles/40144492186515)、[官方部落格](https://blog.superhuman.com/introducing-email-assistant/)】
- **Granola**：
  - 你打的字是黑色，AI 補的字是灰色；**你一編輯灰字，它就變成黑色，代表你認領了這段內容**。
  - AI 補的每一點都連回逐字稿裡的原處。
  【事實：[Granola 發表文](https://granola.ai/blog/announcement) 2024-05 **（舊）**、[說明文件](https://www.granola.ai/docs/docs/101/afteryourmeeting/editing-your-enhanced-notes)】
- **Dia 瀏覽器**（The Browser Company，2025-06 beta；2025-09 宣布被 Atlassian 收購）：
  - 側欄對話自動知道你正在看哪個分頁，也可以 @ 其他分頁一起問。
  - Skills 是存起來的提示，可以用快捷鍵或斜線指令在任何頁面觸發。
  【事實：[TidBITS 2025-06-20](https://tidbits.com/2025/06/20/dia-browser-debuts-with-contextual-ai-chat-but-arc-users-feel-left-behind/)、[Thurrott](https://www.thurrott.com/cloud/web-browsers/322287/the-browser-company-explains-its-vision-for-dia)】
- **Raycast**：
  - AI Extensions（2025-02-26）讓你在 Quick AI 或 AI Chat 裡打 @ 叫出工具，AI 自己決定要用哪個工具、帶什麼參數。
  - Quick AI 只處理一次性問答，要追問才進入完整對話。
  - 2026 年起，@ 選單依「常用＋最近」排序。
  【事實：[Raycast 1.93](https://www.raycast.com/changelog/1-93-0)、[Raycast 手冊](https://manual.raycast.com/ai-extensions)】
- **ChatGPT Pulse**（2025-09 預覽）：
  - 夜間整理，早上給 5–10 張卡片。
  - **卡片 24 小時後過期，除非你存起來。**
  【單一來源組合：[eWeek](https://www.eweek.com/news/openai-chatgpt-pulse/) 等報導】
  - 產品負責人不要首頁簡報，這裡只借用「會過期」這個機制。
- **ChatGPT Apps（Apps SDK）**：
  - 互動元件有三種顯示方式：對話中的 inline 卡片（輕量操作）、fullscreen（需要大空間的工作，原本的輸入框仍在）、PiP（捲動時固定在畫面上）。
  - 指南特別說明不要用 fullscreen 把整個 app 重做一遍。
  【事實：[OpenAI UI 指南](https://developers.openai.com/apps-sdk/concepts/ui-guidelines)、[設計指南](https://developers.openai.com/apps-sdk/concepts/design-guidelines)，未標日期；Apps SDK 2025-10 推出【記憶】】
- **Gemini 3 的生成式介面**（2025-11-18）：
  - Dynamic View 依照提問即時產生一個互動頁面。
  - Visual Layout 產生雜誌式版面，可以用滑桿和篩選器調整結果。
  【事實：[Google 部落格](https://blog.google/products-and-platforms/products/gemini/gemini-3-gemini-app/)、[9to5Google](https://9to5google.com/2025/11/18/gemini-3-launch/)】
- **人機協作的設計文章**（2026，多半是業者部落格）：
  - 只在「錯了代價很高」的地方要求核准；唯讀或容易復原的動作直接做。
  - 核准畫面要顯示「實際會執行的動作」，不能只給摘要。
  - 低風險的動作可以用「事後可以復原」取代「事前核准」，也可以批次核准。
  【單一來源組合：[Kanerika](https://kanerika.com/blogs/human-in-the-loop-ai-agents/)、[Kunal Ganglani](https://www.kunalganglani.com/blog/tool-approval-patterns-ai-agents)、[Agentic Wire](https://www.agenticwire.news/article/agent-ux-design-patterns)（引用 NN/g）】
- **SAP Fiori 的可解釋 AI 指南**：解釋要分層。先是一個小指示，點開是精簡說明（彈出框或原地展開），再往下才是完整細節。【事實：[SAP 設計系統](https://www.sap.com/design-system/fiori-design-web/v1-145/foundations/ai-and-joule-design/guidelines/explainable-ai-building-explanations)，依版本更新】

### 3.3 讓 AI「做得多又不吵」的十個模式

| # | 模式 | 例子 | Forliosa 可以怎麼用【推論】 |
|---|---|---|---|
| M1 | **建議貼在物件上**，不放在側欄 | Linear 的 triage 建議、Granola 的灰字、Google 圖表上的 key moments（第一輪 P3） | 在持股列、總數字、除息日旁邊放一則短短的「旁註」，可以接受、拒絕、看原因 |
| M2 | **AI 和手動共用一個審核畫面** | Wealthfolio 3.3：AI 匯入用的是手動精靈的審核表 | AI 記的交易、匯入的對帳單、配息入帳，全部進入同一個「交易草稿表」 |
| M3 | **標示是誰寫的** | Granola：黑字是你、灰字是 AI，編輯就算你的 | AI 建立的列是灰色，確認後變成正式列；交易列表保留「由 AI 建立」標示 |
| M4 | **提議修改，逐條核准** | Notion 的提議修改、Superhuman 的草稿匣 | 對帳時 AI 一次提出 12 筆修正，使用者由上到下逐筆確認或全部確認 |
| M5 | **依風險分級處理動作** | 人機協作文章、Linear 的自動套用 | 唯讀動作直接做；寫入帳本要確認；分享和權限永遠手動；使用者可以自己開「某一類自動套用」（見 3.4） |
| M6 | **@ 提及與技能** | Raycast 的 @、Dia 的 @ 分頁和 Skills、Linear 的 @Linear | 輸入 `@00878`、`@家人群`、`/健檢`、`/對帳`；常用的提示可以存成按鈕 |
| M7 | **回答用真正的介面元件** | ChatGPT Apps 的 inline 和 fullscreen、Gemini Dynamic View、Claude 的 Artifacts【記憶】 | 回答用 Forliosa 自己的持股表、交易草稿、河流圖呈現，不用 markdown 表格；可以「展開成整頁」或「釘選」 |
| M8 | **主動提醒會過期** | ChatGPT Pulse 的 24 小時過期、eToro Tori | 提醒掛在相關的列上（例如 00878 旁邊寫「11/18 除息」），過了日期就消失；**不做首頁簡報區塊** |
| M9 | **背景任務** | Notion agent 最長約 20 分鐘、Linear Agent、Google Finance 的 tasks（第一輪 P6） | 「整理這份 PDF 對帳單」在背景執行，完成後變成一批草稿等你確認 |
| M10 | **多種管道與語音** | Revolut AIR 的語音、Tori 在 WhatsApp 和 Telegram 上、Wealthsimple Penny | 手機輸入框支援語音（照顧長輩）；Telegram、Discord 推播附一個「回 app 確認」的連結，**確認一律在 app 內完成** |

### 3.4 「完整 AI」的動作分級【推論，對應 PRODUCT.md 原則 6】

| 類別 | 例子 | AI 能做到哪裡 | 誰確認、怎麼確認 | 事後 |
|---|---|---|---|---|
| 讀取與回答 | 問答、解釋數字、比較 | 直接做 | 不需要確認 | — |
| 改變畫面 | 篩選、排序、切換成 %、展開績效 | 直接做 | 不需要確認 | 一鍵還原 |
| 寫入帳本 | 記交易、配息入帳、匯入、修正成本、拆股與配股 | **只產生草稿** | 逐筆或批次確認（畫面顯示稅費、資料來源與時間） | 標示「由 AI 建立」，可以復原 |
| 建立任務或警示 | 到價提醒、除息前提醒、每週健檢 | 產生草稿 | 確認 | 可以停用 |
| 分享與群組 | 分享卡、群組分享開關、授權他人查看 | 只準備預覽，或帶你到設定頁 | **使用者自己在設定頁手動完成** | — |
| 刪除 | 刪除交易、退出群組 | 不讓 AI 做 | 手動 | 刪除交易可以從垃圾桶復原 |
| 使用者主動開的自動套用 | 定期定額每月入帳 | 照使用者訂的規則自動執行 | 規則建立時確認一次 | 每一筆都標示，可以復原 |

---

## 4. 讓密集資料看起來簡單的技巧

1. **一個主數字，其他都降一級。**
   - Vanguard 的新首頁把帳戶餘額當成第一件事。【單一來源：[NN/g 案例](https://www.nngroup.com/articles/vanguard-mobile-app/)，日期未確認，可能早於 2025】
   - Copilot 把所選期間的報酬放在頂部（見 1.2）。
2. **持股永遠在第一屏，不要藏起來。** 反例是 Trading 212（見 1.3）。
3. **用分區和小計，代替多個頁籤。** 例如 Kubera 的工作表與區塊、Trade Republic 把投資和現金分開。
4. **欄位可以自選，圖表可以隱藏，隱藏後自動變緊湊。** Sharesight 2026-02 和 2026-03 的更新就是這樣做。
5. **細節按住才出現。** 例如 Trade Republic 的圖表座標軸。
6. **分層揭露：數字 → 一句話 → 細節。**
   - 參考：[NN/g 漸進揭露](https://www.nngroup.com/articles/progressive-disclosure/) **（舊，2006）**、SAP Fiori 的分層解釋、[LogRocket 2025-03](https://blog.logrocket.com/ux-design/progressive-disclosure-ux-types-use-cases)。
   - 也見第一輪 4.4 的「數字加一句話」。
7. **用一個合成指標，但要能展開看組成。** 例如 Simply Wall St 的 Snowflake、getquin 的分數。
8. **每個元素都要通過同一個問題。** Capital.com 的問題是「能不能幫客戶在行動前理解自己的部位」。
   - Forliosa 可以用：「它有沒有讓我知道自己的錢現在怎樣，以及下一步要不要做什麼？」【推論】
9. **讓使用者自訂首頁，而不是做簡易版和專業版兩套。** 例如 Wealthsimple 2027 年的自訂首頁、Wealthfolio 的可調整導覽。
   - 對照：台灣的元大「簡易版」（第一輪第 3 節）、Trading 212 的 Standard 與 Advanced 兩種檢視，都是分成兩套。
10. **百分比模式本身就是一種簡化。** 例如 Delta 搖一下手機、Robinhood 小工具的只顯示 %。截圖分享時尤其有用。
11. **一個「只看重點」的開關。** 例如 Ghostfolio 的 Zen Mode。
12. **依時間和狀態換內容。** 盤中、收盤後、除權息季該顯示的不一樣，不需要永遠顯示全部。【推論】
13. **三種最有效的策略：依情境調整介面、漸進揭露、以任務為中心。** 這是一家顧問公司分析 50 多個銀行和金融科技產品後的結論。【單一來源：[Mark's Web](https://markswebb.com/insights/information-overload-in-ux/)，日期不明】

---

## 5. 結構概念（本節全部是推論）

### 5.0 四個概念的共同前提

- **視線順序**：先看投資組合，再問今天的問題。所以每個概念的第一屏都把主數字和持股放在最上面，輸入框放在第二眼會看到的位置。
- **首頁沒有 AI 簡報區塊。** 主動的內容只掛在相關的物件上（M1、M8）。
- **AI 寫入帳本一律先產生草稿**（3.4）；分享和權限設定永遠手動。
- **群組預設只顯示 %**（2.4）。
- **保留 ⌘K 和所有手動入口。**
- **四個概念都不是三欄。** 只有 B 在把對話固定在旁邊時才會暫時變成三欄。
- **線框圖例**：
  - 數字是示意，取自 mock 示範資料的大小。
  - 中文字以兩格寬繪製。
  - `░…░` 是 AI 草稿；`┊` 是旁註；`◐` 是隱私模式；`●` 是頭像。

### 5.1 概念 A「一本帳」：首頁就是帳本，AI 寫在旁註裡

**一句話**：打開就是持倉帳本。AI 不放在側欄，而是寫在每一列旁邊的「旁註」，以及帳本裡的灰色草稿列。

**導覽**
- **桌面**：頂列只有兩個目的地「帳本、群組」，加上輸入框（搜尋、提問、下指令，⌘K）、隱私切換、頭像（設定、帳戶、匯入紀錄）。
  - 個股頁不是目的地，從帳本點某一列進入。
  - 觀察清單是帳本最下面的一個分區（參考 Kubera 的區塊）。
- **手機**：頂部切換「帳本｜群組」，底部固定輸入框（方便單手）。沒有底部分頁列。

**桌面第一屏，由上而下**
1. **頂列**：如上。
2. **主數字列**：
   - 總資產是唯一的大字，旁邊是今日損益和一條迷你走勢。
   - 點主數字會在原地展開績效（TWR、XIRR、和 0050 比較、最大回撤），再點一次收起。績效因此不需要頁籤。
3. **帳本主欄**（約三分之二寬）：
   - 依帳戶或依類別分區，每區有小計；欄位可以自選（參考 Sharesight）。
   - 檢視切換只有「持倉、交易、股利」三個。
4. **旁註欄**（約三分之一寬）：
   - 沒有外框、沒有對話紀錄，只有和帳本列對齊的灰色短註。
   - 每頁最多同時顯示 3 則，其他收成「還有 2 則」。
   - 最上面放 1 個和這頁有關的建議問題。
5. **草稿列**：AI 或匯入產生的交易，以灰底列出現在帳本中正確的位置，列尾有「確認、修改、刪除」。
6. **觀察分區**：只顯示價格和漲跌，沒有數量。

**手機第一屏**
- 主數字和今日損益。
- 持股清單：有旁註的列會出現一個小圓點，點一下在該列下方展開一行說明。
- 草稿列、觀察分區。
- 底部輸入框，可以附加檔案、用語音。

**分析在哪裡**
- 點主數字，在原地展開績效。
- 點持股列，進入個股頁，個股頁也用「內容＋旁註」的格式。
- 「股利」檢視裡有股利行事曆和未來收入。

**AI 在哪裡、怎麼做**
- **輸入框**：
  - 輸入代號：打開個股頁。
  - 輸入問句：答案以旁註出現在相關的列旁邊，或出現在旁註欄頂部。
  - 長答案或多輪對話：旁註欄變成全高的「筆記」覆蓋層（⌘J），關掉就回到帳本。
- **依頁面換內容**：
  - 帳本頁：每一檔今天貢獻多少、即將發生的事件。
  - 個股頁：旁註貼在「我的部位」「河流圖位置」「月營收」旁邊。
  - 群組頁：旁註貼在成員列旁邊，例如「三個人都持有 00878」。
- **草稿**：用 M2 和 M3。確認後灰色列變成正式列，列尾留一個「AI」小標，可以復原。
- **為什麼**：點任何數字，旁註就出現分層的解釋。

**群組**
- 「群組」是第二個目的地，用同樣的帳本格式：
  - 每一列是一位成員：今日、本月、今年 %，以及共同持股。
  - 旁註放留言和群組 AI 週報。
- 帳本上有「群組視角」開關。打開後：
  - 每一檔持股多一欄淡色字，例如「家人群 3 人持有」。
  - 旁註顯示群組對這一檔的留言，只有在對方有分享持股時才出現。

**桌面線框**

```text
┌────────────────────────────────────────────────┐
│ Forliosa  帳本  群組   [搜尋・提問・指令 ⌘K] ◐●│
├────────────────────────────────────────────────┤
│ 總資產 NT$4,812,300  今日 ▲51,100 +1.07% ╱╲╱   │
│ 持倉 · 交易 · 股利              旁註（AI）     │
│ 台積電   3張 3,255,000 ▲1.4%  ┊ 近九成漲幅靠它 │
│ 0050    12張   868,800 ▲0.8%  ┊   為什麼？ ›   │
│ 00878   10張   228,600 ▼0.2%  ┊ 11/18 除息     │
│ ░草稿 買0050 2張 稅費206░     ┊ 確認 修改 刪   │
│ ── 觀察 ──────────────────    ┊                │
│ 聯發科   —      觀察中 ▲0.8%  ┊ 問：股利夠繳   │
│                               ┊ 　　保費嗎？   │
└────────────────────────────────────────────────┘
```

**手機線框**

```text
┌──────────────────────────┐
│ 帳本 | 群組          ◐ ● │
│ NT$4,812,300             │
│ 今日 ▲51,100  +1.07%     │
├──────────────────────────┤
│ 台積電  3,255,000 ▲1.4% •│
│   └ 近九成漲幅來自它 ›   │
│ 0050      868,800 ▲0.8%  │
│ 00878     228,600 ▼0.2% •│
│ ░草稿 買0050 2張 [確認]░ │
│ ── 觀察 ──               │
│ 聯發科       觀察中 ▲0.8%│
│ [問或下指令…    附件 說] │
└──────────────────────────┘
```

**借鑑**
- Kubera：表格加分區。
- Sharesight：欄位自選、圖表可藏。
- Granola：灰字和黑字代表作者。
- Linear：建議可以接受、拒絕、看原因。
- Wealthfolio 3.3：AI 和手動用同一個審核表。
- Google 文件的邊欄留言【記憶】。
- Delta：一鍵換成 %。

**和 Google Finance 不同**
- 沒有常駐的 AI 欄，也沒有左側清單欄、沒有市場區塊。
- AI 依附在每一列上，不是另一欄聊天。
- 首頁就是持股表本身；Google 是「大數字＋圖表＋頁籤＋表格」。

**和台灣預設不同**：沒有報價表首頁，沒有底部五個分頁，沒有一排頁籤；AI 不是角落的按鈕。

**取捨**
- **優點**：
  - 最持倉優先，也最簡單（只有 2 個目的地）。
  - AI 的存在感來自具體的列，不像聊天機器人。
  - M4 之前最容易先做規則版：每檔貢獻多少、除息提醒、交易草稿都不需要語言模型。
- **缺點**：
  - 旁註需要寬度。螢幕寬度約 1200px 以下時要收成小圓點。
  - 排序、捲動、虛擬列表時，要讓旁註對齊對應的列，工程上不容易。
  - 旁註太多會變吵，數量要有嚴格上限。
  - 長對話是次要入口，喜歡研究的使用者會覺得 AI 被藏起來了。
  - 「旁註」對一般使用者是新概念，需要引導。

### 5.2 概念 B「清單與焦點」：兩欄主從式，AI 附在選中的物件上

**一句話**：左邊永遠是「你的東西」，也就是投資組合、各個群組、觀察清單並列；右邊是選中的那一個。AI 是焦點頂端的一條「問這個」，回答在原地展開，不是第三欄。

**導覽**
- **桌面**：
  - 左欄（約 220px）本身就是導覽：
    - 投資組合：全部，以及各個帳戶。每列顯示總值和今日 %。
    - 群組：每列顯示「你本月第幾名」或群組今日 %。
    - 觀察。
  - 左欄底部是頭像和設定。沒有頂部分頁，⌘K 仍然可用。
- **手機**：
  - 打開 app 直接是「全部投資組合」，維持持倉優先。
  - 左上角「‹清單」回到清單畫面，像郵件 app 的信箱列表；清單畫面上帳戶和群組並列。

**桌面第一屏**
1. **左欄清單**：如上。
2. **焦點頂部**：物件名稱、主數字、今日損益、走勢圖（可切換期間）。
3. **「問這個」列**：
   - 一個輸入框，最多 3 個建議問題，最多 2 個動作（例如記一筆、匯入）。
   - 建議會依物件類型改變。
   - 回答在這一列下方展開，可以收合；按「⌘J」開成完整對話。
4. **焦點內容**：持股、交易、股利、績效四個檢視；選的是群組時換成群組自己的檢視。

**手機第一屏**
- 打開就是「全部投資組合」的焦點畫面，由上而下是：主數字、今日損益、走勢、「問這個」和建議、持股表。
- 最下面一列是群組的摘要（例如「家人群：你本月第 2」），點了直接進入群組。

**分析在哪裡**
- 焦點裡的「績效」檢視：TWR、XIRR、和 0050 比較、回撤。
- 個股頁：從持股列點進去，是焦點的下一層，不是新的目的地。

**AI**
- 每個物件都有自己的「問這個」，自動帶入目前的物件、檢視、篩選。
- 草稿以卡片出現在「問這個」下方；確認後，表格中的新列會短暫標示出來。
- ⌘J 打開全螢幕對話，參考 Linear Agent 的最大化覆蓋層；裡面也有對話紀錄和任務。

**群組**
- 群組在清單中和投資組合同一層級。
- 選中群組時，焦點顯示：排行（可以關掉）、共同持股、成員的交易動態（有分享才顯示）、留言。
- 「問這個」換成群組相關的問題，例如「這週大家共同持有什麼？」。
- 群組 AI 週報是群組焦點裡的一張卡，不推到個人首頁。

**桌面線框**

```text
┌────────────┬───────────────────────────────────┐
│ 投資組合   │ 全部投資組合                      │
│ ▸全部 4.8M │ NT$4,812,300  今日 ▲51,100        │
│  永豐 3.6M │ ──╱╲──╱──────────── 1月 1年       │
│  國泰 1.2M │ [問這個…] 誰影響最大·配息         │
│ 群組       │ ┊AI：近九成來自台積電… ⌘J         │
│  家人  第2 │ 持股  交易  股利  績效            │
│  同學  第5 │ 台積電   3張 3,255,000 ▲1.4%      │
│ 觀察       │ 0050    12張   868,800 ▲0.8%      │
│  自選 8檔  │ 00878   10張   228,600 ▼0.2%      │
│ ● 設定     │ ░草稿 買0050 2張 [確認]░          │
└────────────┴───────────────────────────────────┘
```

**手機線框**

```text
┌──────────────────────────┐
│ ‹清單   全部投資組合   ● │
│ NT$4,812,300             │
│ 今日 ▲51,100  +1.07%     │
│ ──╱╲──╱──────────        │
│ [問這個…]                │
│ 誰影響最大·配息·記一筆   │
├──────────────────────────┤
│ 持股  交易  股利  績效   │
│ 台積電  3,255,000 ▲1.4%  │
│ 0050      868,800 ▲0.8%  │
│ 00878     228,600 ▼0.2%  │
│ 家人群：你本月第 2  ›    │
└──────────────────────────┘
```

**借鑑**
- Apple Mail、Finder 的主從式介面【記憶】。
- Google Finance 的左側清單（產品負責人的截圖），但內容換成「我的帳戶和群組」。
- Linear Agent 的 ⌘J 覆蓋層（2026-03）。
- Trade Republic 把投資和現金分開：每個帳戶就是一份清單。
- Wealthsimple 的釘選持股、自訂首頁（2026-11）。

**和 Google Finance 不同**
- 兩欄，不是三欄。
- AI 附在物件上、在原地展開，不佔一整欄的寬度。
- 左欄放的是我的帳戶和群組，不是市場類股。
- 群組和投資組合同一層級。

**和台灣預設不同**：沒有行情和下單；不同券商的帳戶並列在一起。

**取捨**
- **優點**：
  - 最容易理解，幾乎每個人都用過郵件類 app。
  - 帳戶和群組變多時，可以自然擴充。
  - 最接近產品負責人喜歡的 Google 版面，討論起來最快。
- **缺點**：
  - 最像 Google，也最容易做成產品負責人不要的「SaaS 後台」樣子，必須靠內容和視覺來避免。
  - 只有一個帳戶的使用者，左欄會很空。
  - 手機上從清單進入焦點多一層。
  - 回答在原地展開時，會把下方內容往下推。

### 5.3 概念 C「說了就做」：用輸入框操作，AI 是主要方式

**一句話**：主要的操作方式是一個輸入框。AI 用 Forliosa 自己的元件（持股表、交易草稿、圖表）回答，答案卡可以釘選，而**釘選的卡片組成你的首頁**。

**導覽**
- 沒有傳統導覽，畫面由上到下分成四塊：
  1. **主數字列**：永遠在最上面。
  2. **釘選板**：預設只釘了「持股」卡。
  3. **工作區**：最近的答案卡。沒有釘選的卡，24 小時後收進「紀錄」。
  4. **輸入框**：在最下面，附帶依情境變化的建議按鈕。
- 輔助入口只有四個：釘選、紀錄（對話、任務、AI 做過的事）、@群組、頭像。
- **手機**：同樣的結構直向排列，像訊息 app。
  - 輸入框在拇指容易按到的位置。
  - 可以附加檔案（拍對帳單、截圖），也可以用語音。

**桌面第一屏，由上而下**（單欄，最寬約 760px，置中）
1. **主數字列**：總資產、今日損益。
2. **釘選板**：預設只有「持股」卡，顯示前幾檔，可以展開全部。
3. **工作區**：最近的答案卡和草稿卡，例如一張交易草稿。
4. **建議按鈕**：依目前選中的卡片改變。
5. **輸入框**：可以附加檔案、用語音。

**手機第一屏**：主數字、持股卡、最近一張草稿卡、建議按鈕、輸入框。

**分析在哪裡**
- 用問的：例如「今年報酬跟 0050 比如何」會產生績效卡，可以展開成整頁或釘到首頁。
- 個股頁是「個股卡」展開成的整頁。

**AI**
- **辨別你要做什麼**：
  - 輸入代號：出現個股卡。
  - 輸入問句：出現答案卡。
  - 輸入動作：出現草稿卡，依 3.4 的分級處理。
  - 丟入檔案：出現匯入預覽卡。
- **卡片的三種大小**（參考 ChatGPT Apps）：
  - 對話中的一般卡片。
  - 展開成整頁：例如要對 50 筆交易時，用整頁表格。
  - 釘選到首頁。
- **依情境變化**：
  - 建議按鈕依「目前選中的卡片」改變。例如點了持股卡裡的 00878，按鈕變成「00878 何時除息」「加碼試算」。
  - 可以用 @ 提到股票、帳戶、群組。
- **技能**：常用指令存成技能，例如 /健檢、/對帳、/月報（參考 Dia 的 Skills）。
- **手動**：每張卡都有手動按鈕，例如持股卡上的「＋記一筆」；設定在頭像選單裡。

**群組**
- 輸入「@家人群」叫出群組卡；群組卡也可以釘在首頁。
- 「把這張卡分享到家人群」時，AI 產生一張只有 % 的預覽，並標出哪些內容會被遮掉。
- **分享設定本身只能手動調整。**

**桌面線框**

```text
┌────────────────────────────────────────────────┐
│ Forliosa         釘選  紀錄  @群組       ◐ ●   │
│ NT$4,812,300   今日 ▲51,100  +1.07%            │
│ ┌ 持股（釘選）───────────────────────────────┐ │
│ │ 台積電 ▲1.4%  0050 ▲0.8%  00878 ▼0.2%      │ │
│ │ 0056 ▲0.1%    AAPL ▲0.6%  …共9檔 展開      │ │
│ └────────────────────────────────────────────┘ │
│ ┌ AI 草稿（你說：買了0050兩張72.4）──────────┐ │
│ │ 買 0050 2張 @72.4  手續費206  證交稅0      │ │
│ │ [確認入帳] [修改] [取消]   怎麼算的 ⌄      │ │
│ └────────────────────────────────────────────┘ │
│ 試試：誰影響最大 · 匯入對帳單 · @家人群        │
│ [說或打字：搜尋、提問、下指令…   附件  說]     │
└────────────────────────────────────────────────┘
```

**手機線框**

```text
┌──────────────────────────┐
│ NT$4,812,300 ▲1.07%   ●  │
│ ┌持股（釘選）──────────┐ │
│ │台積電▲1.4% 0050▲0.8% │ │
│ │00878▼0.2% …9檔 展開  │ │
│ └──────────────────────┘ │
│       你：買0050兩張72.4 │
│ ┌AI草稿────────────────┐ │
│ │買0050 2張@72.4 費206 │ │
│ │[確認] [修改]  怎麼算 │ │
│ └──────────────────────┘ │
│ 誰影響最大·對帳單·@家人  │
│ [說或打字…    附件  說]  │
└──────────────────────────┘
```

**借鑑**
- ChatGPT Apps 的 inline 和 fullscreen、Gemini Dynamic View、Claude 的 Artifacts【記憶】。
- Raycast 的 @、Dia 的 Skills。
- Revolut AIR：用對話取代多步驟導覽，支援語音。
- Wealthsimple Penny：AI 準備好，使用者按送出。
- ChatGPT Pulse：卡片會過期。

**和 Google Finance 不同**：Google 的 AI 在內容旁邊；這裡內容由 AI 產生，再由使用者收藏成首頁。完全沒有市場內容。

**和台灣預設不同**：沒有分頁也沒有報價表，完全相反。

**取捨**
- **優點**：
  - 最符合「AI 盡量替你做事」，AI 就是主要的操作方式。
  - 畫面元素最少。
  - 每個人的首頁都不一樣，因為是自己釘出來的。
- **缺點**：
  - 不好發現能做什麼。不知道該問什麼的家人（尤其長輩）會卡住，一定要有建議按鈕和範例。
  - M4 之前沒有語言模型，要先做規則版的指令解析。「買 0050 2 張 72.4」這種指令可以用規則解析，問句不行。
  - 每次互動都有 AI 成本。
  - 判斷錯使用者要做什麼，會傷害信任。
  - 容易讓人覺得只是「套了 ChatGPT 的殼」。
  - Revolut AIR 被批評「只有一條對話串，看不到其他功能」，這裡也會遇到。
  - 對帳、整理歷史交易這類大量表格工作，卡片不如整頁表格好用，所以「展開成整頁」一定要做好。
  - 釘選板可能越釘越亂。

### 5.4 概念 D「今天時間軸」：帳本放在時間上

**一句話**：左邊是某一天的持倉；右邊是以「今天」為中心的時間軸，上面是已經發生的事（交易、配息），下面是接下來的事（除息、入帳、警示、AI 排程）。AI 草稿就放在事情發生的那一天。

**導覽**
- **桌面**：
  - 頂列有「帳本、群組」和輸入框。
  - 主數字列裡的走勢圖可以拖曳：拖到某一天，左邊的持倉變成那天的快照，右邊的時間軸也捲到那一天。
  - 「紀錄」（AI 對話和任務）放在頭像選單或輸入框旁邊。
- **手機**：
  - 底部三個分頁「帳本、群組、紀錄」，加上頭像。
  - 帳本頁上方是主數字和前幾檔持股，下方是時間軸，順序是「今天 → 接下來 → 最近」。

**桌面第一屏**
1. **頂列**：帳本、群組、輸入框、隱私切換、頭像。
2. **主數字列**：總資產、今日損益，以及可以拖曳的走勢圖。
3. **左欄（約 40%）**：所選日期的持倉。預設是今天，最下面是群組分享狀態。
4. **右欄（約 60%）**：時間軸，由上而下是「最近」「今天」（含輸入框）「接下來」。草稿和排程任務都在「接下來」裡。

**手機第一屏**：主數字、可拖曳的走勢、前幾檔持股、「今天」輸入框、接下來、最近，底部三個分頁。

**分析在哪裡**
- 拖曳走勢圖，可以看任一天的持倉。
- 點主數字，展開績效（TWR、XIRR、和 0050 比較、回撤）。
- 個股頁從持倉列進入；個股頁裡也有一條這一檔自己的時間軸（買賣、除息、配息）。

**AI**
- **輸入框**：放在時間軸「今天」那一格，頂列也有一個。
- **草稿和日期綁在一起**：
  - AI 從配息公告推算出「12/15 00878 配息入帳 5,500」的草稿，到那一天提醒你確認。
  - 匯入的對帳單交易出現在各自的日期，成為一串待確認的草稿。
- **為什麼**：走勢圖上大漲大跌的日子，時間軸上會有對應的事件（交易、除息、AI 說明）。概念類似 Google 的 key moments，但以「我的事件」為主。
- **任務**：排程任務是時間軸未來的一列固定項目，例如「每週五 盤後健檢」。
- **依時間和狀態變化的建議**：
  - 除息季：「這個月會入帳多少？」
  - 月底：「本月成績單」

**群組**
- 群組頁也是時間軸：成員分享的交易動態、群組週報、大家共同持股的除息日。
- 個人帳本可以疊加一條「家人群」軌道，預設關閉。

**桌面線框**

```text
┌────────────────────────────────────────────────┐
│ 帳本  群組   [搜尋・提問・指令 ⌘K]       ◐ ●   │
│ NT$4,812,300 ▲1.07%  ──╱╲──╱──●── 拖曳看過去   │
├─────────────────────┬──────────────────────────┤
│ 持倉（11/12）       │ 最近                     │
│ 台積電  3張 ▲1.4%   │ 11/05 買 0050 2張        │
│ 0050   12張 ▲0.8%   │ 08/13 0050 配息 +11,400  │
│ 00878  10張 ▼0.2%   │ ● 今天 [問或下指令…]     │
│ 0056    5張 ▲0.1%   │ 接下來                   │
│ AAPL   20股 ▲0.6%   │ 11/18 00878 除息 估5,500 │
│ …共 9 檔            │ ░12/15 配息入帳草稿 確認 │
│ 家人群：分享 %      │ 每週五 盤後健檢（任務）  │
└─────────────────────┴──────────────────────────┘
```

**手機線框**

```text
┌──────────────────────────┐
│ NT$4,812,300  ▲1.07%  ●  │
│ ──╱╲──╱──●  拖曳看過去   │
│ 台積電▲1.4%  0050▲0.8%   │
│ 00878▼0.2%  全部9檔 ›    │
│ ● 今天 [問或下指令…]     │
│ 接下來                   │
│ 11/18 00878除息 估5,500  │
│ ░12/15 入帳草稿 [確認]   │
│ 最近                     │
│ 11/05 買 0050 2張        │
├──────────────────────────┤
│  帳本   群組   紀錄   ●  │
└──────────────────────────┘
```

**借鑑**
- Stock Events：用事件行事曆組織持股。
- Trade Republic：Cash 底下的時間軸。
- Sharesight：Future Income 和自訂日期區間。
- Snowball：股利行事曆。
- Google 的 key moments 和 tasks（第一輪）。

**和 Google Finance 不同**：Google 投資組合有「持有資產、洞察資訊、交易、事件」四個頁籤，這裡合成一條時間軸；也沒有市場新聞流。

**和台灣預設不同**：台灣券商的帳務只看庫存和未實現損益，看不到「接下來會發生什麼」。

**取捨**
- **優點**：
  - 最貼近台股持有人的節奏：除權息、配息入帳、二代健保、股東會。
  - 對帳很自然，因為帳本和日期對得起來。
  - 主動提醒有天然的位置，又不是簡報。
- **缺點**：
  - 時間軸是新的思考方式，需要適應。
  - 除權息旺季（6–9 月）事件會暴增，需要按週收合。
  - 持倉和時間軸並排，會分散注意力。
  - 「某一天的持倉快照」需要後端計算歷史部位，要確認 M2、M3 是否已經有。
  - 績效分析（TWR、XIRR、回撤）仍然需要另一個檢視。

### 5.5 四個概念比較

| 比較項目 | A 一本帳 | B 清單與焦點 | C 說了就做 | D 今天時間軸 |
|---|---|---|---|---|
| 第一屏看得到持股 | 最高（首頁就是持股） | 高 | 中（持股卡可能被其他卡擠下去） | 高 |
| 頂層目的地數量 | 2 | 由清單決定（帳戶＋群組） | 0（只有輸入框和釘選） | 2–3 |
| AI 的存在感 | 中高（貼在每一列） | 中（在物件頂端） | **最高** | 中高（放在時間上） |
| 群組的分量 | 中 | **高**（和投資組合同一層） | 低到中 | 中 |
| 手機適合度 | 高 | 中 | 高 | 中高 |
| 和 Google 的距離 | 遠 | **近** | 遠 | 中 |
| 看起來像模板後台的風險 | 低 | **高** | 中（容易像 ChatGPT） | 低 |
| M4 之前沒有 AI 時 | 好（旁註可以用規則產生） | 好 | **差** | 好（事件本來就是規則產生） |
| 工程難度 | 中高（旁註要對齊列） | 低到中 | 高（判斷使用者意圖、生成卡片） | 高（歷史快照、時間軸） |
| 長輩友善 | 高 | 中 | 低到中（語音可以補） | 中 |

### 5.6 各頁的情境建議範例（四個概念共用）

每頁最多 3 個建議問題、2 個動作，內容依頁面、時間（盤中、盤後）、季節（除權息）改變。

| 頁面或狀態 | 建議問題 | 動作 |
|---|---|---|
| 總覽・盤中（09:00–13:30） | 今天誰影響最大？／今天跟 0050 比如何？ | 記一筆 |
| 總覽・收盤後 | 今天的損益主要來自哪裡？／這週累計多少？ | 記一筆、匯入對帳單 |
| 總覽・除權息季 | 這個月會入帳多少股利？／哪幾筆要扣二代健保？ | 記下已入帳的股利 |
| 個股・有持有 | 我的成本在河流圖的哪個位置？／加碼 1 張後成本變多少？ | 記一筆這檔、設到價提醒 |
| 個股・沒持有 | 它跟我持有的哪一檔最像？ | 加入觀察 |
| 交易紀錄 | 有沒有重複或漏記？／今年手續費和證交稅一共多少？ | 對帳 |
| 股利 | 明年預估可以領多少？ | 記入帳 |
| 群組 | 這週大家共同持有什麼？／我們的持股重疊多少？ | 分享本月 %（先預覽，要確認） |
| 剛匯入對帳單 | 這 12 筆中哪些和現有紀錄重複？ | 全部確認 |

### 5.7 可以組合的方向

- **A 當骨架，加上 C 的輸入框行為和 D 的「接下來」**：
  - 骨架是 A 的帳本加旁註。
  - 輸入框照 C 的方式運作：回答是 Forliosa 的元件卡，可以展開成整頁，也可以釘在旁註欄頂部。
  - 旁註欄頂部放 D 的「接下來 7 天」事件。這些事件由規則產生，不是 AI 簡報。
  - 這個組合同時滿足持倉優先、簡單、AI 做得多。
- **最低風險的選擇是 B**：但要嚴格避免後台感，例如只用兩欄、左欄淡化、焦點區用大數字。
- **C 適合當實驗**：先在手機上試，因為輸入框本來就在拇指區；桌面維持 A 或 B。

### 5.8 討論題

1. 首頁直接是持股表（A、D）可以嗎？還是要像 Google 一樣有大圖表加頁籤（B）？
2. AI 要「貼在數字旁邊」（A）、「放在物件頂端」（B），還是「主要用說的」（C）？
3. 群組要和投資組合同一層級（B），還是當成一個目的地（A、D）？群組首頁要不要放排行榜？
4. 「接下來」的事（除息、入帳）要放在旁註、時間軸，還是個股頁？
5. 手機底部要不要有分頁列？D 有，A 和 C 沒有。
6. 哪些 AI 寫入可以讓使用者開「自動套用」？例如定期定額。
7. 要不要把「只含 % 的分享卡，可以貼到 LINE」放進 M5？

---

## 6. 來源日期速查

- **早於 2025 年（舊）**：
  - Commonstock 被 Yahoo 收購（2023-08，Dealroom）
  - Trade Republic 2023 年改版的批評（basic thinking 2023-09）
  - Granola 發表（2024-05）
  - NN/g 漸進揭露（2006）
  - Delta 被 eToro 收購（2019）
  - Stock Events 部分商店頁面（2024）
- **2025**：
  - Raycast AI Extensions（02-26）
  - LogRocket 漸進揭露（03 更新）
  - Delta 商店頁更新（04）
  - Public 關閉社群（06）
  - Dia beta（06）
  - Linear Triage Intelligence 預覽（08-14）與自動套用（09-19）
  - Wealthsimple 收購 Fey（08 下旬）
  - Notion 3.0（09-18）
  - ChatGPT Pulse（09 下旬）
  - Wealthsimple 三分頁改版（09）
  - Robinhood Social 宣布（09-10）
  - Gemini 3 生成式介面（11-18）
  - Trading 212 首頁改版（年初）與撤回投資組合改版（12-24）
  - Copilot Money Web 版（12）
  - Finary 預算重做（12）
  - Sharesight 2025 新報表
  - Snowball 的 Trustpilot 評論
  - Wealthfolio 2.0（約下半年，依貼文編號推估）
- **2026**：
  - Copilot Money Web 版報導（9to5Mac 01-01）
  - Sharesight Investments 分頁（02）與調整（03）
  - Simply Wall St Command Center（02）
  - Summit（02-21）
  - Robinhood 家庭中心（03-04）
  - Perplexity Portfolio（03）
  - Robinhood Social beta（03-18）
  - Linear Agent（03-24）
  - getquin 的 Sagard 訪談（03-24）
  - Revolut AIR（04-09）
  - Capital.com 新 app（05／06）
  - Fiscal.ai 券商連線（05）
  - Cortex 擴大到投顧（06）
  - eToro 新 app（07-07）
  - Robinhood 工程部落格（08-25）
  - Notion 提議修改（08-28）
  - eToro 客戶移轉（10-04）
  - Wealthsimple Penny 與新 app 預告（11-05）
  - Wealthfolio 3.x（日期未確認）
  - Kubera、Blossom 等評測
- **沒有標日期的官方說明頁**（2026-11 透過搜尋讀取）：
  - getquin 說明 13609828、6817049、11706719
  - Delta 支援頁
  - Kubera 說明
  - Trade Republic 說明 1602、2904
  - Snowball 說明中心
  - Robinhood 的 Cortex、Social、iOS 小工具說明
  - Linear Triage Intelligence 文件
  - Superhuman 說明
  - OpenAI Apps SDK 指南
  - SAP Fiori 指南
  - Parqet 舊說明頁
  - Commensa 官網
- **無法直接開啟的網域**：`www.getquin.com`、`linear.app`、`cdn.jsdelivr.net`（WebFetch 解析失敗）。這些來源的內容都來自搜尋摘要。
