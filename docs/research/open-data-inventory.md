# 開放資料盤點：Forliosa 可合法商用的公開資料

> 撰寫：2026-11-12（研究子代理）。前提：產品負責人決定 **只使用可合法商用的資料**（`DATA_POLICY=commercial`）。
> 本文件盤點「官方開放資料與公開 API」的**全部端點**，判斷每一個能不能商用、對 Forliosa 哪個功能有用、先做哪些。
> 授權的法律分析沿用 [`data-sources-licensing.md`](data-sources-licensing.md)，這裡不重複。**這不是法律意見。**
>
> 機器可讀版：[`open-data-catalog.json`](open-data-catalog.json)（638 筆，一個端點或資料集一筆）。
>
> **標示**（與授權研究相同）
> - 【事實】這次直接讀到原文：官方 swagger、實際 API 回應、本 repo 程式碼。
> - 【單一來源】只有搜尋引擎摘要，原文沒能打開。
> - 【推論】研究者自己的判斷。
> - 「〔推定〕」：集保資料集的標題是依 CSV 欄位推定的（官方清單頁讀不到）。

---

## 0. 一頁結論

1. **三個交易所 OpenAPI 的每一個端點都讀了 swagger，並各實際呼叫一次。**【事實】
   - 證交所 143 個端點，140 個拿到真實回應；櫃買 225 個，225 個；期交所 135 個，135 個。
   - 集保 `opendata.tdcc.com.tw` 沒有清單頁，以 ≥2.5 秒間隔逐一試出 103 個有資料的 `getOD.ashx?id=` 資料集。
   - Forliosa 目前用了證交所 26 個、櫃買 25 個端點、集保 1 個（`datapolicy.DATASETS` 的 33 筆：證交所 16、櫃買 15、集保 1、shioaji-data 1；財報 6 個產業別合成一筆）。
2. **最值得馬上加的（全部免費、政府資料開放授權、只需顯名）**：
   - **報酬指數**：證交所 `MI_INDEX` 每天有「發行量加權股價報酬指數」等 267 個指數收盤值 → 補上目前 `benchmark.twr: null` 的 `^TAIEXTR` 基準。
   - **USD/TWD**：期交所 `DailyForeignExchangeRates` 每天有 USD/NTD 等 10 個匯率，回應還附近 6 週 → 取代固定 31.5。（2026-11-12 更新：期交所這個資料集授權「有條件」，產品負責人決定改用央行 7232〈銀行間新臺幣對美元收盤匯率〉，數字與期交所 USD/NTD 逐日相同，見第 7 節。）
   - **股利決議**：證交所 `t187ap45_L` 有董事會／股東會決議的每股股利，並把盈餘、法定公積、資本公積分開 → 股利頁可以在除權息預告前數週就顯示，也能分辨「資本公積配發」（不算股利所得）。**櫃買對應的 `mopsfin_t187ap39_O` 已停在 2021-08，不能用。**
   - **公司基本資料**：`t187ap03_L`、`mopsfin_t187ap03_O` 有已發行股數、產業別、上市日 → 可算市值，減少對 shioaji-data 的依賴。
   - **期交所籌碼**：三大法人（期貨、選擇權、買賣權分計）、大額交易人未沖銷部位、Put/Call 比 → 「大盤籌碼」與 AI 盤勢說明。
   - **ETF 受益人數**：集保 `id=2-22`（上市）、`id=2-23`（上櫃）月資料有每檔 ETF 與股票的「集保股東戶數」（例：0050 在 115 年 10 月為 3,741,557 戶）。
3. **上市個股三大法人、外資持股仍然沒有開放來源。** 證交所 143 個端點只有類股層級（`MI_QFIIS_cat`）與前 20 名（`MI_QFIIS_sort_20`）。【事實】
4. **歷史資料幾乎都要自己存。** 多數端點只回最新一期；少數回應帶近一個月（指數、`FMTQIK`、期交所 `PutCallRatio`、外幣匯率）；`FMNPTK_ALL` 給去年整年；`newsList` 約 10 個月（200 個日期）；集保 `id=2-21` 的票券利率從 2009 年起。**越早開始存越好**。【事實】
5. **期交所授權**：swagger 只連到期交所網站使用條款，沒有連到 data.gov.tw 授權；但 data.gov.tw 上二十多筆期交所資料集都標「政府資料開放授權條款第 1 版」，而且都指向這個 OpenAPI【單一來源】。所以有找到對應資料集的端點標「可商用」，其餘（包括最重要的「期貨每日交易行情」）標「有條件」，建議寄信確認。
6. **美股**：SEC EDGAR 可以商用（公開申報與政府作品可自由再利用），適合美股財報與事件；**美股價格仍然沒有免費可商用的來源**（FRED 禁止存檔、IEX HIST 只有單一交易所、各國交易所都要授權）。
7. **其他交易所**（香港、日本、韓國、新加坡、上海／深圳）都沒有可商用的免費資料，全部 `skip`。

---

## 1. 盤點方法與研究限制

| 項目 | 做法 | 標示 |
|---|---|---|
| 時間 | 2026-11-12 06:20–07:40 UTC（台北 14:20–15:40）。這時當天盤後資料多半還沒公布，所以大多數回應是 **11/11** 的資料 | 【事實】 |
| 證交所 | 讀 [swagger](https://openapi.twse.com.tw/v1/swagger.json)（Swagger 2.0，143 個 GET）；逐一呼叫，間隔 3.5 秒；失敗的端點以 12 秒、15 秒間隔各再試一輪 | 【事實】 |
| 櫃買 | 讀 [swagger](https://www.tpex.org.tw/openapi/swagger.json)（OpenAPI 3.0，225 個 GET）；間隔 2.5 秒；失敗的隔 12 秒再試 | 【事實】 |
| 期交所 | `https://openapi.taifex.com.tw/v1/swagger.json` 回 302 轉到 Swagger UI 首頁；首頁寫的規格網址是 [`/swagger.json`](https://openapi.taifex.com.tw/swagger.json)（OpenAPI 3.0，135 個 GET，伺服器 `https://openapi.taifex.com.tw/v1`）；間隔 2.5 秒 | 【事實】 |
| 集保 | 根目錄是空白 ASP.NET 頁，沒有資料集清單；`openapi.tdcc.com.tw`（data.gov.tw 頁面寫的 OAS 文件）被沙箱代理擋。改為以 2.5 秒間隔試 `getOD.ashx?id=1-1` 起的編號，連續 3 個空回應就換下一組 | 【事實】 |
| User-Agent | `forliosa-research/0.1 (open-data inventory; low-rate one-off survey)`；不偽裝瀏覽器、不跟隨重新導向 | 【事實】 |
| 大檔 | 每個回應最多 40 MB、120 秒；超過的只取前 400 KB 看欄位（期交所每筆成交、證交所 `FMNPTK_ALL`、`t187ap37_L` 等） | 【事實】 |
| 其他網站 | data.gov.tw、MOPS、sec.gov、FRED、央行、主計總處、國發會、openapi.tdcc.com.tw、各國交易所：curl 被代理拒絕（HTTP 403 CONNECT），WebFetch 也無法解析網域 → **只能用搜尋摘要** | 【事實】 |
| 下載內容 | 全部放在 scratchpad，當作不可信資料只做解析，沒有執行 | 【事實】 |

**證交所的不穩定**：第一輪 143 次請求中有 25 次失敗（HTTP 307「因為安全性考量，您所執行的頁面無法呈現」或 `Connection reset by peer`），重試兩輪後仍失敗 2 個。失敗沒有固定模式，和授權研究、`CONTRACT_NOTES.md` 記錄的「偶發 307、數秒後正常」一致。**這些端點的欄位改取自 swagger**，catalog 的 `verified` 欄有寫明。`t187ap37_L`（上市權證基本資料）超過 40 MB 上限，只取前段也沒拿到內容。櫃買第一輪失敗 5 個（HTTP 520 或連線重設）、重試後 0 個，另有 4 個大檔 120 秒逾時、只拿到前段（`mopsfin_t187ap39_O`、`mopsfin_t187ap37_O`、`tpex_warrant_monthly_quts`、`tpex_warrant_quts`）；期交所 0 個失敗。【事實】

---

## 2. 總表

| 提供者 | 端點／資料集 | 實際取得回應 | 有用（P0+P1+P2） | P0 | P1 | P2 | skip | 已在用 |
|---|---|---|---|---|---|---|---|---|
| 臺灣證券交易所 OpenAPI | 143 | 140 | 107 | 31 | 13 | 63 | 36 | 26 |
| 證券櫃檯買賣中心 OpenAPI | 225 | 225 | 170 | 26 | 13 | 131 | 55 | 25 |
| 臺灣期貨交易所 OpenAPI | 135 | 135 | 40 | 11 | 6 | 23 | 95 | 0 |
| 臺灣集中保管結算所 開放資料 | 103 | 103 | 23 | 1 | 2 | 20 | 80 | 1 |
| 臺灣集中保管結算所 OpenAPI | 1 | 0 | 1 | 0 | 1 | 0 | 0 | 0 |
| 其他（data.gov.tw 各機關、MOPS、國外） | 31 | 0 | 20 | 0 | 6 | 14 | 11 | 0 |
| **合計** | 638 | 603 | 361 | 69 | 41 | 251 | 277 | 52 |

- **P0**＝已在用，或應該立刻加；**P1**＝下一批；**P2**＝有用但不急；**skip**＝與個人投資帳本無關（券商名錄、境外結構型商品、票券報價…）或不可商用。
- 「已在用」以 `apps/api/src/forliosa/datapolicy.py` 的 `DATASETS`、`archive.py`、`marketdata/tpex.py` 實際呼叫的網址為準；財報 6 個產業別各算一個端點。【事實】

---

## 3. 證交所 OpenAPI（143 個端點）

**授權**：swagger `info.description` 連到 [data.gov.tw/license](https://data.gov.tw/license)（政府資料開放授權條款第 1 版）。可商用、可存檔、可加工，**必須顯名**。【事實】

### 3.1 已在用（26 個端點）

| 端點 | Forliosa 用途 |
|---|---|
| `exchangeReport/STOCK_DAY_ALL` | 收盤價、日線、成交量 |
| `exchangeReport/BWIBBU_ALL` | 本益比、殖利率、淨值比 |
| `exchangeReport/TWT84U` | 參考價、漲跌停 |
| `exchangeReport/MI_MARGN` | 融資融券 |
| `exchangeReport/TWT48U_ALL` | 除權息預告 |
| `announcement/notice`、`announcement/punish` | 注意、處置 |
| `opendata/t187ap04_L` | 重大訊息（事件、財報與法說會日期） |
| `opendata/t187ap41_L` | 股東會 |
| `opendata/t187ap05_L` | 月營收 |
| `opendata/t187ap06_L_{ci,basi,bd,fh,ins,mim}`、`t187ap07_L_{…}` | 季報損益、資產負債（12 個端點） |
| `opendata/t187ap17_L` | 利潤率 |
| `holidaySchedule/holidaySchedule` | 交易日 |
| `news/newsList` | 證交所新聞 |
| `opendata/t187ap47_L` | ETF 基本資料（存進 `fund_profiles`，尚無端點） |

### 3.2 建議新增（P0／P1）

| 端點 | 內容（欄位取自 2026-11-12 真實回應） | 用途 | 優先 |
|---|---|---|---|
| `exchangeReport/MI_INDEX` | 267 個指數的收盤值、漲跌、漲跌%：發行量加權指數、**發行量加權股價報酬指數**、臺灣50報酬指數、高股息報酬指數、各類股報酬指數 | `^TAIEXTR` 基準、ETF 追蹤指數報酬、大盤卡 | **P0** |
| `indicesReport/MFI94U` | `Date, TAIEXTotalReturnIndex`；回應含本月每日（8 天） | 同上；第一次執行可回補本月 | **P0** |
| `indicesReport/MI_5MINS_HIST` | 加權指數本月每日開高低收 | 大盤 K 線 | **P0** |
| `opendata/t187ap45_L` | 1,270 列：決議進度、股利年度與期間、董事會日期、股東會日期、可分配盈餘、**每股現金股利（盈餘／法定公積／資本公積分列）**、配股 | 股利頁「已決議」、帳本預估股利、資本公積配發的稅務處理 | **P0** |
| `opendata/t187ap03_L` | 1,099 列：產業別、成立／上市日、實收資本額、**已發行普通股數**、面額、董事長、總經理、發言人、簽證會計師、網址 | 市值、公司小卡、產業分類 | **P0** |
| `exchangeReport/BWIBBU_d` | 和 `BWIBBU_ALL` 不同：多了收盤價、`DividendYear`、`FiscalYearQuarter`（本益比依據的財報季） | 估值頁標示「本益比依 2026Q2 財報」 | P1 |
| `exchangeReport/FMTQIK` | 本月每日成交量值、筆數、加權指數 | 大盤成交值、AI context | P1 |
| `indicesReport/TAI50I` | 臺灣50指數與報酬指數（本月每日） | 0050 類 ETF 追蹤比較 | P1 |
| `fund/MI_QFIIS_cat` | 各類股外資持股比率 | 上市個股外資持股的合法替代（類股層級） | P1 |
| `ETFReport/ETFRank` | 定期定額交易戶數前 20 名（個股、ETF 分列） | ETF 頁人氣、定期定額功能 | P1 |
| `exchangeReport/TWTAWU` | 暫停交易（停牌、恢復日期時間） | 個股狀態 | P1 |
| `exchangeReport/TWT85U` | 變更交易（全額交割）清單 | 個股狀態 | P1 |
| `exchangeReport/BFI84U` | 停資停券預告（起訖日、原因：股東會、除權息） | 事件 | P1 |
| `company/suspendListingCsvAndHtml` | 終止上市公司與日期（265 筆，民國 90 年起） | 持股下市標示 | P1 |
| `opendata/t187ap11_L` | 董監持股餘額明細 27,494 列：職稱、姓名、選任持股、目前持股、設質股數、設質比例 | 籌碼頁「董監持股、質押比」 | P1（含個資） |
| `opendata/t187ap09_L` | 董監質權設定比率（以百分比區間列出公司） | 風險提示 | P1 |
| `opendata/t187ap02_L` | 持股逾 10% 大股東 | 公司小卡 | P1（含個資） |
| `opendata/t187ap12_L` | 內部人持股轉讓事前申報：申報人身分、姓名、轉讓方式、股數、有效期間 | 事件時間軸 | P1（含個資） |

### 3.3 其餘端點的分類

| 類別 | 個數 | 判斷 |
|---|---|---|
| ESG 揭露 `t187ap46_L_1`～`_21` | 21 | P2：年度資料（報告年度 114），可做 ESG 卡片，不急 |
| 公開發行（未上市櫃）公司財報、營收、基本資料、董監（`_X_*`、`_P`） | 15 | skip |
| 券商、營業員、分公司、券商財務（`brokerService/*`、`t187ap01/18/20/21`、`OpenData_BRK0*`） | 8 | skip（`secRegData` 開辦定期定額券商名單可當說明資料，P2） |
| 權證（`t187ap36/37/42/43_L`） | 4 | P2／skip |
| 其他公司治理（酬金、獨董兼任、提案權、累積投票、經營權異動、裁罰…） | 約 20 | P2／skip；裁罰、經營權異動可進事件頁 |
| 大盤統計（`MI_INDEX20`、`MI_INDEX4`、`twtazu_od`、鉅額交易 3 個、`MI_5MINS`） | 7 | P2；`MI_5MINS` 是全市場每 5 秒累計委託成交，**不是**個股盤中走勢 |
| 其他行情（零股 `TWT53U`、盤後定價、月／年成交、外國股票） | 6 | P2；`FMNPTK_ALL` 給**去年整年**的個股最高、最低與日期 |

### 3.4 實作時要注意（含停更端點）

- 日期多為**民國年**（`1151111`），`BWIBBU_d`、`MI_INDEX20` 用西元（`20261111`）。【事實】
- `STOCK_DAY_AVG_ALL` 約 3 萬列（含權證）；`FMNPTK_ALL` 超過 14 MB，120 秒內下載不完。【事實】
- `t187ap09_L` 把公司放在一個多行字串欄位（`"3040      遠見  99.36\r\n…"`），要另外解析。【事實】
- `twtazu_od` 的出表日期停在 1150605，可能已停止更新。【事實】

---

## 4. 櫃買 OpenAPI（225 個端點）

**授權**：swagger 只連到網站使用條款（聯絡信箱是範本預設值 `apiteam@swagger.io`）；data.gov.tw 上的櫃買資料集標示政府資料開放授權條款第 1 版【單一來源；授權研究 §1.6】。網站條款第七條寫明「已授權政府資料開放平臺」的資料不在限制範圍。可商用，須顯名。

### 4.1 已在用（25 個端點）

`tpex_mainboard_daily_close_quotes`、`tpex_mainboard_quotes`、`tpex_mainboard_peratio_analysis`、`tpex_mainboard_margin_balance`、`tpex_3insti_daily_trading`、`tpex_3insti_qfii`、`tpex_exright_prepost`、`tpex_trading_warning_information`、`tpex_disposal_information`、`mopsfin_t187ap04_O`、`t187ap41_O`、`mopsfin_t187ap05_O`、`mopsfin_187ap17_O`、`mopsfin_t187ap06_O_*`（6）、`mopsfin_t187ap07_O_*`（6）。【事實】

### 4.2 建議新增（P0／P1）

| 端點 | 內容（真實回應） | 用途 | 優先 |
|---|---|---|---|
| ~~`mopsfin_t187ap39_O`~~ | 上櫃股利分派情形（董事會通過）——**已停更**：出表日期 1100804（2021-08-04），股利年度 107–110 | 上櫃公司的決議股利沒有開放來源，只能等除權息預告 | skip |
| `mopsfin_t187ap03_O` | 上櫃股票基本資料（已發行股數、產業、上櫃日…） | 市值、公司小卡 | **P0** |
| `tpex_reward_index` | `TPExIndex, TPExTotalReturnIndex`，本月每日 | 上櫃持股的報酬基準 | P1 |
| `tpex_index` | 櫃買指數本月每日開高低收 | 大盤卡 | P1 |
| `tpex_exright_daily` | 除權息計算結果：除權息前收盤、**開盤參考價**、漲跌停、現金股利、配股（例：3680 家登 11/12 除息，435.50 → 參考價 425.50、漲跌停 468.00／383.50，和 `CONTRACT_NOTES.md` 記錄的自算值完全一致） | 用官方值取代或核對自算的除權息參考價 | P1 |
| `tpex_margin_sbl` | 融券與借券賣出餘額（933 列） | 籌碼 | P1 |
| `tpex_3insti_summary` | 三大法人買賣金額（市場層級） | 大盤籌碼 | P1 |
| `tpex_3insti_qfii_industry` | 各類股外資持股比例 | 籌碼 | P1 |
| `tpex_cmode` | 變更交易、分盤、管理股票、停止交易 | 個股狀態 | P1 |
| `tpex_spendi_today` | 當日暫停／恢復交易 | 個股狀態 | P1 |
| `tpex_margin_trading_term` | 暫停融券賣出預告（起訖日） | 事件 | P1 |
| `mopsfin_t187ap11_O`、`mopsfin_t187ap09_O`、`mopsfin_t187ap02_O`、`mopsfin_t187ap12_O` | 董監持股、質押、大股東、內部人轉讓申報 | 同證交所 | P1（含個資） |

### 4.3 其餘端點的分類

| 類別 | 個數 | 判斷 |
|---|---|---|
| 指數系列（富櫃50、富櫃200、高殖利率、薪酬、就業88、公司治理指數與成分股；另 2 個在 4.2） | 18 | P2：成分股可做「ETF 追蹤指數成分」，但只有部分指數 |
| 債券（國際債、寶島債、可轉債、公債發行資料、理論價格） | 20 | skip；`bond_cb_daily` 可轉債日報 P2 |
| 權證、牛熊證 | 19 | P2／skip；日報表數 MB |
| ESG `t187ap46_O_*`（櫃買只有 16 個主題，證交所 21 個） | 16 | P2 |
| 興櫃（行情、注意、處置、推薦券商、財報、營收、基本資料） | 約 20 | P2：只有持有興櫃股時才需要；`tpex_esb_latest_statistics` 可當興櫃估值來源 |
| 創櫃、黃金現貨、開放式基金 | 11 | skip |
| 大盤統計與排行（市值、週轉率、日均量、成交分價、熱門股券商進出…） | 約 25 | P2；`tpex_active_broker_volume` 是上櫃熱門股的**券商分點進出**（只有熱門股前幾名） |
| 其他法人、信用交易、當沖細項 | 約 15 | P2 |
| `mopsfin_t187ap06_O_*A`「財報資訊」（6 個產業別） | 6 | P2：與已用的綜合損益表重疊 |

**停更或空白的端點**【事實】：`mopsfin_t187ap39_O`（股利分派，停在 2021-08-04）、`mopsfin_t187ap16_O`（2021-04，空白）、`tpex_warrant_gold*`（2018）、`tpex_warrant_wxy_*`（2020）、創櫃籌資三個端點（2025-10）。另外，已在用的 `mopsfin_t187ap06_O_*`／`07_O_*` 中，金融、金控、保險、異業幾個產業別當天只回一列空白（`07_O_ins`、`07_O_mim` 的日期還停在 1100616），這是上櫃沒有該產業公司或尚無資料，不影響一般業。

**櫃買沒有 ETF 專屬端點**（沒有 ETF 基本資料、淨值、受益人數）；上櫃 ETF 的行情在 `tpex_mainboard_daily_close_quotes` 裡。【事實】

---

## 5. 期交所 OpenAPI（135 個端點）

### 5.1 授權與取得

| 項目 | 內容 | 標示 |
|---|---|---|
| swagger | `info.description`：「本平臺提供臺灣期貨交易所 OAS 資訊服務，歡迎各位介接使用。[使用條款](https://www.taifex.com.tw/cht/edu/userTerms) [聯絡窗口](mailTo:s0160116@taifex.com.tw)」；**沒有**連到 data.gov.tw 授權 | 【事實】 |
| data.gov.tw | 期交所資料集標示政府資料開放授權條款第 1 版、免費，頁面備註都指向 openapi.taifex.com.tw：三大法人 11592–11601、Delta 11321、Put/Call 比 11322、大額交易人 11337／11338、鉅額交易 11590／22649–22651／22671、價差 20669／20670、最後結算價 28825／30853、履約交割 34063、年成交量 36476、電子下單 43448、股票期貨前十大 43449、個股選擇權未平倉 45747 | 【單一來源：搜尋摘要】 |
| 網站使用條款 | 英文版：網站軟體與內容（含資料）屬期交所著作權，法規與公告除外；禁止重製、散布、改作等。中文版是否和證交所一樣有「已授權政府資料開放平臺者不在此限」的例外，兩次搜尋結果互相矛盾 | 【單一來源】 |
| 主機 | Cloudflare；`/v1/swagger.json` 302 → 根目錄；資料端點直接 200（`Content-Type: application/octet-stream`，內容是 JSON）；本次誠實 UA、2.5 秒間隔沒有被擋 | 【事實】 |

【推論】資料集已在 data.gov.tw 以 OGDL 釋出的端點，依 OGDL 可以商用；沒找到個別資料集的端點（包括 `DailyMarketReportFut`／`Opt`、`DailyForeignExchangeRates`）catalog 標 `conditional`。上線前建議寄信給 swagger 上的窗口確認（問法同授權研究 §1.9 給櫃買的信）。

### 5.2 分類

| 類別 | 個數 | 判斷 |
|---|---|---|
| 每日行情（期貨、選擇權）、Put/Call 比、Delta | 4 | **P0**（`DailyOptionsDelta` P2） |
| 三大法人（依日期 5、依週 5） | 10 | 依日期 **P0**，依週 P2 |
| 大額交易人未沖銷部位（期貨、選擇權） | 2 | **P0** |
| 每日外幣參考匯率 | 1 | **P0**（匯率） |
| 最後結算價（總表＋9 個分類）、到期履約交割（11） | 21 | 總表 P1，其餘 P2／skip |
| 保證金一覽（6）、可抵繳有價證券（4） | 10 | 指數、股票、ETF 保證金 P1；其餘 skip |
| 股票期貨／選擇權標的、契約調整、調整開盤參考價 | 7 | 標的清單 P1，其餘 P2／skip |
| 未平倉增減、平均成交金額、個股期貨量（`va01`–`va14`） | 14 | P2／skip；`va01` 只有全市場合計 1 列 |
| 每筆成交（期貨、選擇權、價差）與價差概況 | 4 | skip（期貨、選擇權每筆成交是數百 MB） |
| 鉅額交易 | 10 | skip |
| 期貨商財務、交易量、名冊、造市者、結算／保管銀行 | 34 | skip |
| 部位限制、費用表、市場參與者、交易人結構 | 7 | P2／skip；費用表日後期貨帳本可用 |
| 年成交量統計（8）、電子下單統計、股票期貨成交量前十大、盤後豁免代沖銷商品 | 11 | P2／skip |

### 5.3 重要端點的實際內容（2026-11-12 回應）【事實】

| 端點 | 列數 | 重點 |
|---|---|---|
| `DailyMarketReportFut` | 2,278（375 個契約代號） | `Date`（西元）、`Contract`（TX、MTX、TMF、股票期貨代號…）、`ContractMonth(Week)`、開高低收、`SettlementPrice`、`OpenInterest`、`TradingSession`＝「一般」2,097 列／「盤後」181 列。盤後列的 `SettlementPrice` 是 `"NULL"`、`OpenInterest` 是 `"-"` |
| `DailyMarketReportOpt` | 13,914（36 個契約，TXO 7,166 列） | 各履約價 Call/Put；一般 10,186、盤後 3,728 |
| `MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate` | 66（22 契約 × 自營商／投信／外資及陸資） | `ContractCode` 是**中文名稱**（臺股期貨、小型臺指期貨、股票期貨…），和行情的 `TX` 不同，要建對照表；口數與金額（千元）多空、淨額，未平倉多空、淨額 |
| `OpenInterestOfLargeTradersFutures` | 1,410 | `TypeOfTraders` 0／1（推定：全部大額交易人／其中特定法人），`SettlementMonth` 有哨兵值 `666666`、`999912`（推定：週契約、全部月份合計），`ContractName` 例「臺股期貨(TX+MTX/4)」 |
| `PutCallRatio` | 21 | 回應含 2026-10-12～11-11 每日 → 第一次執行可回補一個月 |
| `DailyForeignExchangeRates` | 27 | 2026-10-01～11-11 每日；`USD/NTD`（11/11 為 32.86）、`RMB/NTD`、`EUR/USD`、`USD/JPY`、`GBP/USD`、`AUD/USD`、`USD/HKD`、`USD/RMB`、`USD/ZAR`、`NZD/USD` |
| `FinalSettlementPrice` | 392 | 2025-12 起各到期月份（含週選 W、F） |
| `IndexFuturesAndOptionsMargining` | 31 | 臺股期貨原始保證金 701,000、維持 538,000 等 |
| `va01` | 1 | 只有指數選擇權全市場未平倉與前一日增減（不是各履約價） |

【推論】`DailyMarketReportFut` 某日的「盤後」列，是**前一個營業日 15:00 開始、當日 05:00 結束**的夜盤（期交所把夜盤算在下一個交易日）。例：11/11 TX 近月一般盤收 44,091（+1,445），盤後列收 42,522（−124）。實作前請用兩天的資料再確認一次。

---

## 6. 集保開放資料（`opendata.tdcc.com.tw`）

- **授權**：集保資料集在 data.gov.tw 以政府資料開放授權條款第 1 版釋出（11449、11452、11457、11458、11460、20603、20605…）【單一來源】。catalog 只有標題能對上 data.gov.tw 頁面的才標 `true`，其餘 `conditional`。
- **取得**：沒有清單頁、沒有 `robots.txt`；`HEAD` 會被 302「Security Redirect」，`GET` 正常。正式清單應該在 `openapi.tdcc.com.tw/tdcc-opendata-api-docs`（沙箱連不到）。【事實】
- **試出的編號**：1-x 證券與股務（15）、2-x 集保統計與票券利率（25）、3-x 境外基金（24）、4-x 境外結構型商品（17）、5-x 期貨信託基金（16）、6-x 股東會電子投票，Big5 編碼（5）、7-x 與 1-5 相同的副本（1）；8-x 沒有資料。【事實】

| id | 資料集 | 重點 | 優先 |
|---|---|---|---|
| `1-5` | 集保戶股權分散表 | 已在用（每週） | P0 |
| `2-22` | 有價證券集中保管個別股票異動月分析表－上市證券（data.gov.tw 20603） | 1,377 檔上市股票與 ETF：月底保管千股數、增減、發行千股數、**集保股東戶數**（0050：3,741,557；00878：1,711,531） | **P1** |
| `2-23` | 同－上櫃證券（20605） | 上櫃股票與 ETF | **P1** |
| `2-25` | 上市櫃檯合併保管有價證券週餘額表 | 每檔每週集保餘額與增減（ETF 單位數週變化） | P2 |
| `2-24` | 同－興櫃證券 | 興櫃 | P2 |
| `2-1` | 證券開戶數〔推定〕 | 每月新開戶、累計開戶（散戶熱度） | P2 |
| `2-6` | 帳簿劃撥設質交付統計（11460） | 全市場質押月統計 | P2 |
| `2-19`～`2-21` | 短期票券利率指標〔推定〕 | 10–365 天期；`2-21` 從 2009 年起 | P2 |
| `1-7` | 集中保管交付明細〔推定〕 | 初次上市櫃、減資、有償認股的交付日 | P2 |
| `6-2`、`6-5` | 股東會電子投票日程、召開方式〔推定〕 | 「股東會投票」提醒 | P2 |
| `3-4`、`3-5` | 境外基金淨值、配息〔推定〕 | 只有帳本支援境外基金時才需要 | P2 |

其餘（股務單位、債券、票券報價、境外結構型商品、期信基金）都是 `skip`。

---

## 7. 政府資料開放平臺上的其他機關

> data.gov.tw 本沙箱連不到，下表全是【單一來源：搜尋摘要】，下載網址與欄位要上線前再確認。

| 機關 | 資料集 | 內容 | 頻率 | 授權 | 用途／優先 |
|---|---|---|---|---|---|
| 證交所、櫃買、期交所、集保 | （見第 3–6 節） | data.gov.tw 上的版本就是 OpenAPI | — | OGDL | — |
| 中央銀行 | [7232 銀行間新臺幣對美元收盤匯率](https://data.gov.tw/dataset/7232) | 台北外匯經紀公司資料；`https://cpx.cbc.gov.tw/api/OpenData/FTDOpenData_Day`（JSON：`日期` 西元 YYYYMMDD、`NTD_USD` 字串；一次回 2008-01-02 起全部 4,686 天）、`FTDOpenData_Month`（`西元年月`）、`FTDOpenData_Year`（鍵 `西元年`，實測回的是月資料）【事實：2026-11-12】 | **每營業日**，當天下午公布（2026-11-12 的 32.889 在 17:12 已有；metadata 寫「每1年」不準） | OGDL | **已採用（2026-11-12）**：USD/TWD 唯一換算來源（群組 `cbc`，21:40）；與期交所 USD/NTD 逐日相同 |
| 中央銀行 | [統計資料庫 API](https://cpx.cbc.gov.tw/Data/ExportToAPIInfo) | API-JSON；匯率、利率、貨幣 | 依項目 | 未確認 | 總經 P2 |
| 臺灣銀行 | 牌告匯率 | data.gov.tw 只有「一般外匯收費標準」（24936）與年度即期收盤匯率（NCHC 105011），**沒有每日牌告**；網站 CSV 條款未找到 | — | 未確認 | skip |
| 金管會證期局 | [11109 證券投資信託基金每日淨值](https://data.gov.tw/dataset/11109) | 日期、公司、基金代號、基金名稱、**淨值**、漲跌、類型、幣別、受益憑證代號 | 每日 | OGDL | **ETF 折溢價 P1**（要先確認是否含 ETF、下載網址） |
| 金管會證期局（來源投信投顧公會） | 43476 境內基金基本資料、21404 ISIN／短線交易／月報網址 | 境內基金資料 | 不定期 | OGDL（NCHC 鏡像顯示無資料檔） | P2 |
| 金管會 | [統計資料平台 OpenAPI](https://stat.fsc.gov.tw/api/swagger/openapi.json)（26798 備註） | 證期局、銀行局、保險局統計 | 依資料集 | 推定 OGDL | P2 |
| 國家發展委員會 | [6099 景氣指標及燈號](https://data.gov.tw/dataset/6099)、[31564 景氣指標月刊](https://data.gov.tw/dataset/31564) | 領先／同時／落後指標、燈號、綜合分數 | 每月 | OGDL | 總經、AI context P1 |
| 行政院主計總處 | 總體統計資料庫（CPI、GDP） | data.gov.tw 上**全國** CPI 資料集 id 沒找到（只找到地方政府）；網站的「政府網站資料開放宣告」內容未讀到 | CPI 月、GDP 季 | 未確認 | P2 |
| 財政部關務署 | [6053 海關進出口貿易統計](https://data.gov.tw/dataset/6053) | 年月、出口、進口、出入超；CSV | 每月 | OGDL | P2 |
| 經濟部統計處 | 外銷訂單 | NCHC 鏡像的分項資料集標 OGDL，但顯示「無資料、不定期」 | 每月 | OGDL（鏡像） | P2 |
| 投信投顧公會（SITCA） | 網站統計（基金規模、受益人數） | 網站條款沒找到；只有經金管會上架的上述資料集可用 | — | — | 先問 |
| 證交所 | [ETF 申贖資訊及即時淨值揭露專區](https://dsp.twse.com.tw/)（介接格式 PDF） | 盤中預估淨值、申贖清單 | 盤中 | MIS 體系，非開放授權 | skip |

---

## 8. 公開資訊觀測站（MOPS）

- **沒有找到 MOPS 自己的開放授權**。MOPS 由證交所營運，適用證交所網站條款（禁止未經同意以程式下載）；財報 PDF 的著作權屬發行公司。【單一來源＋授權研究 §2.2】
- **XBRL**：IFRSs XBRL 實例文件的查詢下載在申報／觀測站系統內；data.gov.tw 上**沒有** XBRL 原始檔資料集。【單一來源】
- **可用的是 OpenAPI 版本**：月營收、季報（損益、資產負債，累計數）、營益分析、重大訊息、股利分派、公司基本資料、董監持股、內部人轉讓、股東會——都已透過證交所／櫃買 OpenAPI 以 OGDL 提供。**現金流量表不在任何 OpenAPI 裡**，這是財務頁唯一無法用開放資料補的缺口（目前靠 shioaji-data 季報）。【事實：swagger】
- 結論：MOPS 網站、新版 JSON API、XBRL 下載都標 `commercial_ok: false`，要用就寫信給證交所（詢問信見授權研究 §1.9，可加一題 XBRL）。

---

## 9. 國外

| 來源 | 給什麼 | 授權 | 判斷 |
|---|---|---|---|
| **SEC EDGAR**（`data.sec.gov`） | `submissions/CIK##########.json`（公司、ticker、申報清單）、`api/xbrl/companyfacts/…`（全部 XBRL 財報科目）、`companyconcept`、`frames`、每晚 bulk zip、`www.sec.gov/files/company_tickers.json` | SEC Webmaster FAQ：政府內容與公開申報「free to access and reuse」；申報內的第三方著作另計 | ✅ **P1**：美股財報、事件時間軸。**每秒最多 10 次（所有機器合計）**，User-Agent 必須寫公司／名稱與聯絡信箱（範例格式「Sample Company Name AdminContact@&lt;domain&gt;」），超量封 IP【單一來源】 |
| Nasdaq Trader Symbol Directory | `nasdaqlisted.txt`、`otherlisted.txt`（全美上市代號、ETF 註記） | 檔案層級條款沒找到；Nasdaq 資料政策要求「Nasdaq Information」須授權 | ⚠️ P2；改用 SEC `company_tickers.json` |
| FRED | 美國總經、利率 | API 條款禁止儲存、快取、封存、整批下載，也禁止用於訓練模型；第三方版權序列商用須原擁有者書面同意 | ❌ skip，改抓原機關 |
| U.S. Treasury FiscalData | 匯率（季度報告用）、國債、財政；JSON/CSV/XML、免金鑰 | 第三方目錄稱公有領域；官方條款未讀到 | ✅ P2 |
| U.S. Treasury 殖利率曲線 | Daily Treasury Par Yield Curve | 推定公有領域 | ⚠️ P2 |
| IEX HIST | T+1 的 IEX 單一交易所逐筆資料（pcap），保留 12 個月 | 條款原文未讀到 | ⚠️ skip：不是全市場收盤價 |
| 美股價格 | — | 沒有免費可商用來源 | 維持「使用者自帶 Tiingo 金鑰」或付費授權（授權研究 §2.3） |
| HKEX | 網站資料、市場數據 | 條款禁止抽取資料庫與自動存取；再散布須 HKEX-IS 授權並收費 | ❌ skip |
| JPX | J-Quants 免費方案、上場銘柄一覽 | J-Quants 免費方案限個人、延遲 12 週、禁止提供第三方與商用；可商用的是付費 DataCube | ❌ skip |
| KRX | KRX OPEN API | 條款：只能非商業、不得提供第三方；data.go.kr 的 KRX 上場종목정보（15094775）標「利用許可範圍無限制」，但股價類多為公共누리 2 型（禁止商用） | ❌ skip（上場清單 ⚠️） |
| SGX | 市場數據 | 再散布需授權（即時、延遲分別計費） | ❌ skip |
| 上交所、深交所 | 行情、公告 | 沒找到開放授權；行情由授權資訊商提供 | ❌ skip |

---

## 10. 覆蓋地圖

| Forliosa 功能 | 現在有（已用） | 開放資料可以補 | 仍是缺口 |
|---|---|---|---|
| **帳本估值** | 上市、上櫃股票與 ETF 收盤價（`STOCK_DAY_ALL`、`tpex_mainboard_*`）；USD/TWD：央行 7232（2026-11-12 起） | **USD/TWD**：~~期交所 `DailyForeignExchangeRates`（P0）~~ 只存檔、央行 7232（已採用）；**基準 ^TAIEXTR**：`MI_INDEX`／`MFI94U`（P0）、櫃買報酬指數（P1）；興櫃：`tpex_esb_latest_statistics`（P2） | 美股價格；開始存檔前的歷史收盤 |
| **個股頁・總覽** | 現價、本益比、殖利率、注意／處置、商品主檔（shioaji-data） | 公司基本資料與已發行股數 → 市值（`t187ap03_L`、`mopsfin_t187ap03_O`，P0）；停牌、全額交割、管理股票（`TWTAWU`、`TWT85U`、`tpex_cmode`、`tpex_spendi_today`，P1）；下市（`suspendListingCsvAndHtml`，P1） | 盤中走勢（需付費授權） |
| **估值** | 本益比、殖利率、淨值比（存檔累積中） | 本益比依據財報季（`BWIBBU_d`，P1）；產業 EPS（`t187ap14_L`、`mopsfin_t187ap14_O`，P2） | 存檔前的歷史估值 |
| **財務** | 月營收、季報損益與資產負債、利潤率 | 財測達成（P2） | **現金流量表**（OpenAPI 沒有，只有 shioaji-data） |
| **籌碼** | 上櫃法人、上櫃外資持股、融資融券、集保分散 | 類股外資持股（`MI_QFIIS_cat`，P1）；借券（`TWT96U`、`tpex_margin_sbl`）；董監持股與質押（`t187ap11_L`、`t187ap09_L`…，P1）；**集保股東戶數**（集保 2-22／2-23，P1） | **上市個股三大法人與外資持股**（只能 E-Shop 付費或書面同意） |
| **股利** | 除權息預告（`TWT48U_ALL`、`tpex_exright_prepost`）、參考價（`TWT84U`） | **上市公司董事會／股東會決議的股利與來源**（`t187ap45_L`，P0）；上櫃除權息計算結果（`tpex_exright_daily`，P1）；股東會預擬配發（`t187ap38_L`，P2） | **上櫃公司的決議股利**（`mopsfin_t187ap39_O` 停在 2021）；存檔前的歷年股利（OpenAPI 只有當期） |
| **事件** | 重大訊息、股東會、財報／營收／法說日期 | 停資停券（`BFI84U`、`tpex_margin_trading_term`，P1）；內部人轉讓申報（`t187ap12_L`、`mopsfin_t187ap12_O`，P1）；電子投票期間（集保 6-2，P2）；裁罰、經營權異動（P2） | — |
| **ETF 頁** | 基本資料（`t187ap47_L` 存檔，尚無端點）、行情、除息 | **受益人數**（集保 2-22／2-23，P1）；定期定額排行（`ETFRank`，P1）；追蹤指數報酬（`MI_INDEX`、`TAI50I`，P0／P1）；**淨值與折溢價**（金管會 11109，P1，待確認）；單位數週變化（集保 2-25，P2） | 成分股與 PCF、盤中預估淨值（投信網站、MIS，需同意） |
| **期貨／選擇權**（未來） | — | 期交所行情、三大法人、大額交易人、PCR、最後結算價、保證金、標的清單（第 12 節） | 盤中行情（需授權）；期交所網站的歷史回補（需同意） |
| **美股** | 無（`/quote` 404） | SEC EDGAR 財報與事件（P1） | 價格 |
| **匯率** | ~~固定 31.5~~ 央行 7232（2026-11-12 起） | 期交所參考匯率只存檔（授權有條件，數字與央行相同） | — |
| **AI context** | 重大訊息、證交所新聞 | 大盤指數與成交（`MI_INDEX`、`FMTQIK`）、期貨籌碼（期交所）、景氣燈號（國發會 6099）、市場寬度（`twtazu_od`，疑似停更） | 媒體新聞（需授權） |

---

## 11. 建議加入清單（依優先順序）

工作量以現有的存檔架構估計（`archive.py` 冪等 upsert、`marketdata/opendata.py` 解析、`datapolicy.DATASETS` 顯名、2026-11-12 真實回應當 fixture）：**S** ≤ 半天、**M** 1–2 天、**L** 3–5 天（前端串接另計）。

| # | 加什麼 | 端點 | 解決什麼 | 工作量 | 優先 |
|---|---|---|---|---|---|
| 1 | 指數與報酬指數每日存檔 | 證交所 `MI_INDEX`（＋`MFI94U` 回補本月） | `^TAIEXTR` 基準、ETF 追蹤指數 | S | **P0** |
| 2 | USD/TWD 等外幣參考匯率 | 期交所 `DailyForeignExchangeRates`（只存檔）→ **改用央行 7232**（`cpx.cbc.gov.tw/api/OpenData/FTDOpenData_Day`，2026-11-12 完成） | 取代固定 31.5；美股帳戶估值 | S（＋新主機加白名單） | **P0** |
| 3 | 股利分派決議（上市） | 證交所 `t187ap45_L`（櫃買版 `mopsfin_t187ap39_O` 已停更） | 股利頁提早顯示、資本公積配發的稅務處理 | M | **P0** |
| 4 | 公司基本資料 | `t187ap03_L`、`mopsfin_t187ap03_O` | 已發行股數→市值、產業、公司小卡 | S–M | **P0** |
| 5 | 期交所三大法人（依日期 5 個）＋大額交易人（2）＋Put/Call 比 | 見第 12 節 | 大盤籌碼卡、AI 盤勢 | M | **P0**（期貨功能）／P1（現在） |
| 6 | 期貨、選擇權每日行情 | `DailyMarketReportFut`、`DailyMarketReportOpt` | 期貨頁、台指期夜盤 | M–L | **P0**（期貨功能） |
| 7 | 集保個股異動月分析表 | 集保 `2-22`、`2-23` | ETF 受益人數、個股股東戶數趨勢 | S–M | P1 |
| 8 | 本益比依據的財報季 | `BWIBBU_d` | 估值頁標示 | S | P1 |
| 9 | 大盤 K 線與成交值 | `MI_5MINS_HIST`、`FMTQIK`、`tpex_index`、`tpex_reward_index` | 首頁大盤卡、上櫃基準 | S | P1 |
| 10 | 交易狀態 | `TWTAWU`、`TWT85U`、`tpex_cmode`、`tpex_spendi_today`、`suspendListingCsvAndHtml` | 停牌、全額交割、管理股票、下市標示 | M | P1 |
| 11 | 停資停券 | `BFI84U`、`tpex_margin_trading_term` | 事件頁 | S | P1 |
| 12 | 上櫃除權息計算結果 | `tpex_exright_daily` | 核對自算參考價 | S | P1 |
| 13 | 董監持股、質押、內部人轉讓 | `t187ap11_L`、`t187ap09_L`、`t187ap12_L`＋櫃買對應 | 籌碼與事件；**個資**只存必要欄位、提供刪除管道 | M | P1 |
| 14 | 美股財報與事件 | SEC `submissions`、`companyfacts`、`company_tickers.json` | 美股個股頁（價格仍缺） | L | P1 |
| 15 | ETF 淨值與折溢價 | 金管會 data.gov.tw 11109 | ETF 頁折溢價 | M（先確認內容） | P1 |

下一批（P1／P2）：`MI_QFIIS_cat`、`ETFRank`、`TAI50I`、國發會景氣燈號 6099、~~央行 7232~~（2026-11-12 已採用）、期交所保證金與股票期貨標的、`tpex_margin_sbl`、集保 2-25。

---

## 12. 期交所實作規格

### 12.1 要每天存的端點

| 端點 | 每日列數 | 存法 | 顯名資料集名稱（照 swagger summary） |
|---|---|---|---|
| `DailyMarketReportFut` | ≈2,300 | 全存 | 期貨每日交易行情 |
| `DailyMarketReportOpt` | ≈14,000 | 先只存 TXO、TEO、TFO 與股票／ETF 選擇權的近兩個到期月；或全存（一年約 350 萬列） | 選擇權每日交易行情 |
| `MarketDataOfMajorInstitutionalTradersGeneralBytheDate` | 3 | 全存 | 三大法人-總表-依日期 |
| `MarketDataOfMajorInstitutionalTradersDividedByFuturesAndOptionsBytheDate` | 3 | 全存 | 三大法人-區分期貨與選擇權二類-依日期 |
| `MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate` | 66 | 全存 | 三大法人-區分各期貨契約-依日期 |
| `MarketDataOfMajorInstitutionalTradersDetailsOfOptionsContractsBytheDate` | 15 | 全存 | 三大法人-區分各選擇權契約-依日期 |
| `MarketDataOfMajorInstitutionalTradersDetailsOfCallsAndPutsBytheDate` | 30 | 全存 | 三大法人-選擇權買賣權分計-依日期 |
| `OpenInterestOfLargeTradersFutures` | ≈1,400 | 全存 | 期貨大額交易人未沖銷部位資料 |
| `OpenInterestOfLargeTradersOptions` | ≈320 | 全存 | 選擇權大額交易人未沖銷部位資料 |
| `PutCallRatio` | 1（回應含近 1 個月） | upsert；第一次執行即回補一個月 | 臺指選擇權Put/Call比 |
| `DailyForeignExchangeRates` | 1（回應含近 6 週） | upsert；第一次執行即回補 6 週 | 每日外幣參考匯率 |
| `FinalSettlementPrice` | 每次到期 | 每週 upsert | 最後結算價 |
| `IndexFuturesAndOptionsMargining`、`SingleStockFuturesMargining`、`SingleStockFuturesETFMargining` | 數十到數百 | 每天存快照，或只在內容變動時新增一筆 | 保證金一覽表-股價指數類／股票類／股票類(ETF) |
| `SSFLists`、`SSOLists` | 數百 | 每週 | 股票期貨交易標的／股票選擇權交易標的 |

**不要抓**：`TimeAndSalesData`、`OptionsTimeAndSalesData`（數百 MB）、`TimeAndSalesDataOnCalendarSpreadOrders`（16 MB）。

### 12.2 排程與連線

- **白名單**：`marketdata/http.py` 的 `ALLOWED_URL_PREFIXES` 加 `https://openapi.taifex.com.tw/v1/`；`DEFAULT_LIMITER.per_host` 加 `"taifex.com.tw": 2.0`。`follow_redirects=False` 可以照舊（資料端點直接 200；只有 `/v1/swagger.json` 會 302）。【事實】
- **交易日**：沿用證交所 `holidaySchedule`（期貨與股票同日休市）【推論】。
- **時間**：既有 worker 的 21:40 那次加跑期交所（所有日資料都已公布，冪等）；若要盤後即時，另加 15:40（行情、三大法人）。夜盤列算在「下一個交易日」（見 5.3 推論），不需要清晨另跑。【推論】
- 回應的 `Content-Type` 是 `application/octet-stream`，要直接當 JSON 解析（`HttpFetcher.get_json` 本來就不看 Content-Type）。【事實】

### 12.3 資料表建議

```text
taifex_futures_daily   PK(trade_date, session, contract, contract_month)
  session: 'regular' | 'after_hours'   （TradingSession 一般／盤後）
  open, high, low, last, change, change_pct, volume, settlement_price, open_interest,
  best_bid, best_ask, hist_high, hist_low, halted, spread_volume, source, fetched_at
taifex_options_daily   PK(trade_date, session, contract, contract_month, strike, call_put)
  open, high, low, close, volume, settlement_price, open_interest, best_bid, best_ask, …
taifex_institutional   PK(trade_date, scope, contract_name, call_put, investor)
  scope: 'all' | 'fut_opt' | 'futures' | 'options' | 'calls_puts'
  investor: '自營商' | '投信' | '外資及陸資'
  long_vol, long_value_k, short_vol, short_value_k, net_vol, net_value_k,
  oi_long, oi_long_value_k, oi_short, oi_short_value_k, oi_net, oi_net_value_k
taifex_large_traders   PK(trade_date, kind, contract, call_put, settlement_month, trader_type)
  kind: 'futures' | 'options'; trader_type: 0 | 1
  top5_buy, top5_sell, top10_buy, top10_sell, market_oi
taifex_put_call_ratio  PK(trade_date)  put_vol, call_vol, pc_vol_ratio, put_oi, call_oi, pc_oi_ratio
fx_reference_rates     PK(rate_date, pair)  rate, source='taifex-openapi'
taifex_contract_map    PK(contract_code)  name_zh   （三大法人用中文名稱、行情用代號，需要對照）
```

**解析陷阱**【事實】：數字都是字串；缺值是 `"NULL"`、`"-"`、`""`；百分比有 `"1.90%"` 與 `"107.08"`（欄名 `PutCallVolumeRatio%`）兩種寫法；欄名含括號與斜線（`TradingValue(Long)(Thousands)`、`USD/NTD`）；`ContractMonth(Week)` 有 `202611W2`、`202611F2` 之類；`SettlementMonth` 有 `666666`、`999912`；日期是**西元** `YYYYMMDD`（和證交所的民國年不同）；三大法人總表的金額單位是百萬元，各契約明細是千元。

### 12.4 顯名與授權登記

- `datapolicy.py` 新增 `TAIFEX = "臺灣期貨交易所"`、provider key `taifex-openapi`、每個端點一筆 `Dataset`，例如：
  - 「臺灣期貨交易所〈期貨每日交易行情〉（2026），依政府資料開放授權條款第 1 版」
  - 「臺灣期貨交易所〈三大法人-區分各期貨契約-依日期〉（2026），依政府資料開放授權條款第 1 版」
  - 「臺灣期貨交易所〈每日外幣參考匯率〉（2026），依政府資料開放授權條款第 1 版」
- `GET /meta/attributions` 照樣附 OGDL 固定聲明與 `https://data.gov.tw/license`。
- 在期交所確認前，`DailyMarketReportFut`／`Opt`、`DailyForeignExchangeRates` 等 `conditional` 端點建議用一個設定開關控制是否顯示【推論】。

### 12.5 產品上怎麼用（初版）

- **大盤籌碼卡**：外資及陸資台指期淨未平倉口數與日變化、三大法人選擇權買權／賣權淨額、前十大交易人淨部位、Put/Call 未平倉比。
- **期貨頁**：台指期近月日線（一般＋夜盤兩條）、結算價、未平倉；保證金。
- **個股頁**：「有股票期貨／選擇權」標記（`SSFLists`、`SSOLists`）。
- **匯率**：USD/TWD 改用央行 7232〈銀行間新臺幣對美元收盤匯率〉（2026-11-12；顯示「中央銀行〈銀行間新臺幣對美元收盤匯率〉（年），依政府資料開放授權條款第 1 版」）。期交所的參考匯率只存檔。
- **AI context**：「外資台指期淨空單 X 口（較前日 +Y）」「Put/Call 未平倉比 65%」。

---

## 13. 不確定、未能驗證的事

1. **期交所 OpenAPI 的授權**：swagger 沒有連 data.gov.tw；期交所中文使用條款是否有「已授權政府資料開放平臺」例外，搜尋結果互相矛盾；`DailyMarketReportFut`／`Opt`、`DailyForeignExchangeRates`、選擇權大額交易人等沒找到個別的 data.gov.tw 資料集。→ 寄信 s0160116@taifex.com.tw 確認。
2. **data.gov.tw 全部內容**（金管會 11109、國發會 6099、關務署 6053…）：沙箱連不到，只有搜尋摘要；下載網址、欄位、是否仍在更新都沒驗證。金管會 11109 是否包含 ETF 是 ETF 折溢價的關鍵。央行 7232 已在 2026-11-12 驗證（`cpx.cbc.gov.tw` 開通後直接下載）並採用。
3. **主計總處全國 CPI／GDP**：沒找到 data.gov.tw 資料集 id，網站資料開放宣告未讀到。
4. **集保資料集標題**：只有 1-2、1-5、2-6、2-22、2-23、2-25、4-5、4-6 等能對上 data.gov.tw；其他標題依欄位推定。`openapi.tdcc.com.tw` 的 OAS 文件連不到。
5. **證交所 2 個、櫃買 0 個端點**三次呼叫都失敗，欄位只取自 swagger：證交所 `/exchangeReport/BFI61U`、證交所 `/opendata/t187ap32_L`；另 `t187ap37_L` 太大沒取得內容。這三個都是 skip／P2。
6. **夜盤日期歸屬**（5.3 推論）、大額交易人 `TypeOfTraders` 與 `SettlementMonth` 哨兵值的意義，要用兩天資料或期交所說明再確認。
7. **SEC EDGAR**：sec.gov 連不到；`companyconcept`、`frames`、bulk zip、`company_tickers.json` 的網址是研究者記憶，待核對；Website Dissemination 頁面原文未讀到。
8. **Nasdaq Trader、IEX HIST、Treasury** 的條款原文都沒讀到。
9. `twtazu_od`（漲跌家數）出表日期停在 1150605、`t187ap09_L`／`mopsfin_t187ap09_O`（董監質押）出表日期 1150819，是停更還是不定期更新未確認。櫃買 `mopsfin_t187ap39_O` 停在 2021-08 是確定的（2026-11-12 回應）。
10. 各端點的**實際公布時間**沒有官方文件；本文的排程建議是推論。

---

## 14. 主要來源（讀取日期 2026-11-12）

- 直接讀取【事實】：[證交所 OpenAPI swagger](https://openapi.twse.com.tw/v1/swagger.json)、[櫃買 OpenAPI swagger](https://www.tpex.org.tw/openapi/swagger.json)、[期交所 OpenAPI swagger](https://openapi.taifex.com.tw/swagger.json) 與三者全部端點的實際回應；集保 `https://opendata.tdcc.com.tw/getOD.ashx?id=…` 共 103 個資料集；本 repo `datapolicy.py`、`marketdata/http.py`、`archive.py`、`marketdata/opendata.py`、`marketdata/tpex.py`、`CONTRACT_NOTES.md`、`docs/research/data-sources-licensing.md`。
- 搜尋摘要【單一來源】：data.gov.tw 資料集 [7232](https://data.gov.tw/dataset/7232)、[11109](https://data.gov.tw/dataset/11109)、[6099](https://data.gov.tw/dataset/6099)、[31564](https://data.gov.tw/dataset/31564)、[6053](https://data.gov.tw/dataset/6053)、[11592](https://data.gov.tw/dataset/11592)、[11600](https://data.gov.tw/dataset/11600)、[45747](https://data.gov.tw/dataset/45747)、[11322](https://data.gov.tw/en/datasets/11322)、[11338](https://data.gov.tw/en/datasets/11338)、[20603](https://data.gov.tw/en/datasets/20603)、[20605](https://data.gov.tw/en/datasets/20605)、[11457](https://data.gov.tw/dataset/11457)、[11460](https://data.gov.tw/dataset/11460)、[26798](https://data.gov.tw/dataset/26798)；[期交所網站使用條款](https://www.taifex.com.tw/cht/edu/userTerms)、[英文版](https://www.taifex.com.tw/enl/eduEng/userTerms)；[央行統計資料庫 API 說明](https://cpx.cbc.gov.tw/Data/ExportToAPIInfo)；[SEC Accessing EDGAR Data](https://www.sec.gov/os/accessing-edgar-data)、[SEC Webmaster FAQ](https://www.sec.gov/os/webmaster-faq)；[Nasdaq Trader 欄位定義](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs)、[Nasdaq Data AI Policy](https://nasdaqtrader.com/content/AdministrationSupport/AgreementsData/Data_AI_Policy.pdf)；[FRED API Terms](https://fred.stlouisfed.org/docs/api/terms_of_use.html)；[IEX Market Data](https://iextrading.com/trading/market-data/)；[HKEX Terms of Use](https://www.hkex.com.hk/Global/Exchange/Terms-of-Use)；[J-Quants Terms](https://jpx-jquants.com/en/termsofservice)；[KRX OPEN API 條款](https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO005.jsp)、[data.go.kr 15094775](https://www.data.go.kr/data/15094775/openapi.do)；[SGX Market Data Policy](https://www.datadirect.sgx.com/Market-Data-Policy)。

---

## 附錄 A：全部端點一覽

> 由 `open-data-catalog.json` 產生；完整欄位（key_fields、history_depth、授權、驗證方式）請看 JSON。「回應」欄：✓＝本次取得真實回應，—＝只有 swagger 或搜尋摘要。

### 臺灣證券交易所 OpenAPI（143）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `/opendata/t187ap46_L_21` | 上市公司企業ESG資訊揭露彙總資料-職業安全衛生 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap45_L` | 上市公司股利分派情形 | dividends | P0 |  | ✓ | ✓ |
| `/opendata/t187ap46_L_20` | 上市公司企業ESG資訊揭露彙總資料-反競爭行為法律訴訟 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap46_L_19` | 上市公司企業ESG資訊揭露彙總資料-風險管理政策 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap46_L_18` | 上市公司企業ESG資訊揭露彙總資料-持股及控制力 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap46_L_17` | 上市公司企業ESG資訊揭露彙總資料-普惠金融 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap46_L_16` | 上市公司企業ESG資訊揭露彙總資料-資訊安全 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap46_L_15` | 上市公司企業ESG資訊揭露彙總資料-社區關係 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap46_L_14` | 上市公司企業ESG資訊揭露彙總資料-產品品質與安全 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap46_L_13` | 上市公司企業ESG資訊揭露彙總資料-供應鏈管理 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap46_L_12` | 上市公司企業ESG資訊揭露彙總資料-食品安全 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap46_L_11` | 上市公司企業ESG資訊揭露彙總資料-產品生命週期 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap46_L_10` | 上市公司企業ESG資訊揭露彙總資料-燃料管理 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap46_L_9` | 上市公司企業ESG資訊揭露彙總資料-功能性委員會 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap46_L_8` | 上市公司企業ESG資訊揭露彙總資料-氣候相關議題管理 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap47_L` | 基金基本資料彙總表 | etf | P0 | ✓ | ✓ | ✓ |
| `/opendata/t187ap05_P` | 公開發行公司每月營業收入彙總表 | financials | skip |  | ✓ | ✓ |
| `/opendata/t187ap46_L_7` | 上市公司企業ESG資訊揭露彙總資料-投資人溝通 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap46_L_6` | 上市公司企業ESG資訊揭露彙總資料-董事會 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap46_L_5` | 上市公司企業ESG資訊揭露彙總資料-人力發展 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap46_L_4` | 上市公司企業ESG資訊揭露彙總資料-廢棄物管理 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap46_L_3` | 上市公司企業ESG資訊揭露彙總資料-水資源管理 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap46_L_2` | 上市公司企業ESG資訊揭露彙總資料-能源管理 | esg | P2 |  | ✓ | ✓ |
| `/opendata/t187ap46_L_1` | 上市公司企業ESG資訊揭露彙總資料-溫室氣體排放 | esg | P2 |  | ✓ | ✓ |
| `/ETFReport/ETFRank` | 定期定額交易戶數統計排行月報表 | etf | P1 |  | ✓ | ✓ |
| `/brokerService/secRegData` | 開辦定期定額業務證券商名單 | reference | P2 |  | ✓ | ✓ |
| `/opendata/t187ap07_X_ci` | 公發公司資產負債表-一般業 | financials | skip |  | ✓ | ✓ |
| `/opendata/t187ap07_X_mim` | 公發公司資產負債表-異業 | financials | skip |  | ✓ | ✓ |
| `/opendata/t187ap06_X_basi` | 公發公司綜合損益表-金融業 | financials | skip |  | ✓ | ✓ |
| `/opendata/t187ap06_X_bd` | 公發公司綜合損益表-證券期貨業 | financials | skip |  | ✓ | ✓ |
| `/opendata/t187ap06_X_ci` | 公發公司綜合損益表-一般業 | financials | skip |  | ✓ | ✓ |
| `/opendata/t187ap06_X_fh` | 公發公司綜合損益表-金控業 | financials | skip |  | ✓ | ✓ |
| `/opendata/t187ap06_X_ins` | 公發公司綜合損益表-保險業 | financials | skip |  | ✓ | ✓ |
| `/opendata/t187ap06_X_mim` | 公發公司綜合損益表-異業 | financials | skip |  | ✓ | ✓ |
| `/news/eventList` | 證交所活動訊息 | news | P2 |  | ✓ | ✓ |
| `/company/applylistingForeign` | 外國公司向證交所申請第一上市之公司 | events | P2 |  | ✓ | ✓ |
| `/company/newlisting` | 最近上市公司 | events | P2 |  | ✓ | ✓ |
| `/company/suspendListingCsvAndHtml` | 終止上市公司 | events | P1 |  | ✓ | ✓ |
| `/brokerService/brokerList` | 證券商總公司基本資料 | reference | skip |  | ✓ | ✓ |
| `/news/newsList` | 證交所新聞 | news | P0 | ✓ | ✓ | ✓ |
| `/exchangeReport/BWIBBU_ALL` | 上市個股日本益比、殖利率及股價淨值比（依代碼查詢） | valuation | P0 | ✓ | ✓ | ✓ |
| `/exchangeReport/STOCK_DAY_AVG_ALL` | 上市個股日收盤價及月平均價 | price | P2 |  | ✓ | ✓ |
| `/exchangeReport/STOCK_DAY_ALL` | 上市個股日成交資訊 | price | P0 | ✓ | ✓ | ✓ |
| `/exchangeReport/FMSRFK_ALL` | 上市個股月成交資訊 | price | P2 |  | ✓ | ✓ |
| `/exchangeReport/FMNPTK_ALL` | 上市個股年成交資訊 | price | P2 |  | ✓ | ✓ |
| `/exchangeReport/MI_INDEX` | 每日收盤行情-大盤統計資訊 | index | P0 |  | ✓ | ✓ |
| `/company/applylistingLocal` | 申請上市之本國公司 | events | P2 |  | ✓ | ✓ |
| `/fund/MI_QFIIS_cat` | 集中市場外資及陸資投資類股持股比率表 | chips | P1 |  | ✓ | ✓ |
| `/fund/MI_QFIIS_sort_20` | 集中市場外資及陸資持股前 20 名彙總表 | chips | P2 |  | ✓ | ✓ |
| `/exchangeReport/BFI61U` | 中央登錄公債補息資料表 | bonds | skip |  | ✓ | — |
| `/exchangeReport/TWT88U` | 上市個股首五日無漲跌幅 | status | P2 |  | ✓ | ✓ |
| `/Announcement/BFZFZU_T` | 投資理財節目異常推介個股 | status | P2 |  | ✓ | ✓ |
| `/exchangeReport/TWTB4U` | 上市股票每日當日沖銷交易標的及統計 | chips | P2 |  | ✓ | ✓ |
| `/exchangeReport/TWTBAU1` | 集中市場暫停先賣後買當日沖銷交易標的預告表 | status | P2 |  | ✓ | ✓ |
| `/exchangeReport/TWTBAU2` | 集中市場暫停先賣後買當日沖銷交易歷史查詢 | status | P2 |  | ✓ | ✓ |
| `/exchangeReport/MI_INDEX4` | 每日上市上櫃跨市場成交資訊 | market | P2 |  | ✓ | ✓ |
| `/indicesReport/FRMSA` | 寶島股價指數歷史資料 | index | P2 |  | ✓ | ✓ |
| `/indicesReport/TAI50I` | 臺灣 50 指數歷史資料 | index | P1 |  | ✓ | ✓ |
| `/exchangeReport/MI_5MINS` | 每 5 秒委託成交統計 | market | skip |  | ✓ | ✓ |
| `/exchangeReport/FMTQIK` | 集中市場每日市場成交資訊 | market | P1 |  | ✓ | ✓ |
| `/exchangeReport/MI_INDEX20` | 集中市場每日成交量前二十名證券 | market | P2 |  | ✓ | ✓ |
| `/exchangeReport/TWT53U` | 集中市場盤後零股交易行情單 | price | P2 |  | ✓ | ✓ |
| `/exchangeReport/TWTAWU` | 集中市場暫停交易證券 | status | P1 |  | ✓ | ✓ |
| `/exchangeReport/BFT41U` | 集中市場盤後定價交易 | price | skip |  | ✓ | ✓ |
| `/exchangeReport/BFI84U` | 集中市場停資停券預告表 | events | P1 |  | ✓ | ✓ |
| `/exchangeReport/MI_MARGN` | 集中市場融資融券餘額 | chips | P0 | ✓ | ✓ | ✓ |
| `/indicesReport/MI_5MINS_HIST` | 發行量加權股價指數歷史資料 | index | P0 |  | ✓ | ✓ |
| `/block/BFIAUU_d` | 集中市場鉅額交易日成交量值統計 | market | P2 |  | ✓ | ✓ |
| `/block/BFIAUU_m` | 集中市場鉅額交易月成交量值統計 | market | skip |  | ✓ | ✓ |
| `/block/BFIAUU_y` | 集中市場鉅額交易年成交量值統計 | market | skip |  | ✓ | ✓ |
| `/exchangeReport/STOCK_FIRST` | 每日第一上市外國股票成交量值 | price | P2 |  | ✓ | ✓ |
| `/exchangeReport/TWT85U` | 集中市場證券變更交易 | status | P1 |  | ✓ | ✓ |
| `/holidaySchedule/holidaySchedule` | 有價證券集中交易市場開（休）市日期 | calendar | P0 | ✓ | ✓ | ✓ |
| `/exchangeReport/BWIBBU_d` | 上市個股日本益比、殖利率及股價淨值比（依日期查詢） | valuation | P1 |  | ✓ | ✓ |
| `/indicesReport/MFI94U` | 發行量加權股價報酬指數 | index | P0 |  | ✓ | ✓ |
| `/SBL/TWT96U` | 上市上櫃股票當日可借券賣出股數 | chips | P2 |  | ✓ | ✓ |
| `/exchangeReport/TWT84U` | 上市個股股價升降幅度 | price | P0 | ✓ | ✓ | ✓ |
| `/opendata/twtazu_od` | 集中市場漲跌證券數統計表 | market | P2 |  | ✓ | ✓ |
| `/opendata/t187ap04_L` | 上市公司每日重大訊息 | events | P0 | ✓ | ✓ | ✓ |
| `/opendata/t187ap03_L` | 上市公司基本資料 | profile | P0 |  | ✓ | ✓ |
| `/opendata/t187ap05_L` | 上市公司每月營業收入彙總表 | financials | P0 | ✓ | ✓ | ✓ |
| `/opendata/t187ap01` | 券商業務別人員數 | reference | skip |  | ✓ | ✓ |
| `/opendata/t187ap02_L` | 上市公司持股逾 10% 大股東名單 | governance | P1 |  | △ | ✓ |
| `/opendata/t187ap14_L` | 上市公司各產業EPS統計資訊 | financials | P2 |  | ✓ | ✓ |
| `/opendata/t187ap15_L` | 上市公司截至各季綜合損益財測達成情形(簡式) | financials | P2 |  | ✓ | ✓ |
| `/opendata/t187ap16_L` | 上市公司當季綜合損益經會計師查核(核閱)數與當季預測數差異達百分之十以上者，或截至當季累計差異達百分之二十以上者(簡式) | financials | P2 |  | ✓ | ✓ |
| `/opendata/t187ap17_L` | 上市公司營益分析查詢彙總表(全體公司彙總報表) | financials | P0 | ✓ | ✓ | ✓ |
| `/opendata/t187ap20` | 各券商每月月計表 | reference | skip |  | ✓ | ✓ |
| `/opendata/t187ap21` | 各券商收支概況表資料 | reference | skip |  | ✓ | ✓ |
| `/opendata/t187ap18` | 證券商基本資料 | reference | skip |  | ✓ | ✓ |
| `/opendata/t187ap19` | 電子式交易統計資訊 | market | skip |  | ✓ | ✓ |
| `/opendata/t187ap08_L` | 上市公司董事、監察人持股不足法定成數彙總表 | governance | P2 |  | △ | ✓ |
| `/opendata/t187ap11_L` | 上市公司董監事持股餘額明細資料 | governance | P1 |  | △ | ✓ |
| `/opendata/t187ap12_L` | 上市公司每日內部人持股轉讓事前申報表-持股轉讓日報表 | events | P1 |  | △ | ✓ |
| `/opendata/t187ap13_L` | 上市公司每日內部人持股轉讓事前申報表-持股未轉讓日報表 | events | P2 |  | △ | ✓ |
| `/opendata/t187ap22_L` | 上市公司金管會證券期貨局裁罰案件專區 | events | P2 |  | ✓ | ✓ |
| `/opendata/t187ap30_L` | 上市公司獨立董監事兼任情形彙總表 | governance | P2 |  | △ | ✓ |
| `/opendata/t187ap29_A_L` | 上市公司董事酬金相關資訊 | governance | P2 |  | △ | ✓ |
| `/opendata/t187ap29_B_L` | 上市公司監察人酬金相關資訊 | governance | P2 |  | △ | ✓ |
| `/opendata/t187ap29_C_L` | 上市公司合併報表董事酬金相關資訊 | governance | skip |  | △ | ✓ |
| `/opendata/t187ap29_D_L` | 上市公司合併報表監察人酬金相關資訊 | governance | skip |  | △ | ✓ |
| `/opendata/t187ap23_L` | 上市公司違反資訊申報、重大訊息及說明記者會規定專區 | events | P2 |  | ✓ | ✓ |
| `/opendata/t187ap31_L` | 上市公司財務報告經監察人承認情形 | financials | skip |  | ✓ | ✓ |
| `/opendata/t187ap36_L` | 上市認購(售)權證年度發行量概況統計表 | warrants | skip |  | ✓ | ✓ |
| `/opendata/t187ap03_P` | 公開發行公司基本資料 | profile | skip |  | ✓ | ✓ |
| `/opendata/t187ap43_L` | 上市認購(售)權證交易人數檔 | warrants | skip |  | ✓ | ✓ |
| `/opendata/t187ap42_L` | 上市認購(售)權證每日成交資料檔 | warrants | P2 |  | ✓ | ✓ |
| `/announcement/punish` | 集中市場公布處置股票 | status | P0 | ✓ | ✓ | ✓ |
| `/opendata/t187ap10_L` | 上市公司董事、監察人持股不足法定成數連續達3個月以上彙總表 | governance | P2 |  | △ | ✓ |
| `/opendata/t187ap38_L` | 上市公司股東會公告-召集股東常(臨時)會公告資料彙總表(95年度起適用) | events | P2 |  | ✓ | ✓ |
| `/opendata/t187ap24_L` | 上市公司經營權及營業範圍異(變)動專區-經營權異動公司 | events | P2 |  | ✓ | ✓ |
| `/opendata/t187ap37_L` | 上市權證基本資料彙總表 | warrants | P2 |  | ✓ | — |
| `/opendata/t187ap26_L` | 上市公司經營權及營業範圍異(變)動專區-經營權異動且營業範圍重大變更停止買賣公司 | events | P2 |  | ✓ | ✓ |
| `/opendata/t187ap41_L` | 上市公司召開股東常 (臨時) 會日期、地點及採用電子投票情形等資料彙總表 | events | P0 | ✓ | ✓ | ✓ |
| `/announcement/notetrans` | 集中市場公布注意累計次數可能達處置標準資訊 | status | P2 |  | ✓ | ✓ |
| `/announcement/notice` | 集中市場當日公布注意股票 | status | P0 | ✓ | ✓ | ✓ |
| `/opendata/t187ap25_L` | 上市公司經營權及營業範圍異(變)動專區-營業範圍重大變更公司 | events | P2 |  | ✓ | ✓ |
| `/opendata/t187ap27_L` | 上市公司經營權及營業範圍異(變)動專區-經營權異動且營業範圍重大變更列為變更交易公司 | events | P2 |  | ✓ | ✓ |
| `/opendata/t187ap32_L` | 上市公司公司治理之相關規程規則 | governance | skip |  | ✓ | — |
| `/opendata/t187ap33_L` | 上市公司董事長是否兼任總經理 | governance | P2 |  | ✓ | ✓ |
| `/opendata/t187ap09_L` | 上市公司董事、監察人質權設定占董事及監察人實際持有股數彙總表 | governance | P1 |  | △ | ✓ |
| `/opendata/OpenData_BRK01` | 證券商營業員男女人數統計資料 | reference | skip |  | ✓ | ✓ |
| `/opendata/OpenData_BRK02` | 證券商分公司基本資料 | reference | skip |  | ✓ | ✓ |
| `/opendata/t187ap34_L` | 上市公司採累積投票制、全額連記法、候選人提名制選任董監事及當選資料彙總表 | governance | skip |  | △ | ✓ |
| `/opendata/t187ap35_L` | 上市公司股東行使提案權情形彙總表 | governance | skip |  | ✓ | ✓ |
| `/exchangeReport/TWT48U_ALL` | 上市股票除權除息預告表 | dividends | P0 | ✓ | ✓ | ✓ |
| `/opendata/t187ap06_L_bd` | 上市公司綜合損益表(證券期貨業) | financials | P0 | ✓ | ✓ | ✓ |
| `/opendata/t187ap06_L_ci` | 上市公司綜合損益表(一般業) | financials | P0 | ✓ | ✓ | ✓ |
| `/opendata/t187ap06_L_fh` | 上市公司綜合損益表(金控業) | financials | P0 | ✓ | ✓ | ✓ |
| `/opendata/t187ap06_L_ins` | 上市公司綜合損益表(保險業) | financials | P0 | ✓ | ✓ | ✓ |
| `/opendata/t187ap06_L_mim` | 上市公司綜合損益表(異業) | financials | P0 | ✓ | ✓ | ✓ |
| `/opendata/t187ap07_L_bd` | 上市公司資產負債表(證券期貨業) | financials | P0 | ✓ | ✓ | ✓ |
| `/opendata/t187ap07_L_ci` | 上市公司資產負債表(一般業) | financials | P0 | ✓ | ✓ | ✓ |
| `/opendata/t187ap07_L_fh` | 上市公司資產負債表(金控業) | financials | P0 | ✓ | ✓ | ✓ |
| `/opendata/t187ap07_L_ins` | 上市公司資產負債表(保險業) | financials | P0 | ✓ | ✓ | ✓ |
| `/opendata/t187ap07_L_mim` | 上市公司資產負債表(異業) | financials | P0 | ✓ | ✓ | ✓ |
| `/opendata/t187ap07_X_basi` | 公發公司資產負債表-金融業 | financials | skip |  | ✓ | ✓ |
| `/opendata/t187ap07_X_bd` | 公發公司資產負債表-證券期貨業 | financials | skip |  | ✓ | ✓ |
| `/opendata/t187ap07_X_fh` | 公發公司資產負債表-金控業 | financials | skip |  | ✓ | ✓ |
| `/opendata/t187ap07_X_ins` | 公發公司資產負債表-保險業 | financials | skip |  | ✓ | ✓ |
| `/opendata/t187ap11_P` | 公發公司董監事持股餘額明細 | governance | skip |  | △ | ✓ |
| `/opendata/t187ap06_L_basi` | 上市公司綜合損益表(金融業) | financials | P0 | ✓ | ✓ | ✓ |
| `/opendata/t187ap07_L_basi` | 上市公司資產負債表(金融業) | financials | P0 | ✓ | ✓ | ✓ |

### 證券櫃檯買賣中心 OpenAPI（225）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `/tpex_mainborad_highlight` | 上櫃股票市場現況 | market | P2 |  | ✓ | ✓ |
| `/tpex_securities` | 上櫃股票現股當沖交易標的資訊 | chips | P2 |  | ✓ | ✓ |
| `/tpex_spendi_today` | 上櫃當日公布暫停/恢復交易股票 | status | P1 |  | ✓ | ✓ |
| `/tpex_spendi_history` | 上櫃歷史公布暫停/恢復交易股票 | status | P2 |  | ✓ | ✓ |
| `/tpex_mainboard_daily_close_quotes` | 上櫃股票行情 | price | P0 | ✓ | ✓ | ✓ |
| `/tpex_mainboard_quotes` | 上櫃股票收盤行情 | price | P0 | ✓ | ✓ | ✓ |
| `/tpex_mainboard_peratio_analysis` | 上櫃股票個股本益比、殖利率、股價淨值比 | valuation | P0 | ✓ | ✓ | ✓ |
| `/tpex_mainboard_margin_balance` | 上櫃股票融資融券餘額 | chips | P0 | ✓ | ✓ | ✓ |
| `/tpex_index` | 櫃買指數歷史資料 | index | P1 |  | ✓ | ✓ |
| `/tpex50_index` | 富櫃50指數歷史收盤指數 | index | P2 |  | ✓ | ✓ |
| `/tpex_intraday_trading_statistics` | 上櫃股票現股當沖交易統計資訊 | chips | P2 |  | ✓ | ✓ |
| `/tpex_active_broker_volume` | 上櫃股票熱門股證券商進出排行 | chips | P2 |  | ✓ | ✓ |
| `/tpex_margin_sbl` | 上櫃股票融券借券賣出餘額 | chips | P1 |  | ✓ | ✓ |
| `/tpex_exright_daily` | 上櫃股票除權除息計算結果表 | dividends | P1 |  | ✓ | ✓ |
| `/tpex_exright_prepost` | 上櫃股票除權除息預告表 | dividends | P0 | ✓ | ✓ | ✓ |
| `/tpex_cmode` | 上櫃股票變更交易、分盤交易、管理股票與停止交易資訊 | status | P1 |  | ✓ | ✓ |
| `/tpex_odd_stock` | 上櫃股票零股交易資訊 | price | P2 |  | ✓ | ✓ |
| `/tpex_off_market` | 上櫃股票盤後定價行情 | price | skip |  | ✓ | ✓ |
| `/tpex_esb_applicant_companies` | 申請上櫃公司 | events | P2 |  | ✓ | ✓ |
| `/tpex_trading_warning_information` | 上櫃公布注意股票資訊 | status | P0 | ✓ | ✓ | ✓ |
| `/tpex_disposal_information` | 上櫃處置有價證券資訊 | status | P0 | ✓ | ✓ | ✓ |
| `/tpex_trading_warning_note` | 上櫃公布注意累計次數異常資訊 | status | P2 |  | ✓ | ✓ |
| `/tpex_margin_trading_term` | 上櫃融資融券暫停融券賣出預告表 | events | P1 |  | ✓ | ✓ |
| `/tpex_margin_trading_adjust` | 上櫃融資融券調整成數 | chips | P2 |  | ✓ | ✓ |
| `/tpex_margin_trading_lend` | 上櫃融資融券標借 | chips | P2 |  | ✓ | ✓ |
| `/tpex_margin_trading_marginspot` | 上櫃信用交易餘額概況表 | market | P2 |  | ✓ | ✓ |
| `/tpex_margin_trading_margin_mark` | 上櫃平盤下得融(借)券賣出之證券名單 | chips | P2 |  | ✓ | ✓ |
| `/tpex_margin_trading_margin_used` | 上櫃融資融券使用率報表 | chips | P2 |  | ✓ | ✓ |
| `/tpex_margin_trading_short_sell` | 上櫃融資融券增減排行表 | chips | P2 |  | ✓ | ✓ |
| `/tpex_3insti_qfii` | 上櫃僑外資及陸資持股比例排行表 | chips | P0 | ✓ | ✓ | ✓ |
| `/tpex_3insti_qfii_industry` | 上櫃各類股僑外資及陸資持股比例表 | chips | P1 |  | ✓ | ✓ |
| `/tpex_3insti_daily_trading` | 上櫃股票三大法人買賣明細資訊 | chips | P0 | ✓ | ✓ | ✓ |
| `/tpex_3insti_dealer_trading` | 上櫃股票自營商買賣超彙總表 | chips | P2 |  | ✓ | ✓ |
| `/tpex_ceil_non_trading` | 上櫃漲跌停未成交資訊 | market | P2 |  | ✓ | ✓ |
| `/tpex_daily_trading_index` | 上櫃日成交量值指數 | market | P2 |  | ✓ | ✓ |
| `/tpex_short_sell` | 上櫃當日融券賣出與借券賣出成交量值 | chips | P2 |  | ✓ | ✓ |
| `/tpex_daily_broker1` | 上櫃各券商當日營業金額統計表 | reference | skip |  | ✓ | ✓ |
| `/tpex_active_dollar_volume` | 上櫃盤中個股成交金額排行 | market | P2 |  | ✓ | ✓ |
| `/tpex_active_advanced` | 上櫃盤中個股漲幅排行 | market | P2 |  | ✓ | ✓ |
| `/tpex_active_declined` | 上櫃盤中個股跌幅排行 | market | P2 |  | ✓ | ✓ |
| `/tpex_intraday_fee` | 上櫃應付現股當日沖銷券差借券費率 | chips | P2 |  | ✓ | ✓ |
| `/tpex_intraday_trading_pre` | 上櫃暫停先賣後買當日沖銷交易標的預告表 | chips | P2 |  | ✓ | ✓ |
| `/tpex_intraday_trading_his` | 上櫃暫停先賣後買當日沖銷交易歷史查詢 | chips | P2 |  | ✓ | ✓ |
| `/tpex_daily_market_value` | 上櫃歷史個股市值排行 | market | P2 |  | ✓ | ✓ |
| `/tpex_daily_turnover` | 上櫃歷史個股週轉率排行 | market | P2 |  | ✓ | ✓ |
| `/tpex_trading_volumes_avg` | 上櫃歷史個股日均量排行 | market | P2 |  | ✓ | ✓ |
| `/tpex_trading_amount_avg` | 上櫃歷史個股日均值排行 | market | P2 |  | ✓ | ✓ |
| `/tpex_trading_volume_ratio` | 上櫃歷史類股成交價量比重 | market | P2 |  | ✓ | ✓ |
| `/tpex_pe_ratio_top10` | 上櫃歷史個股本益比排行 | valuation | skip |  | ✓ | ✓ |
| `/tpex_daily_qutoes_block` | 上櫃鉅額交易日成交資訊 | market | P2 |  | ✓ | ✓ |
| `/tpex_daily_trading_block` | 上櫃個股單一證券鉅額交易日成交資訊 | market | P2 |  | ✓ | ✓ |
| `/tpex_daily_trading_summary_odd` | 上櫃鉅額交易日成交量值統計 | market | P2 |  | ✓ | ✓ |
| `/tpex_monthly_trading_summary_block` | 上櫃鉅額交易月成交量值統計 | market | P2 |  | ✓ | ✓ |
| `/tpex_yearly_trading_summary_block` | 上櫃鉅額交易年成交量值統計 | market | skip |  | ✓ | ✓ |
| `/tpex_volume_rank` | 上櫃歷史個股成交量排行 | market | P2 |  | ✓ | ✓ |
| `/tpex_amount_rank` | 上櫃歷史個股成交值排行 | market | P2 |  | ✓ | ✓ |
| `/tpex_prvol` | 上櫃股票等價系統成交分價表 | market | P2 |  | ✓ | ✓ |
| `/tpex_3insti_summary` | 上櫃股票三大法人買賣金額彙總表 | chips | P1 |  | ✓ | ✓ |
| `/tpex_3insti_trading` | 上櫃股票投信買賣超彙總表 | chips | P2 |  | ✓ | ✓ |
| `/tpex_daily_trade_block_day` | 鉅額交易歷史成交資訊 | market | P2 |  | ✓ | ✓ |
| `/tpex_delayed_stock_open` | 上櫃每日暫緩開盤股票 | status | P2 |  | ✓ | ✓ |
| `/tpex_delayed_stock_close` | 上櫃每日暫緩收盤股票 | status | P2 |  | ✓ | ✓ |
| `/tpex_ipo_no_limit` | 上櫃首五日無漲跌幅資訊 | status | P2 |  | ✓ | ✓ |
| `/tpex_esb_eps_rank` | 本國興櫃公司EPS排名 | financials | skip |  | ✓ | ✓ |
| `/tpex_esb_capitals_rank` | 興櫃公司資本額排名 | financials | skip |  | ✓ | ✓ |
| `/tpex200_change` | 櫃買「富櫃200指數」當日收盤指數 | index | P2 |  | ✓ | ✓ |
| `/tpcgi_constituents` | 上櫃公司治理指數當日成分股資訊 | index | P2 |  | ✓ | ✓ |
| `/tpcgi_reward_index` | 上櫃公司治理指數歷史收盤指數 | index | P2 |  | ✓ | ✓ |
| `/tpcgi_change` | 上櫃公司治理指數當日收盤指數 | index | P2 |  | ✓ | ✓ |
| `/tpex_index_consti` | 櫃買指數成分股 | index | P2 |  | ✓ | ✓ |
| `/tpex_reward_index` | 櫃買指數與報酬指數之收市指數 | index | P1 |  | ✓ | ✓ |
| `/tpex50_constituents` | 櫃買「富櫃50指數」當日成分股 | index | P2 |  | ✓ | ✓ |
| `/tpex50_change` | 櫃買「富櫃50指數」當日收盤指數 | index | P2 |  | ✓ | ✓ |
| `/tphd_constituents` | 櫃買「高殖利率指數」當日成分股 | index | P2 |  | ✓ | ✓ |
| `/tphd_change` | 櫃買「高殖利率指數」當日收盤指數 | index | P2 |  | ✓ | ✓ |
| `/tpci_constituents` | 櫃買「薪酬指數」當日成分股 | index | P2 |  | ✓ | ✓ |
| `/tpci_change` | 櫃買「薪酬指數」當日收盤指數 | index | P2 |  | ✓ | ✓ |
| `/tpci_reward_index` | 櫃買「薪酬指數」歷史收盤指數 | index | P2 |  | ✓ | ✓ |
| `/tpex_emp88_constituents` | 櫃買「勞工就業88指數」當日成分股 | index | P2 |  | ✓ | ✓ |
| `/tpex_emp88_change` | 櫃買「勞工就業88指數」當日收盤指數 | index | P2 |  | ✓ | ✓ |
| `/tpex_emp88_reward_index` | 櫃買「勞工就業88指數」歷史收盤指數 | index | P2 |  | ✓ | ✓ |
| `/tpex_dpsp_monthly_CBmcs007` | 可轉債資產交換ASO及ASW銀行承作餘額 | bonds | skip |  | ✓ | ✓ |
| `/tpex_international_bond_quotes` | 國際債券當日盤中報價行情表(含寶島債) | bonds | skip |  | ✓ | ✓ |
| `/tpex_international_bond_trade` | 國際債券當日盤中成交行情表(含寶島債) | bonds | skip |  | ✓ | ✓ |
| `/tpex_international_bond_issue_investor` | 國際債券(一般投資人) | bonds | skip |  | ✓ | ✓ |
| `/tpex_international_bond_issue_org` | 國際債券(僅售予專業投資人者) | bonds | skip |  | ✓ | ✓ |
| `/t187ap46_O_21` | 上櫃公司企業ESG資訊揭露彙總資料-職業安全衛生 | esg | P2 |  | ✓ | ✓ |
| `/t187ap46_O_9` | 上櫃公司企業ESG資訊揭露彙總資料-功能性委員會 | esg | P2 |  | ✓ | ✓ |
| `/t187ap46_O_8` | 上櫃公司企業ESG資訊揭露彙總資料-氣候相關議題管理 | esg | P2 |  | ✓ | ✓ |
| `/tpex_esb_disposal_information` | 興櫃處置有價證券資訊 | status | P2 |  | ✓ | ✓ |
| `/tpex_esb_warning_information` | 興櫃公布注意有價證券資訊 | status | P2 |  | ✓ | ✓ |
| `/tpex_esb_recommended_dealer` | 興櫃推薦證券商與推薦之股票 | reference | skip |  | ✓ | ✓ |
| `/tpex_warrant_gold` | 黃金現貨權證發行基本資料 | reference | skip |  | ✓ | ✓ |
| `/tpex_warrant_gold_quts` | 黃金現貨權證收盤行情 | reference | skip |  | ✓ | ✓ |
| `/tpex_warrant_daily_quts` | 上櫃權證收盤行情日報表 | warrants | P2 |  | ✓ | ✓ |
| `/tpex_warrant_monthly_quts` | 上櫃權證收盤行情月報表 | warrants | skip |  | ✓ | ✓ |
| `/tpex_warrant_issue` | 上櫃權證發行基本資料 | warrants | P2 |  | ✓ | ✓ |
| `/tpex_warrant_wcb_daily_quts` | 上櫃牛熊證收盤行情(不含展延型牛熊證)日報表 | warrants | skip |  | ✓ | ✓ |
| `/tpex_warrant_wcb_monthly_quts` | 上櫃牛熊證收盤行情(不含展延型牛熊證)月報表 | warrants | skip |  | ✓ | ✓ |
| `/tpex_warrant_wcb_issue` | 上櫃牛熊證發行基本資料(不含展延型牛熊證) | warrants | P2 |  | ✓ | ✓ |
| `/tpex_warrant_wxy_daily_quts` | 上櫃展延型牛熊證收盤行情日報表 | warrants | P2 |  | ✓ | ✓ |
| `/tpex_warrant_wxy_monthly_quts` | 上櫃展延型牛熊證收盤行情月報表 | warrants | skip |  | ✓ | ✓ |
| `/tpex_warrant_wxy_issue` | 上櫃展延型牛熊證發行基本資料 | warrants | P2 |  | ✓ | ✓ |
| `/tpex_warrant_quts` | 單筆權證成交資料 | warrants | skip |  | ✓ | ✓ |
| `/tpex_warrant_statistics` | 每日權證交易人數(上櫃) | warrants | skip |  | ✓ | ✓ |
| `/tpex_warrant` | 上櫃股票權證資訊 | warrants | skip |  | ✓ | ✓ |
| `/tpex_warrant_suspend_today` | 上櫃權證當日暫停/恢復交易資訊 | warrants | skip |  | ✓ | ✓ |
| `/tpex_warrant_suspend_history` | 上櫃權證歷史暫停/恢復交易資訊 | warrants | skip |  | ✓ | ✓ |
| `/tpex_opfund_latest` | 開放式基金當日行情表 | funds | skip |  | ✓ | ✓ |
| `/tpex_opfund_recommended_dealer` | 開放式基金受益憑證造市商與造市之基金 | reference | skip |  | ✓ | ✓ |
| `/tpex_opfund_market_highlight` | 開放式基金市場現況 | funds | skip |  | ✓ | ✓ |
| `/tpex_gold_market_highlight` | 黃金現貨市場現況 | reference | skip |  | ✓ | ✓ |
| `/tpex_gold_recommended_dealer` | 造市商與造市之黃金現貨 | reference | skip |  | ✓ | ✓ |
| `/tpex_gold_latest` | 黃金現貨當日行情表 | reference | skip |  | ✓ | ✓ |
| `/tpex_gisa_highlight` | 創櫃板公司市場現況 | reference | skip |  | ✓ | ✓ |
| `/tpex_gisa_company` | 創櫃板公司資訊 | reference | skip |  | ✓ | ✓ |
| `/tpex_gisa_financing_before` | 於登錄創櫃板前辦理籌資資訊 | reference | skip |  | ✓ | ✓ |
| `/t187ap46_O_20` | 上櫃公司企業ESG資訊揭露彙總資料-反競爭行為法律訴訟 | esg | P2 |  | ✓ | ✓ |
| `/t187ap46_O_19` | 上櫃公司企業ESG資訊揭露彙總資料-風險管理政策 | esg | P2 |  | ✓ | ✓ |
| `/t187ap46_O_15` | 上櫃公司企業ESG資訊揭露彙總資料-社區關係 | esg | P2 |  | ✓ | ✓ |
| `/t187ap46_O_13` | 上櫃公司企業ESG資訊揭露彙總資料-供應鏈管理 | esg | P2 |  | ✓ | ✓ |
| `/t187ap46_O_12` | 上櫃公司企業ESG資訊揭露彙總資料-食品安全 | esg | P2 |  | ✓ | ✓ |
| `/t187ap46_O_14` | 上櫃公司企業ESG資訊揭露彙總資料-產品品質與安全 | esg | P2 |  | ✓ | ✓ |
| `/tpex200_constituents` | 櫃買「富櫃200指數」當日成分股 | index | P2 |  | ✓ | ✓ |
| `/t187ap41_O` | 上櫃公司召開股東常 (臨時) 會日期、地點及採用電子投票情形等資料彙總表 | events | P0 | ✓ | ✓ | ✓ |
| `/t187ap05_R` | 興櫃公司每月營業收入彙總表 | financials | P2 |  | ✓ | ✓ |
| `/t187ap46_O_4` | 上櫃公司企業ESG資訊揭露彙總資料-廢棄物管理 | esg | P2 |  | ✓ | ✓ |
| `/t187ap46_O_2` | 上櫃公司企業ESG資訊揭露彙總資料-能源管理 | esg | P2 |  | ✓ | ✓ |
| `/t187ap46_O_7` | 上櫃公司企業ESG資訊揭露彙總資料-投資人溝通 | esg | P2 |  | ✓ | ✓ |
| `/t187ap46_O_1` | 上櫃公司企業ESG資訊揭露彙總資料-溫室氣體排放 | esg | P2 |  | ✓ | ✓ |
| `/t187ap46_O_6` | 上櫃公司企業ESG資訊揭露彙總資料-董事會 | esg | P2 |  | ✓ | ✓ |
| `/t187ap46_O_5` | 上櫃公司企業ESG資訊揭露彙總資料-人力發展 | esg | P2 |  | ✓ | ✓ |
| `/t187ap46_O_3` | 上櫃公司企業ESG資訊揭露彙總資料-水資源管理 | esg | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap05_OA` | 二十九大類股營收變化統計表 | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap05_OB` | 發行公司營收創新高一覽表(上櫃) | financials | P2 |  | ✓ | ✓ |
| `/BDdos216UTF` | 美元固定利率不可贖回國際債券理論價格 | bonds | skip |  | ✓ | ✓ |
| `/BDdos215UTF` | 美元附息固定利率可贖回國際債券理論價格 | bonds | skip |  | ✓ | ✓ |
| `/BDdos209UTF` | 美元零息可贖回國際債券理論價格 | bonds | skip |  | ✓ | ✓ |
| `/tpex_gisa_financing_history` | 創櫃板公司透過籌資系統辦理籌資資訊 | reference | skip |  | ✓ | ✓ |
| `/mopsfin_t187ap35_O` | 上櫃公司股東行使提案權情形彙總表 | governance | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap37_O` | 上櫃權證基本資料彙總表 | warrants | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap42_O` | 上櫃認購(售)權證每日成交資料檔 | warrants | skip |  | ✓ | ✓ |
| `/mopsfin_t187ap32_O` | 上櫃公司公司治理之相關規程規則 | governance | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap34_O` | 上櫃公司採累積投票制、全額連記法、候選人提名制選任董監事及當選資料彙總表 | governance | P2 |  | △ | ✓ |
| `/mopsfin_t187ap33_O` | 上櫃公司董事長是否兼任總經理 | governance | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap31_O` | 上櫃公司財務報告經監察人承認情形 | financials | skip |  | ✓ | ✓ |
| `/mopsfin_t187ap09_O` | 上櫃公司董事、監察人質權設定占董事及監察人實際持有股數彙總表 | governance | P1 |  | △ | ✓ |
| `/mopsfin_t187ap10_O` | 上櫃公司董事、監察人持股不足法定成數連續達3個月以上彙總表 | governance | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap24_O` | 上櫃公司經營權及營業範圍異(變)動專區-經營權異動公司 | governance | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap25_O` | 上櫃公司經營權及營業範圍異(變)動專區-營業範圍重大變更公司 | governance | P2 |  | ✓ | ✓ |
| `/tpex_gisa_financing_in_process` | 創櫃板辦理中籌資資訊 | reference | skip |  | ✓ | ✓ |
| `/mopsfin_t187ap03_O` | 上櫃股票基本資料 | profile | P0 |  | ✓ | ✓ |
| `/tpex_3insti_qfii_trading` | 上櫃股票外資及陸資買賣超彙總表 | chips | P2 |  | ✓ | ✓ |
| `/tpex_esb_latest_statistics` | 興櫃股票當日行情表 | price | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap36_O` | 上櫃認購(售)權證年度發行量概況統計表 | warrants | skip |  | ✓ | ✓ |
| `/mopsfin_t187ap03_R` | 興櫃公司基本資料 | profile | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap04_O` | 上櫃公司每日重大訊息 | events | P0 | ✓ | ✓ | ✓ |
| `/mopsfin_t187ap01` | 券商業務別人員數 | reference | skip |  | ✓ | ✓ |
| `/mopsfin_t187ap02_O` | 上櫃公司持股逾 10% 大股東名單 | governance | P1 |  | △ | ✓ |
| `/mopsfin_t187ap26_O` | 上櫃公司經營權及營業範圍異(變)動專區-經營權異動且營業範圍重大變更停止買賣公司 | governance | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap27_O` | 上櫃公司經營權及營業範圍異(變)動專區-經營權異動且營業範圍重大變更列為變更交易公司 | governance | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap05_O` | 上櫃公司每月營業收入彙總表 | financials | P0 | ✓ | ✓ | ✓ |
| `/mopsfin_t187ap39_O` | 上櫃股利分派情形-董事會通過 | dividends | skip |  | ✓ | ✓ |
| `/bond_cb_daily` | 轉(交)換公司債買賣斷券商買賣日報表 | bonds | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap07_O_basi` | 上櫃公司資產負債表(金融業) | financials | P0 | ✓ | ✓ | ✓ |
| `/mopsfin_t187ap07_O_bd` | 上櫃公司資產負債表(證券期貨業) | financials | P0 | ✓ | ✓ | ✓ |
| `/mopsfin_t187ap07_O_ci` | 上櫃公司資產負債表(一般業) | financials | P0 | ✓ | ✓ | ✓ |
| `/mopsfin_t187ap07_O_fh` | 上櫃公司資產負債表(金控業) | financials | P0 | ✓ | ✓ | ✓ |
| `/mopsfin_t187ap07_O_ins` | 上櫃公司資產負債表(保險業) | financials | P0 | ✓ | ✓ | ✓ |
| `/mopsfin_t187ap07_O_mim` | 上櫃公司資產負債表(異業) | financials | P0 | ✓ | ✓ | ✓ |
| `/mopsfin_t187ap06_O_basi` | 上櫃公司綜合損益表(金融業) | financials | P0 | ✓ | ✓ | ✓ |
| `/mopsfin_t187ap06_O_bd` | 上櫃公司綜合損益表(證券期貨業) | financials | P0 | ✓ | ✓ | ✓ |
| `/mopsfin_t187ap06_O_ci` | 上櫃公司綜合損益表(一般業) | financials | P0 | ✓ | ✓ | ✓ |
| `/mopsfin_t187ap06_O_fh` | 上櫃公司綜合損益表(金控業) | financials | P0 | ✓ | ✓ | ✓ |
| `/mopsfin_t187ap06_O_ins` | 上櫃公司綜合損益表(保險業) | financials | P0 | ✓ | ✓ | ✓ |
| `/mopsfin_t187ap06_O_mim` | 上櫃公司綜合損益表(異業) | financials | P0 | ✓ | ✓ | ✓ |
| `/mopsfin_t187ap06_O_basiA` | 上櫃公司財報資訊(金融業) | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap06_O_bdA` | 上櫃公司財報資訊(證券期貨業) | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap06_O_ciA` | 上櫃公司財報資訊( 一般業) | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap06_O_fhA` | 上櫃公司財報資訊(金控業) | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap06_O_insA` | 上櫃公司財報資訊(保險業) | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap06_O_mimA` | 上櫃公司財報資訊(異業) | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap07_U_bd` | 興櫃公司資產負債表-證券期貨業 | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap07_U_ci` | 興櫃公司資產負債表-一般業 | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap07_U_fh` | 興櫃公司資產負債表-金控業 | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap07_U_ins` | 興櫃公司資產負債表-保險業 | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap07_U_mim` | 興櫃公司資產負債表-異業 | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap06_U_basi` | 興櫃公司綜合損益表-金融業 | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap06_U_bd` | 興櫃公司綜合損益表-證券期貨業 | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap06_U_ci` | 興櫃公司綜合損益表-一般業 | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap06_U_fh` | 興櫃公司綜合損益表-金控業 | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap06_U_ins` | 興櫃公司綜合損益表-保險業 | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap06_U_mim` | 興櫃公司綜合損益表-異業 | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap07_U_basi` | 興櫃公司資產負債表-金融業 | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap11_R` | 興櫃公司董監事持股餘額明細資料 | governance | P2 |  | △ | ✓ |
| `/mopsfin_t187ap14_O` | 上櫃公司各產業EPS統計資訊 | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap15_O` | 上櫃公司截至各季綜合損益財測達成情形(簡式) | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap16_O` | 上櫃公司當季綜合損益經會計師查核(核閱)數與當季預測數差異達百分之十以上者，或截至當季累計差異達百分之二十以上者(簡式) | financials | P2 |  | ✓ | ✓ |
| `/mopsfin_187ap17_O` | 上櫃公司營益分析查詢彙總表(全體公司彙總報表) | financials | P0 | ✓ | ✓ | ✓ |
| `/mopsfin_t187ap08_O` | 上櫃公司董事、監察人持股不足法定成數彙總表 | governance | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap11_O` | 上櫃公司董監事持股餘額明細資料 | governance | P1 |  | △ | ✓ |
| `/mopsfin_t187ap12_O` | 上櫃公司每日內部人持股轉讓事前申報表-持股轉讓日報表 | events | P1 |  | △ | ✓ |
| `/mopsfin_t187ap13_O` | 上櫃公司每日內部人持股轉讓事前申報表-持股未轉讓日報表 | events | P2 |  | △ | ✓ |
| `/mopsfin_t187ap22_O` | 上櫃公司金管會證券期貨局裁罰案件專區 | governance | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap30_O` | 上櫃公司獨立董監事兼任情形彙總表 | governance | P2 |  | △ | ✓ |
| `/mopsfin_t187ap29_A_O` | 上櫃公司董事酬金相關資訊 | governance | P2 |  | △ | ✓ |
| `/mopsfin_t187ap29_B_O` | 上櫃公司監察人酬金相關資訊 | governance | P2 |  | △ | ✓ |
| `/mopsfin_t187ap29_C_O` | 上櫃公司合併報表董事酬金相關資訊 | governance | P2 |  | △ | ✓ |
| `/mopsfin_t187ap29_D_O` | 上櫃公司合併報表監察人酬金相關資訊 | governance | P2 |  | △ | ✓ |
| `/mopsfin_t187ap23_O` | 上櫃公司違反資訊申報、重大訊息及說明記者會規定專區 | governance | P2 |  | ✓ | ✓ |
| `/mopsfin_t187ap19_O` | 電子式交易統計資訊(上櫃) | market | skip |  | ✓ | ✓ |
| `/tpex_esb_highlight` | 興櫃股票市場現況 | market | skip |  | ✓ | ✓ |
| `/bond_ISSBD1_data` | 公債發行資料下載 | bonds | skip |  | ✓ | ✓ |
| `/bond_ISSBD2_data` | 外國金融債發行資料下載 | bonds | skip |  | ✓ | ✓ |
| `/bond_ISSBD3_data` | 金融債發行資料下載 | bonds | skip |  | ✓ | ✓ |
| `/bond_ISSBD4_data` | 普通債發行資料下載 | bonds | skip |  | ✓ | ✓ |
| `/bond_ISSBD5_data` | 轉(交)換債發行資料下載 | bonds | P2 |  | ✓ | ✓ |
| `/bond_ISSBD6_data` | 海外轉換債發行資料下載 | bonds | skip |  | ✓ | ✓ |
| `/bond_ISSBD7_data` | 附認股權公司債發行資料下載 | bonds | skip |  | ✓ | ✓ |
| `/bond_ISSBD8_data` | 海外附認股權公司債發行資料下載 | bonds | skip |  | ✓ | ✓ |
| `/bond_ISSBD9_data` | 海外普通債發行資料下載 | bonds | skip |  | ✓ | ✓ |
| `/bond_ISSBD10_data` | 國際債券(寶島債券)-本國發行人及第一、二上市(櫃)公司之外國發行人發行資料下載 | bonds | skip |  | ✓ | ✓ |
| `/bond_ISSBD11_data` | 國際債券(寶島債券)-外國發行人(在我國未公開發行股權商品者)發行資料下載 | bonds | skip |  | ✓ | ✓ |
| `/tpex_daily_broker2` | 上櫃股票各券商總公司當日營業金額統計表 | reference | skip |  | ✓ | ✓ |
| `/tphd_index` | 高殖利率指數歷史收盤指數 | index | P2 |  | ✓ | ✓ |

### 臺灣期貨交易所 OpenAPI（135）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `/CCP_CMLists` | 店頭集中結算會員名冊 | reference | skip |  | △ | ✓ |
| `/productsExemptedAH` | 盤後交易時段指定豁免及非豁免代為沖銷商品 | futures | skip |  | △ | ✓ |
| `/SSFAdjustedInfo` | 股票期貨/選擇權調整型契約資訊內容 | futures | P2 |  | △ | ✓ |
| `/SSFRefferedOpeningPriceAh` | 股票期貨調整開盤參考價(盤後交易時段) | futures | skip |  | △ | ✓ |
| `/SSFRefferedOpeningPrice` | 股票期貨/選擇權調整開盤參考價 | futures | P2 |  | △ | ✓ |
| `/ContractAdj` | 股票期貨/選擇權契約調整一覽事項 | futures | P2 |  | △ | ✓ |
| `/DailyMarketReportFut` | 期貨每日交易行情 | futures | P0 |  | △ | ✓ |
| `/DailyMarketReportOpt` | 選擇權每日交易行情 | options | P0 |  | △ | ✓ |
| `/DailyOptionsDelta` | 選擇權每日Delta值 | options | P2 |  | ✓ | ✓ |
| `/PutCallRatio` | 臺指選擇權Put/Call比 | options | P0 |  | ✓ | ✓ |
| `/BlockTradeContinuousMatchingSingleOrder` | 鉅額交易逐筆撮合之單式委託成交 | market | skip |  | △ | ✓ |
| `/BlockTradeContinuousMatchingCombinationOrder` | 鉅額交易逐筆撮合之組合式委託成交 | market | skip |  | △ | ✓ |
| `/BlockTradeNegotiation` | 鉅額交易議價申報成交 | futures | skip |  | ✓ | ✓ |
| `/BlockTrade` | 鉅額交易各商品成交資訊 | futures | skip |  | △ | ✓ |
| `/MarketDataOfMajorInstitutionalTradersGeneralBytheDate` | 三大法人-總表-依日期 | futures | P0 |  | ✓ | ✓ |
| `/MarketDataOfMajorInstitutionalTradersGeneralBytheWeek` | 三大法人-總表-依週別 | futures | P2 |  | ✓ | ✓ |
| `/MarketDataOfMajorInstitutionalTradersDividedByFuturesAndOptionsBytheDate` | 三大法人-區分期貨與選擇權二類-依日期 | futures | P0 |  | ✓ | ✓ |
| `/MarketDataOfMajorInstitutionalTradersDividedByFuturesAndOptionsBytheWeek` | 三大法人-區分期貨與選擇權二類-依週別 | futures | P2 |  | ✓ | ✓ |
| `/MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate` | 三大法人-區分各期貨契約-依日期 | futures | P0 |  | ✓ | ✓ |
| `/MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheWeek` | 三大法人-區分各期貨契約-依週別 | futures | P2 |  | ✓ | ✓ |
| `/MarketDataOfMajorInstitutionalTradersDetailsOfOptionsContractsBytheDate` | 三大法人-區分各選擇權契約-依日期 | options | P0 |  | ✓ | ✓ |
| `/MarketDataOfMajorInstitutionalTradersDetailsOfOptionsContractsBytheWeek` | 三大法人-區分各選擇權契約-依週別 | options | P2 |  | ✓ | ✓ |
| `/MarketDataOfMajorInstitutionalTradersDetailsOfCallsAndPutsBytheDate` | 三大法人-選擇權買賣權分計-依日期 | options | P0 |  | ✓ | ✓ |
| `/MarketDataOfMajorInstitutionalTradersDetailsOfCallsAndPutsBytheWeek` | 三大法人-選擇權買賣權分計-依週別 | options | P2 |  | ✓ | ✓ |
| `/OpenInterestOfLargeTradersFutures` | 期貨大額交易人未沖銷部位資料 | futures | P0 |  | ✓ | ✓ |
| `/OpenInterestOfLargeTradersOptions` | 選擇權大額交易人未沖銷部位資料 | options | P0 |  | △ | ✓ |
| `/DailyForeignExchangeRates` | 每日外幣參考匯率 | fx | P0 |  | △ | ✓ |
| `/TotalMarketPositionLimitForSingleStockFuturesAndEquityOptions` | 個股類全市場部位限制 | futures | skip |  | △ | ✓ |
| `/SingleStockFuturesContractReferredOpeningPrice` | 股票期貨契約調整開盤參考價 | futures | skip |  | △ | ✓ |
| `/FuturesAndOptionsFeeSchedule` | 期交所期貨暨選擇權商品相關費用表 | futures | P2 |  | △ | ✓ |
| `/FinalSettlementPrice` | 最後結算價 | futures | P1 |  | △ | ✓ |
| `/SettledPositionsOfContractsOnExpirationDate` | 到期契約履約交割 | futures | skip |  | △ | ✓ |
| `/IndexFuturesAndOptionsMargining` | 保證金一覽表-股價指數類 | futures | P1 |  | △ | ✓ |
| `/InterestRateFuturesMargining` | 保證金一覽表-利率類 | futures | skip |  | △ | ✓ |
| `/GoldFuturesAndOptionsMargining` | 保證金一覽表-商品類 | futures | skip |  | △ | ✓ |
| `/SingleStockFuturesMargining` | 保證金一覽表-股票類 | futures | P1 |  | △ | ✓ |
| `/SingleStockFuturesETFMargining` | 保證金一覽表-股票類(ETF) | futures | P1 |  | △ | ✓ |
| `/AcceptableCollateralGovernmentBonds` | 有價證券保證金之可抵繳標的-公債 | bonds | skip |  | △ | ✓ |
| `/AcceptableCollateralInternationalBonds` | 有價證券保證金之可抵繳標的-國際債 | bonds | skip |  | △ | ✓ |
| `/AcceptableCollateralStock` | 有價證券保證金之可抵繳標的-股票(含ETF) | futures | skip |  | △ | ✓ |
| `/NetValuePerShareStatement` | 期貨商每股淨值明細表 | reference | skip |  | △ | ✓ |
| `/AccumulatedIncomeStatementBeforeTaxStatement` | 期貨商稅前累計損益明細表 | reference | skip |  | △ | ✓ |
| `/Daily_FUT` | 期貨商交易量日報表－期貨 | reference | skip |  | △ | ✓ |
| `/Weekly_FUT` | 期貨商交易量週報表－期貨 | reference | skip |  | △ | ✓ |
| `/Monthly_FUT` | 期貨商交易量月報表－期貨 | reference | skip |  | △ | ✓ |
| `/Yearly_FUT` | 期貨商交易量年報表－期貨 | reference | skip |  | △ | ✓ |
| `/Daily_OPT` | 期貨商交易量日報表－選擇權 | reference | skip |  | △ | ✓ |
| `/Weekly_OPT` | 期貨商交易量週報表－選擇權 | reference | skip |  | △ | ✓ |
| `/Monthly_OPT` | 期貨商交易量月報表－選擇權 | reference | skip |  | △ | ✓ |
| `/Yearly_OPT` | 期貨商交易量年報表－選擇權 | reference | skip |  | △ | ✓ |
| `/CustodianBankLists` | 保管銀行名冊 | reference | skip |  | △ | ✓ |
| `/CMLists` | 結算會員名冊 | reference | skip |  | △ | ✓ |
| `/ClearingBankLists` | 結算銀行名冊 | reference | skip |  | △ | ✓ |
| `/FCMLists` | 期貨商總公司名冊 | reference | skip |  | △ | ✓ |
| `/FCMBranchLists` | 期貨商分公司名冊 | reference | skip |  | △ | ✓ |
| `/Daily_OPT_W` | 期貨商交易量週到期選擇權日報表 | reference | skip |  | △ | ✓ |
| `/PositionLimitNonEquity` | 交易人部位限制-非個股類 | futures | skip |  | △ | ✓ |
| `/PositionLimitEquity` | 交易人部位限制-個股類 | futures | skip |  | △ | ✓ |
| `/TimeAndSalesData` | 每日期貨每筆成交資料 | futures | skip |  | △ | ✓ |
| `/DailyVolumeReportOnCalendarSpreadOrders` | 每日期貨價差委託成交概況表 | futures | skip |  | ✓ | ✓ |
| `/TimeAndSalesDataOnCalendarSpreadOrders` | 每日期貨價差每筆成交資料 | futures | skip |  | ✓ | ✓ |
| `/OptionsTimeAndSalesData` | 每日選擇權每筆成交資料 | options | skip |  | △ | ✓ |
| `/MarketMakerListsFut` | 期貨商品造市者清單 | reference | skip |  | △ | ✓ |
| `/MarketMakerListsOpt` | 選擇權商品造市者清單 | reference | skip |  | △ | ✓ |
| `/AnnualTradingVolume` | 各商品年成交量統計表 | futures | skip |  | △ | ✓ |
| `/SSFLists` | 股票期貨交易標的 | futures | P1 |  | △ | ✓ |
| `/SSOLists` | 股票選擇權交易標的 | options | P1 |  | △ | ✓ |
| `/BTContinuousMatchingSingleOrderFutures` | 鉅額交易逐筆撮合之單式委託成交-期貨商品 | market | skip |  | △ | ✓ |
| `/BTContinuousMatchingSingleOrderOptions` | 鉅額交易逐筆撮合之單式委託成交-選擇權商品 | market | skip |  | △ | ✓ |
| `/BTDailyTradeInformationFutures` | 鉅額交易各商品成交資訊-期貨商品 | market | skip |  | ✓ | ✓ |
| `/BTDailyTradeInformationOptions` | 鉅額交易各商品成交資訊-選擇權商品 | market | skip |  | ✓ | ✓ |
| `/DailySummaryOfBlockTradeFutures` | 鉅額交易成交量統計-期貨商品 | market | skip |  | ✓ | ✓ |
| `/DailySummaryOfBlockTradeOptions` | 鉅額交易成交量統計-選擇權商品 | market | skip |  | ✓ | ✓ |
| `/FinalSettlementPriceFutures` | 最後結算價-期貨商品 | futures | P2 |  | △ | ✓ |
| `/FinalSettlementPriceOptions` | 最後結算價-選擇權商品 | options | P2 |  | △ | ✓ |
| `/SettledPositionsFutures` | 到期契約履約交割-期貨商品 | futures | skip |  | △ | ✓ |
| `/SettledPositionsOptions` | 到期契約履約交割-選擇權商品 | futures | skip |  | △ | ✓ |
| `/NetValuePerShareS` | 兼營期貨商每股淨值明細表 | reference | skip |  | △ | ✓ |
| `/NetValuePerShareF` | 專營期貨商每股淨值明細表 | reference | skip |  | △ | ✓ |
| `/NetValuePerShareR` | 複委託期貨商每股淨值明細表 | reference | skip |  | △ | ✓ |
| `/AccumulatedIncomeStateS` | 兼營期貨商稅前累計損益明細表 | reference | skip |  | △ | ✓ |
| `/AccumulatedIncomeStateF` | 專營期貨商稅前累計損益明細表 | reference | skip |  | △ | ✓ |
| `/AccumulatedIncomeStateR` | 複委託期貨商稅前累計損益明細表 | reference | skip |  | △ | ✓ |
| `/NetIncomeRankingS` | 兼營期貨商稅前損益排序表 | reference | skip |  | △ | ✓ |
| `/NetIncomeRankingF` | 專營期貨商稅前損益排序表 | reference | skip |  | △ | ✓ |
| `/NetIncomeRankingR` | 複委託期貨商稅前損益排序表 | reference | skip |  | △ | ✓ |
| `/IncomeStatementS` | 兼營期貨商稅前累計損益彙總表 | reference | skip |  | △ | ✓ |
| `/IncomeStatementF` | 專營期貨商稅前累計損益彙總表 | reference | skip |  | △ | ✓ |
| `/IncomeStatementR` | 複委託期貨商稅前累計損益彙總表 | reference | skip |  | △ | ✓ |
| `/EPSBeforeTaxS` | 兼營期貨商每股稅前盈餘統計表 | reference | skip |  | △ | ✓ |
| `/EPSBeforeTaxF` | 專營期貨商每股稅前盈餘統計表 | reference | skip |  | △ | ✓ |
| `/EPSBeforeTaxR` | 複委託期貨商每股稅前盈餘統計表 | reference | skip |  | △ | ✓ |
| `/MarketParticipants` | 市場參與者統計 | futures | P2 |  | △ | ✓ |
| `/MonthlyTradingStatisticsFutures` | 期貨各類交易人各商品交易量統計表 | futures | P2 |  | △ | ✓ |
| `/MonthlyTradingStatisticsOptions` | 選擇權各類交易人各商品交易量統計表 | options | P2 |  | △ | ✓ |
| `/FinalSettlementPriceSSF` | 最後結算價-股票期貨 | futures | P2 |  | △ | ✓ |
| `/FinalSettlementPriceSSO` | 最後結算價-股票選擇權 | options | P2 |  | △ | ✓ |
| `/FinalSettlementPriceIndexFutures` | 最後結算價-股價指數類（指數期貨） | futures | P2 |  | △ | ✓ |
| `/FinalSettlementPriceIndexOptions` | 最後結算價-股價指數類（指數選擇權） | options | P2 |  | ✓ | ✓ |
| `/FinalSettlementPriceIR` | 最後結算價-利率類 | futures | skip |  | ✓ | ✓ |
| `/FinalSettlementPriceGold` | 最後結算價-商品類 | futures | skip |  | △ | ✓ |
| `/FinalSettlementPriceFx` | 最後結算價-匯率類 | futures | skip |  | △ | ✓ |
| `/SettledPositionsIndexFutures` | 到期契約履約交割-股價指數類（指數期貨） | futures | skip |  | △ | ✓ |
| `/SettledPositionsIndexOptions` | 到期契約履約交割-股價指數類（指數選擇權） | futures | skip |  | △ | ✓ |
| `/SettledPositionsSSF` | 到期契約履約交割-股票類（股票期貨） | futures | skip |  | △ | ✓ |
| `/SettledPositionsSSO` | 到期契約履約交割-股票類（股票選擇權） | futures | skip |  | △ | ✓ |
| `/SettledPositionsIR` | 到期契約履約交割-利率類 | futures | skip |  | △ | ✓ |
| `/SettledPositionsGold` | 到期契約履約交割-商品類 | futures | skip |  | △ | ✓ |
| `/SettledPositionsFX` | 到期契約履約交割-匯率類 | futures | skip |  | ✓ | ✓ |
| `/AnnualTradingIndexFutures` | 商品年成交量統計-股價指數類（指數期貨） | futures | skip |  | △ | ✓ |
| `/AnnualTradingIndexOptions` | 商品年成交量統計-股價指數類（指數選擇權） | futures | skip |  | ✓ | ✓ |
| `/AnnualTradingSSF` | 商品年成交量統計-股票類（股票期貨） | futures | skip |  | △ | ✓ |
| `/AnnualTradingSSO` | 商品年成交量統計-股票類（股票選擇權） | futures | skip |  | △ | ✓ |
| `/AnnualTradingIR` | 商品年成交量統計-利率類 | futures | skip |  | △ | ✓ |
| `/AnnualTradingGold` | 商品年成交量統計-商品類 | futures | skip |  | △ | ✓ |
| `/eTradeQty` | 每月市場電子式交易下單統計（網路與DMA下單） | futures | skip |  | ✓ | ✓ |
| `/STFTop10` | 每日股票期貨交易量前十大統計表 | futures | P2 |  | ✓ | ✓ |
| `/AnnualTradingFX` | 商品年成交量統計-匯率類 | futures | skip |  | △ | ✓ |
| `/SettledPositionsFXFutures` | 到期契約履約交割-匯率期貨類 | futures | skip |  | △ | ✓ |
| `/FXFuturesAndOptionsMargining` | 保證金一覽表-匯率類 | futures | skip |  | △ | ✓ |
| `/AcceptableCollateralLogStock` | 有價證券保證金之可抵繳標的增刪紀錄 | futures | skip |  | △ | ✓ |
| `/va01` | 每日股價指數類選擇權未平倉量增減 | options | P2 |  | △ | ✓ |
| `/va02` | 每日個股選擇權未平倉量增減(區分股票與ETF) | options | P2 |  | ✓ | ✓ |
| `/va03` | 每日商品類選擇權未平倉量增減 | options | skip |  | △ | ✓ |
| `/va04` | 股價指數類期貨商品每月平均成交金額 | futures | skip |  | △ | ✓ |
| `/va05` | 個股期貨商品每月平均成交金額(區分股票與ETF) | futures | skip |  | △ | ✓ |
| `/va06` | 利率期貨商品每月平均成交金額 | futures | skip |  | ✓ | ✓ |
| `/va07` | 股價指數類選擇權商品每月平均成交金額(權利金) | futures | skip |  | △ | ✓ |
| `/va08` | 個股選擇權商品每月平均成交金額(權利金-區分股票與ETF) | futures | skip |  | △ | ✓ |
| `/va09` | 商品類期貨每月平均成交金額 | futures | skip |  | △ | ✓ |
| `/va10` | 商品類選擇權每月平均成交金額(權利金) | futures | skip |  | △ | ✓ |
| `/va11` | 匯率類期貨每月平均成交金額 | futures | skip |  | △ | ✓ |
| `/va12` | 每日個股期貨交易量統計表（區分股票與ETF） | futures | P2 |  | △ | ✓ |
| `/va13` | 每月個股期貨交易量統計表（區分股票與ETF） | futures | skip |  | △ | ✓ |
| `/va14` | 每年個股期貨交易量統計表（區分股票與ETF） | futures | skip |  | △ | ✓ |

### 臺灣集中保管結算所 開放資料（103）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `id=1-1` | 證券基本資料（證券代號、市場別、股務單位、證券狀態、面額）〔標題依欄位推定〕 | profile | P2 |  | △ | ✓ |
| `id=1-2` | 股務代理機構資料〔標題依欄位推定〕 | reference | skip |  | ✓ | ✓ |
| `id=1-3` | 固定收益證券（債券）發行資料〔標題依欄位推定〕 | bonds | skip |  | △ | ✓ |
| `id=1-4` | 強制集保股數（新上市櫃）〔標題依欄位推定〕 | chips | P2 |  | △ | ✓ |
| `id=1-5` | 集保戶股權分散表 | chips | P0 | ✓ | ✓ | ✓ |
| `id=1-6` | 債券持有人結構（月）〔標題依欄位推定〕 | bonds | skip |  | △ | ✓ |
| `id=1-7` | 集中保管交付明細（初次上市櫃、減資、有償認股等）〔標題依欄位推定〕 | events | P2 |  | △ | ✓ |
| `id=1-9` | 無實體登錄數額－股票〔標題依欄位推定〕 | reference | skip |  | △ | ✓ |
| `id=1-10` | 無實體登錄數額－特別股〔標題依欄位推定〕 | reference | skip |  | △ | ✓ |
| `id=1-11` | 無實體登錄數額－公司債〔標題依欄位推定〕 | bonds | skip |  | △ | ✓ |
| `id=1-12` | 無實體登錄數額－轉換公司債〔標題依欄位推定〕 | bonds | skip |  | △ | ✓ |
| `id=1-13` | 轉（交）換公司債轉換價格〔標題依欄位推定〕 | bonds | P2 |  | △ | ✓ |
| `id=1-14` | 收購（公開收購）資訊〔標題依欄位推定〕 | events | P2 |  | △ | ✓ |
| `id=1-15` | 無實體登錄數額－特別股（含類型）〔標題依欄位推定〕 | reference | skip |  | △ | ✓ |
| `id=1-16` | 有價證券登錄數額（全市場）〔標題依欄位推定〕 | reference | skip |  | △ | ✓ |
| `id=2-1` | 證券開戶數統計〔標題依欄位推定〕 | macro | P2 |  | △ | ✓ |
| `id=2-2` | 集保業務統計－收存/付出〔標題依欄位推定〕 | reference | skip |  | △ | ✓ |
| `id=2-3` | 集中保管證券保管統計表〔標題依欄位推定〕 | reference | skip |  | △ | ✓ |
| `id=2-4` | 證券市場成交量統計（上市、上櫃、興櫃、債券）〔標題依欄位推定〕 | market | P2 |  | △ | ✓ |
| `id=2-5` | 股務代理（股東會）業務統計〔標題依欄位推定〕 | reference | skip |  | △ | ✓ |
| `id=2-6` | 集中保管有價證券帳簿劃撥設質交付統計表 | chips | P2 |  | ✓ | ✓ |
| `id=2-7` | 基金申購、買回、轉換統計（基金資訊平台）〔標題依欄位推定〕 | funds | skip |  | △ | ✓ |
| `id=2-8` | 有價證券集中保管個別股票異動月分析表－可轉換公司債〔標題依欄位推定〕 | bonds | P2 |  | △ | ✓ |
| `id=2-9` | 有價證券集中保管個別股票異動月分析表－認購售權證〔標題依欄位推定〕 | warrants | skip |  | △ | ✓ |
| `id=2-10` | 短期票券集保統計（初級、次級市場）〔標題依欄位推定〕 | rates | skip |  | △ | ✓ |
| `id=2-11` | 票券公司各天期買賣報價（日內）〔標題依欄位推定〕 | rates | skip |  | △ | ✓ |
| `id=2-12` | 票券次級市場各天期加權平均利率〔標題依欄位推定〕 | rates | skip |  | △ | ✓ |
| `id=2-13` | 票券買賣斷與附條件交易加權平均利率〔標題依欄位推定〕 | rates | skip |  | △ | ✓ |
| `id=2-14` | 國庫券成交利率〔標題依欄位推定〕 | rates | skip |  | △ | ✓ |
| `id=2-15` | 票券公司報價利率（上午）〔標題依欄位推定〕 | rates | skip |  | △ | ✓ |
| `id=2-16` | 票券公司買賣報價利率（上午）〔標題依欄位推定〕 | rates | skip |  | △ | ✓ |
| `id=2-17` | 票券公司報價利率（11:00）〔標題依欄位推定〕 | rates | skip |  | △ | ✓ |
| `id=2-18` | 票券公司買賣報價利率（11:00）〔標題依欄位推定〕 | rates | skip |  | △ | ✓ |
| `id=2-19` | 短期票券利率指標（近一個月，10–365 天期）〔標題依欄位推定，可能是 TAIBIR〕 | rates | P2 |  | △ | ✓ |
| `id=2-20` | 短期票券利率指標（另一組，近一個月）〔標題依欄位推定〕 | rates | P2 |  | △ | ✓ |
| `id=2-21` | 短期票券利率指標歷史（2009 年起，10–180 天期）〔標題依欄位推定〕 | rates | P2 |  | △ | ✓ |
| `id=2-22` | 有價證券集中保管個別股票異動月分析表－上市證券 | etf | P1 |  | ✓ | ✓ |
| `id=2-23` | 有價證券集中保管個別股票異動月分析表－上櫃證券 | etf | P1 |  | ✓ | ✓ |
| `id=2-24` | 有價證券集中保管個別股票異動月分析表－興櫃證券 | chips | P2 |  | △ | ✓ |
| `id=2-25` | 上市櫃檯合併保管有價證券週餘額表 | etf | P2 |  | ✓ | ✓ |
| `id=3-1` | 境外基金總代理人資料〔標題依欄位推定〕 | funds | skip |  | △ | ✓ |
| `id=3-2` | 境外基金基本資料（含規模）〔標題依欄位推定〕 | funds | P2 |  | △ | ✓ |
| `id=3-3` | 投信投顧事業名錄〔標題依欄位推定〕 | reference | skip |  | △ | ✓ |
| `id=3-4` | 境外基金每日淨值〔標題依欄位推定〕 | funds | P2 |  | △ | ✓ |
| `id=3-5` | 境外基金配息資料〔標題依欄位推定〕 | funds | P2 |  | △ | ✓ |
| `id=3-6` | 境外基金非營業日〔標題依欄位推定〕 | funds | skip |  | △ | ✓ |
| `id=3-7` | 境外基金銷售機構〔標題依欄位推定〕 | reference | skip |  | △ | ✓ |
| `id=3-8` | 境外基金國內投資人持有統計（依受益人形態等）〔標題依欄位推定〕 | funds | skip |  | △ | ✓ |
| `id=3-9` | 境外基金申購買回統計－依計價幣別〔標題依欄位推定〕 | funds | skip |  | △ | ✓ |
| `id=3-10` | 境外基金申購買回統計－依基金類別〔標題依欄位推定〕 | funds | skip |  | △ | ✓ |
| `id=3-11` | 境外基金申購買回統計－依投資區域〔標題依欄位推定〕 | funds | skip |  | △ | ✓ |
| `id=3-12` | 境外基金銷售機構與代理基金數〔標題依欄位推定〕 | reference | skip |  | △ | ✓ |
| `id=3-13` | 基金收付銀行名單〔標題依欄位推定〕 | reference | skip |  | △ | ✓ |
| `id=3-14` | 基金平台金融機構名單〔標題依欄位推定〕 | reference | skip |  | △ | ✓ |
| `id=3-15` | 境外基金反稀釋條款與公開說明書網址〔標題依欄位推定〕 | funds | skip |  | △ | ✓ |
| `id=3-16` | 境外基金淨值與規模排行（一）〔標題依欄位推定〕 | funds | skip |  | △ | ✓ |
| `id=3-17` | 境外基金淨值與規模排行（二）〔標題依欄位推定〕 | funds | skip |  | △ | ✓ |
| `id=3-18` | 境外基金淨值與規模排行（三）〔標題依欄位推定〕 | funds | skip |  | △ | ✓ |
| `id=3-19` | 境外基金淨值與規模排行（四）〔標題依欄位推定〕 | funds | skip |  | △ | ✓ |
| `id=3-20` | 境外基金淨值與規模排行（五）〔標題依欄位推定〕 | funds | skip |  | △ | ✓ |
| `id=3-21` | 境外基金淨值與規模排行（六）〔標題依欄位推定〕 | funds | skip |  | △ | ✓ |
| `id=3-22` | 境外基金淨值與規模排行（七）〔標題依欄位推定〕 | funds | skip |  | △ | ✓ |
| `id=3-23` | 境外基金公平價格調整機制〔標題依欄位推定〕 | funds | skip |  | △ | ✓ |
| `id=3-25` | 境外基金最新淨值總額〔標題依欄位推定〕 | funds | skip |  | △ | ✓ |
| `id=4-1` | 境外結構型商品發行機構〔標題依欄位推定〕 | reference | skip |  | △ | ✓ |
| `id=4-2` | 境外結構型商品基本資料 | reference | skip |  | △ | ✓ |
| `id=4-3` | 境外結構型商品受託/銷售機構名錄 | reference | skip |  | △ | ✓ |
| `id=4-4` | 境外結構型商品受託/銷售對照 | reference | skip |  | △ | ✓ |
| `id=4-5` | 境外結構型商品參考價格 | reference | skip |  | ✓ | ✓ |
| `id=4-6` | 境外結構型商品配息資訊 | reference | skip |  | ✓ | ✓ |
| `id=4-7` | 境外結構型商品公告訊息 | reference | skip |  | △ | ✓ |
| `id=4-8` | 境外結構型商品基本資料（專業投資人）〔推定〕 | reference | skip |  | △ | ✓ |
| `id=4-9` | 境外結構型商品參考價格（專業投資人）〔推定〕 | reference | skip |  | △ | ✓ |
| `id=4-10` | 境外結構型商品配息（專業投資人）〔推定〕 | reference | skip |  | △ | ✓ |
| `id=4-11` | 境外結構型商品月統計（一）〔推定〕 | reference | skip |  | △ | ✓ |
| `id=4-12` | 集保開放資料 4-12〔標題未知，欄位：年月、商品數、金額(百萬台幣)…〕 | reference | skip |  | △ | ✓ |
| `id=4-13` | 集保開放資料 4-13〔標題未知，欄位：年月、商品數、金額(百萬台幣)…〕 | reference | skip |  | △ | ✓ |
| `id=4-14` | 集保開放資料 4-14〔標題未知，欄位：年月、商品數、金額(百萬台幣)…〕 | reference | skip |  | △ | ✓ |
| `id=4-15` | 集保開放資料 4-15〔標題未知，欄位：年月、商品數、金額(百萬台幣)…〕 | reference | skip |  | △ | ✓ |
| `id=4-16` | 集保開放資料 4-16〔標題未知，欄位：年月、商品數、金額(百萬台幣)…〕 | reference | skip |  | △ | ✓ |
| `id=4-17` | 集保開放資料 4-17〔標題未知，欄位：年月、商品數、金額(百萬台幣)…〕 | reference | skip |  | △ | ✓ |
| `id=5-1` | 期貨信託基金基本資料（簡）〔推定〕 | funds | skip |  | △ | ✓ |
| `id=5-2` | 期貨信託基金基本資料〔推定〕 | funds | skip |  | △ | ✓ |
| `id=5-3` | 期貨信託基金銷售機構〔推定〕 | reference | skip |  | △ | ✓ |
| `id=5-4` | 期貨信託基金淨值 | funds | skip |  | △ | ✓ |
| `id=5-5` | 期貨信託基金投資區域比例〔推定〕 | funds | skip |  | △ | ✓ |
| `id=5-6` | 期貨信託事業已成立基金數〔推定〕 | reference | skip |  | △ | ✓ |
| `id=5-7` | 期貨信託基金公告訊息〔推定〕 | funds | skip |  | △ | ✓ |
| `id=5-8` | 期貨信託契約〔推定〕 | funds | skip |  | △ | ✓ |
| `id=5-9` | 期貨信託基金非營業日〔推定〕 | funds | skip |  | △ | ✓ |
| `id=5-10` | 期貨信託事業基金數（含日期）〔推定〕 | reference | skip |  | △ | ✓ |
| `id=5-11` | 期貨信託基金規模與淨值〔推定〕 | funds | skip |  | △ | ✓ |
| `id=5-12` | 期貨信託基金申購金額與人數〔推定〕 | funds | skip |  | △ | ✓ |
| `id=5-13` | 期貨信託基金投資標的〔推定〕 | funds | skip |  | △ | ✓ |
| `id=5-14` | 期貨信託基金最新淨值〔推定〕 | funds | skip |  | △ | ✓ |
| `id=5-15` | 期貨信託事業名錄〔推定〕 | reference | skip |  | △ | ✓ |
| `id=5-16` | 期貨信託基金數量與規模歷史（2008 起）〔推定〕 | funds | skip |  | △ | ✓ |
| `id=6-1` | 股東會電子投票日程（歷年）〔標題依欄位推定〕 | events | P2 |  | △ | ✓ |
| `id=6-2` | 股東會電子投票日程（今年）〔標題依欄位推定〕 | events | P2 |  | △ | ✓ |
| `id=6-3` | 股東會電子投票出席比例〔標題依欄位推定〕 | governance | skip |  | △ | ✓ |
| `id=6-4` | 股東會電子投票權數結構〔標題依欄位推定〕 | governance | skip |  | △ | ✓ |
| `id=6-5` | 股東會召開方式（實體/視訊）〔標題依欄位推定〕 | events | P2 |  | △ | ✓ |
| `id=7-1` | 集保戶股權分散表（與 1-5 內容相同） | chips | skip |  | △ | ✓ |

### 臺灣集中保管結算所 OpenAPI（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://openapi.tdcc.com.tw/tdcc-opendata-api-docs` | 集保開放資料 OAS API 說明文件（Swagger UI：/swagger-ui/index.html?configUrl=/tdcc-opendata-api-docs/swagger-config） | reference | P1 |  | △ | — |

### 中央銀行（外匯局）（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://data.gov.tw/dataset/7232` | 銀行間市場新臺幣對美元收盤匯率（`cpx.cbc.gov.tw/api/OpenData/FTDOpenData_Day`） | fx | P1 | ✓（2026-11-12） | ✓ | ✓ |

### 中央銀行（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://cpx.cbc.gov.tw/Data/ExportToAPIInfo` | 中央銀行統計資料庫 API | macro | P2 |  | △ | — |

### 臺灣銀行（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://rate.bot.com.tw/xrt?Lang=zh-TW` | 牌告匯率（網站 CSV） | fx | skip |  | △ | — |

### 金融監督管理委員會證券期貨局（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://data.gov.tw/dataset/11109` | 證券投資信託基金每日淨值 | etf | P1 |  | ✓ | — |

### 金融監督管理委員會證券期貨局（資料來源：投信投顧公會）（2）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://data.gov.tw/dataset/43476` | 投信投顧公會境內基金基本資料集 | funds | P2 |  | ✓ | — |
| `https://data.gov.tw/dataset/21404` | 投信投顧公會境內基金 ISIN Code、短線交易限制天數、基金月報網址 | funds | P2 |  | ✓ | — |

### 金融監督管理委員會（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://stat.fsc.gov.tw/api/swagger/openapi.json` | 金管會統計資料平台 OpenAPI | macro | P2 |  | △ | — |

### 國家發展委員會（2）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://data.gov.tw/dataset/6099` | 景氣指標及燈號 | macro | P1 |  | ✓ | — |
| `https://data.gov.tw/dataset/31564` | 臺灣景氣指標月刊 | macro | P2 |  | ✓ | — |

### 行政院主計總處（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://nstatdb.dgbas.gov.tw/` | 總體統計資料庫（CPI、GDP、經濟成長率） | macro | P2 |  | △ | — |

### 財政部關務署（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://data.gov.tw/dataset/6053` | 海關進出口貿易統計 | macro | P2 |  | ✓ | — |

### 經濟部統計處（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://data.gov.tw/` | 外銷訂單統計 | macro | P2 |  | △ | — |

### 臺灣證券交易所（2）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://dsp.twse.com.tw/` | ETF 申贖資訊及即時淨值揭露專區（介接格式） | etf | skip |  | ✗ | — |
| `https://www.twse.com.tw/XBRL/about` | XBRL 財報（IFRSs）下載與分類標準 | financials | skip |  | ✗ | — |

### 公開資訊觀測站（臺灣證券交易所營運）（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://mops.twse.com.tw/` | MOPS 網站：財報全表、XBRL、電子書、重大訊息歷史、法說會、彙總報表下載 | financials | skip |  | ✗ | — |

### U.S. SEC EDGAR（5）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://data.sec.gov/submissions/CIK##########.json` | 公司申報清單（submissions） | us | P1 |  | ✓ | — |
| `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` | XBRL company facts（財報數字） | us | P1 |  | ✓ | — |
| `https://data.sec.gov/api/xbrl/companyconcept/CIK##########/us-gaap/<Concept>.json` | XBRL company concept | us | P2 |  | ✓ | — |
| `https://data.sec.gov/api/xbrl/frames/us-gaap/<Concept>/USD/CY2025Q3I.json` | XBRL frames（跨公司同期） | us | P2 |  | ✓ | — |
| `https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip` | bulk 壓縮檔（submissions.zip、companyfacts.zip） | us | P2 |  | ✓ | — |

### U.S. SEC（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://www.sec.gov/files/company_tickers.json` | Ticker ↔ CIK 對照 | us | P1 |  | ✓ | — |

### Nasdaq Trader（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt` | Symbol Directory（nasdaqlisted.txt、otherlisted.txt） | us | P2 |  | △ | — |

### Federal Reserve Bank of St. Louis（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://api.stlouisfed.org/fred/series/observations` | FRED API | macro | skip |  | ✗ | — |

### U.S. Treasury（Fiscal Service）（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/rates_of_exchange` | Treasury Reporting Rates of Exchange 與其他財政資料 API | macro | P2 |  | ✓ | — |

### U.S. Treasury（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://home.treasury.gov/resource-center/data-chart-center/interest-rates` | Daily Treasury Par Yield Curve Rates | rates | P2 |  | △ | — |

### IEX Exchange（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://iextrading.com/trading/market-data/#hist` | IEX HIST（T+1 歷史 TOPS/DEEP） | us | skip |  | △ | — |

### HKEX 香港交易所（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://www.hkex.com.hk/Global/Exchange/Terms-of-Use` | HKEX 網站資料與市場數據 | foreign | skip |  | ✗ | — |

### JPX 日本交易所（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://jpx-jquants.com/en/termsofservice` | J-Quants API（免費方案）與上場銘柄一覽 | foreign | skip |  | ✗ | — |

### KRX 韓國交易所（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://openapi.krx.co.kr/` | KRX OPEN API | foreign | skip |  | ✗ | — |

### SGX 新加坡交易所（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://www.datadirect.sgx.com/Market-Data-Policy` | SGX 市場數據 | foreign | skip |  | ✗ | — |

### 上海／深圳證券交易所（1）

| 端點／資料集 | 標題 | 用途 | 優先 | 已用 | 商用 | 回應 |
|---|---|---|---|---|---|---|
| `https://www.sse.com.cn/` | 上交所、深交所行情與公告 | foreign | skip |  | ✗ | — |

「商用」欄：✓＝可商用（須顯名）、△＝有條件（授權未個別確認或含個資）、✗＝不可商用。
