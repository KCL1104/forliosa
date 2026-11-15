# 美股資料：TradingView 小工具、Databento、SEC EDGAR、美股指數（2026-11-15）

產品負責人 2026-11-15 提出三件事：圖表能不能全部改用 TradingView 的免費嵌入小工具（台股、美股都有）；美股財報用 SEC EDGAR；
美股報價（給 AI 讀、存進我們的歷史資料庫）用 Databento（註冊送 US$125 額度）。這份是研究結果。

**證據等級**：這次的沙盒連不到 tradingview.com 與 databento.com（網路政策；已在環境設定加上，從下一個工作階段起可以直接讀），
所以多數「原文」是**廠商自己頁面的搜尋摘要**（標【廠商摘要】），其他是【第三方】或【推論】。另有 8 個查證代理各自試著推翻重點說法，
結果寫在每一節。下結論前要再確認的事列在第 6 節。

## 0. 一頁結論

| 問題 | 結論 | 建議 |
|---|---|---|
| 圖表全部改用 TradingView 小工具 | **不適合**：上市股（TWSE）很可能**不能**在免費小工具裡畫圖；付費會員網站能不能用免費小工具，條款沒寫清楚；小工具的資料我們拿不到（AI、帳本市值、本益比河流圖都用不到）；會把使用者看的股票送給 TradingView（要改隱私權政策） | 維持自己的圖（已經是 TradingView 開源的 Lightweight Charts） |
| 市場頁的美股區塊 | 真正的指數代號（SPX、DJI、NDX）在小工具裡不能顯示，只能用 ETF（SPY、QQQ、DIA）或差價合約（FOREXCOM:SPXUSD）替代；TradingView 有新聞小工具（News Feed） | 可以考慮「小用法」，但要先取得 TradingView 書面同意、改隱私權政策 |
| 美股財報 | SEC EDGAR 已經在用（個股頁「財務」）；公共領域、可商用 | 維持；之後可加 13F 機構持股（只對美股有用） |
| 美股報價（Databento） | **費用很低**（日線五年 300 檔約 US$1 以下）；但**官方收盤價只從 2024-07-01 開始**、**能不能顯示給付費會員要 Databento 書面確認**（只有 EQUS.MINI 明寫可以對外顯示，且可能要訂閱方案） | 先寄信問 Databento（附錄 A 信稿）；確認前不上線 |
| 美股指數點數 | 要 S&P DJI 與 Nasdaq 的授權，沒找到免費又能顯示的來源（這一項的查證沒做完，見第 5 節） | 用 ETF 價格代替，標成 ETF |

## 1. TradingView 免費小工具

### 1.1 涵蓋範圍（小工具和 tradingview.com 網站不同）

- 小工具裡的股票資料**一律延遲**：「Exchanges want each website to pay fees for real-time data. As per their requirements we are only allowed to
  stream delayed data.」付費升級不影響小工具：「Paid upgraded plans do not affect the data in the widgets.」【廠商摘要：widget-docs/faq/data】
- 「This symbol is only available on TradingView」的意思是「we are not allowed to show that symbol in any timeframe in the widgets」【廠商摘要：同上】。
- **台灣**：小工具的亞太市場清單只有一列台灣：「TPEx Taipei Exchange, Taiwan | TPEX | Delayed Stocks, Indices & Futures」，**沒有證交所（TWSE）**
  【廠商摘要：widget-docs/markets/asia-pacific，兩次搜尋都一樣】。tradingview.com 網站本身有 TWSE（免費延遲 15 分、即時 US$20／月），
  所以是**小工具的授權沒有涵蓋**，不是沒有這檔。
  - 查證（2 個代理）：**部分成立**。上市股（TWSE:2330）、加權指數（TWSE:TAIEX）在小工具裡**很可能**顯示「只能在 TradingView 上看」，
    但沒有找到任何人實際測過的紀錄；另一個開源專案（OpenStockTW）說 TradingView「does not license TWSE/TPEX candle embeds」，
    卻又在拿不到資料時改用 TradingView 小工具畫上櫃股，所以上櫃股到底畫不畫得出來也要實測。【第三方：github.com/tibame201020/OpenStockTW】
  - **一分鐘就能確定**：在一般瀏覽器打開 TradingView 的小工具頁（Advanced Chart），代號輸入 TWSE:2330、TWSE:TAIEX、INDEX:TAIEX、TPEX:6488，看是圖還是那一句提示。
- **美股**：NASDAQ、NYSE、NYSE Arca 都在清單上，資料商是「Cboe One」、「Delayed Stocks」【廠商摘要：widget-docs/markets/north-america】。
  延遲幾分鐘文件沒寫（15 分是第三方說法）；Cboe One 的價格不是主交易所的官方收盤，可能和我們別處的數字差一點。
- **美股指數**：SP:SPX、NASDAQ:NDX、DJ:DJI（還有 TVC:RUT、CBOE:VIX）在免費小工具裡被擋【第三方：2026-10 開發者實測】；NASDAQ:IXIC 沒找到直接證據。
  TradingView 自己的示範改用 FOREXCOM:SPXUSD（S&P 500 差價合約）、FOREXCOM:NSXUSD、FOREXCOM:DJI、FRED:SP500、FRED:NDQ100【廠商摘要：小工具示範】。
  這些都**不是指數本身**。

### 1.2 授權

- 免費是「with default TradingView branding」；顯名「should remain as was originally designed and intended」，要拿掉顯名得填表跟 TradingView 談
  【廠商摘要：tradingview.com/widget、/policies】。顯名、logo、法律連結一律連回 TradingView，不能改；只有代號的連結可以改到我們的頁面。
- 使用條款：「Except as otherwise expressly permitted by separate agreement, we do not permit commercial usage of any of our services or APIs.」
  市場資料是「licensed for exclusive display-only use… strictly limited to personal or internal business purposes」【廠商摘要：/policies】。
- 查證（1 個代理）：**成立**。這條是通則，沒有點名小工具，TradingView 也明顯歡迎商業網站嵌入；但**沒有任何頁面說可以放在要登入、要付費的網站**，
  所以 NT$300 會員制的 Forliosa 要先取得書面同意（附錄 B 信稿）。
- 另外一個產品「Advanced Charts」（自架的圖表庫，資料自己供）免費版**明文排除**：「available for free provided that … the implementation environment is public
  (not for private use or behind a paywall)」【廠商摘要：charting-library-docs】。付費版要洽業務、不公開價格，而且一樣要自己的資料。

### 1.3 其他缺點

- **隱私**：小工具不設 cookie，但會送出「URL of the page embedding the widget, widget type, displayed symbol, IP address」【廠商摘要：widget FAQ】：
  TradingView 會知道我們的會員在看哪些股票。隱私權政策目前寫外部腳本只有 Cloudflare Web Analytics（`docs/legal/README.md` P16），要加一條。
- 要放寬 CSP（s3.tradingview.com 的腳本、tradingview-widget.com 的 iframe）；Advanced Chart 一個約 1.4 MB 以上【第三方，未實測】。
- 樣式：Web Component 版可以用 Theme Builder 改色、字型；iframe 版不行。有繁體中文（`zh_TW`）與淺色、深色；紅漲綠跌能不能對上沒驗證。
- 資料拿不到：AI、帳本市值、本益比河流圖、AI 圖卡都不能用小工具的資料；同一頁會出現 TradingView 的延遲價和我們的官方收盤兩套數字。

### 1.4 我們現在的圖

走勢圖已經是 TradingView 開源的 **Lightweight Charts™**（Apache-2.0，`apps/web/src/pages/stock/PriceChart.tsx`），NOTICE 要求的顯名與連到
tradingview.com 的連結放在「資料來源與授權」頁與頁尾。它只是畫圖的程式，要自己的資料，所以解決不了「沒有美股價格」。

## 2. 美股財報：SEC EDGAR

已經在用（`apps/api/src/forliosa/marketdata/sec.py`：代號對照、XBRL company facts、申報清單），個股頁「財務」顯示美股的營收、EPS 等。
美國政府公開資料、可商用，User-Agent 要聲明身分（`SEC_CONTACT_EMAIL`）、每秒最多 10 次。之後可以加 13F（機構持股），只對美股有用。

## 3. 美股報價：Databento

### 3.1 費用（查證：**成立，但五年歷史的結論要改**）

- 新使用者 **US$125 額度，6 個月後到期**，可用在歷史資料或第一個月的訂閱；註冊要信用卡【廠商摘要：docs.databento.com 知識庫】。
- 即時資料要訂閱（Standard 約 US$199／月；Unlimited 的美股 2026-06-22 起 US$4,000／月）；**收盤後的日線不需要即時資料**。
- 日線很便宜：有人實際付費抓一整年全美股的 EQUS.SUMMARY 日線，約 280 萬筆、157 MB、US$4.38【第三方：news.ycombinator.com/item?id=45516154】。
  換算 300 檔 × 5 年約 US$0.6、每天更新 300 檔約 US$0.0005【推論】，額度用不完。
- **歷史長度才是限制**：
  - EQUS.SUMMARY（官方合併收盤價，來自 Nasdaq NLS+，沒有還原除權息）**從 2024-07-01 開始**【廠商摘要：資料集目錄頁「Since 2024-07-01」】。
  - EQUS.MINI（部分交易所的合成價，**不是官方收盤**）從 2023-03-28 開始。
  - 單一交易所的資料集（例如 XNAS.ITCH）的日線可到 2018，但只有那一家交易所的成交，不是官方收盤。
  - 所以「五年歷史」用 Databento 拿不到官方收盤；要嘛圖從 2024-07 開始畫，要嘛由產品負責人決定把 Yahoo「只畫走勢圖」的例外延伸到美股（授權風險同台股那一條）。

### 3.2 能不能顯示給會員看（查證 2 個代理：**部分成立**——這是最大的不確定）

- 給客戶看的網站就是「distribution」（對外散布）【廠商摘要：Databento 即時資料指南】。
- **只有 EQUS.MINI** 明寫可以：「Databento has a derived use license in place with these venues specifically for its redistribution and in turn our end users are
  allowed to use and redistribute the feed without further licensing or exchange fee requirements」，並標「Personal and commercial | No license fees」
  【廠商摘要：databento.com/equities】。條件：不能讓人從中還原出原始交易所資料。
- **EQUS.SUMMARY** 只說「without introducing license fees」，**沒有找到**對外顯示的授權文字【廠商摘要：Databento 部落格】。
- 「超過 24 小時的歷史資料大多可以轉載」說太滿：Databento 的 FAQ 把「要轉載」列為**連歷史資料也需要授權**的情況，各資料集照原發行者的限制
  【廠商摘要：databento.com/blog/introduction-market-data-licensing】。
- **方案也沒定論**：一個代理查到 EQUS.MINI 要有付費的美股方案（Standard、Plus、Unlimited 都含）；另一個查到定價頁把「External distribution」列在
  Standard 之上（Plus 約 US$1,500／月、年約）。用 US$125 額度按量付費能不能對外顯示，**沒有任何來源說可以**。
- 拆股、股利資料（Security Master、corporate actions）不能對外轉載【廠商摘要】：還原價要我們自己用 SEC 或其他資料算。
- **AI 讀價格**：沒有廠商講到 AI。回答裡寫出價格就等於顯示給使用者，算同一個授權【推論】；寫信時一起問。

### 3.3 其他選擇（價格與條款都是廠商頁面摘要）

| 廠商 | 給使用者看的價格 | 條款重點 |
|---|---|---|
| Tiingo | 「Base Equities Redistribution」US$250／月（新創）、US$500（企業），含日線 | 轉載要申請；要寫「Data sourced by Tiingo」並連結。使用者自帶金鑰只限「your software is not distributing our data」，我們的資料庫與市場頁不適用 |
| Massive（原 Polygon） | Stocks Business US$1,999／月 | 「showing Massive data in your own app requires a Business subscription」 |
| Finnhub、EODHD、FMP | 洽詢報價 | 自助方案都是個人使用；顯示給別人要另簽 |
| Alpaca（免費 IEX） | 不行 | 「you cannot redistribute Alpaca API data」；IEX 只占約 2% 成交量 |
| IEX Cloud | — | 2024-08-31 已關閉 |

## 4. 美股新聞（市場頁）

- TradingView 的 **News Feed** 小工具（2026-10 取代 Top Stories），可以只看股市【廠商摘要】；條款與隱私問題同第 1 節。
- 我們自己的做法：GDELT（已在用、可商用）抓美股相關的中英文標題，存檔、照我們的設計顯示，成本 0。

## 5. 美股指數

- S&P 500、道瓊屬於 S&P Dow Jones Indices；Nasdaq Composite 屬於 Nasdaq。FRED 的 S&P 500 頁寫「Reproduction of S&P 500 in any form is prohibited except
  with the prior written permission of S&P Dow Jones Indices LLC」【廠商摘要：FRED】。
- Nasdaq 2024-08-01 起要求收盤與歷史指數資料的接收者直接跟 Nasdaq 簽約【廠商摘要：nasdaqtrader.com DN2024-5】——**這一條的查證因為搜尋額度用完沒做，暫不當成事實**。
- Databento 有 DBIX.CORE（Cboe 的指數資料，含 SPX、DJX），訂閱 US$99／月起再加指數授權費【廠商摘要】。
- 替代：ETF 價格（成交資料，不是指數資料），跟著美股報價一起解決。**QQQ 追蹤 Nasdaq-100，不是 Nasdaq Composite**（追蹤 Composite 的是 ONEQ）；SPY 約是 S&P 500 點數的 1/10。
  列名寫 ETF 代號與全名（「SPY（SPDR S&P 500 ETF）」），不要寫成「S&P 500」。

## 6. 下決定前還要確認的事

1. TradingView 小工具實測：TWSE:2330、TWSE:TAIEX、INDEX:TAIEX、TPEX:6488、NASDAQ:IXIC（一般瀏覽器一分鐘；或下一個工作階段用無頭瀏覽器跑）。
2. TradingView 書面同意：小工具能不能放在要登入、付費的 Forliosa（附錄 B）。
3. Databento 書面確認：EQUS.MINI／EQUS.SUMMARY 能不能顯示給付費會員、存進我們的資料庫、給 AI 讀；要哪個方案；按量付費可不可以（附錄 A）。
4. 下一個工作階段（網路已開）直接讀：databento.com 的定價頁、授權頁、資料集頁；tradingview.com 的條款與小工具 FAQ 全文。

## 附錄 A：寫給 Databento 的信（英文，寄件人與公司名由產品負責人填）

> Subject: Display rights for US equities end-of-day data in a small consumer web app
>
> Hello Databento team,
>
> We run Forliosa, a small portfolio-tracking web app for retail investors in Taiwan (a few dozen non-professional users; members pay a monthly
> subscription). We would like to show US stock end-of-day prices to our logged-in members, and we want to confirm the licensing before signing up.
>
> Intended use:
> 1. Daily closing prices (OHLCV, one update per day after the US close) for roughly 300 US stocks and ETFs that our users hold or watch, plus as much
>    daily history as available.
> 2. We store the bars in our own database and display them to members: price, daily change, simple line charts, and the market value of their holdings.
> 3. An AI assistant in the app reads these stored prices to answer members' questions (for example "how did NVDA do this week?"), so prices can
>    appear in its answers.
> 4. No real-time data, no redistribution of raw files or an API to third parties, no professional users.
>
> Questions:
> 1. Which dataset fits this use: EQUS.SUMMARY (official consolidated closes) or EQUS.MINI? Does EQUS.SUMMARY allow external display to end users?
> 2. Is this use allowed with usage-based (pay-as-you-go) historical purchases, or does it require a subscription plan? If a plan, which one
>    (Standard or Plus), and is there an extra exchange or redistribution fee?
> 3. Does showing the data inside AI-generated answers count as the same display use?
> 4. Are there attribution or notice requirements we must show?
>
> Thank you,
> 〔name〕, Forliosa

## 附錄 B：寫給 TradingView 的信（英文，用小工具頁的聯絡表單）

> We run Forliosa (forliosa.trade), a portfolio tracker for retail investors in Taiwan. Members log in and pay a monthly subscription. We would like
> to embed free TradingView widgets (Mini Chart / Symbol Overview for SPY, QQQ, DIA, and the News Feed widget) on our market page, keeping the
> default TradingView branding and attribution unchanged. Is this allowed on a login-only, paid-subscription site, or do we need a separate
> agreement? Also, are TWSE-listed stocks (for example TWSE:2330) and the TAIEX available in the widgets?
