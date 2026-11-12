# 期交所 OpenAPI 商用授權詢問（信件草稿）

> 撰寫：2026-11-12。用途：確認 `docs/research/open-data-inventory.md` 標為 **conditional（有條件）** 的期交所 OpenAPI 資料集，
> 能否依《政府資料開放授權條款－第 1 版》（OGDL）在收費 App 中顯示。
> 收件窗口取自期交所 OpenAPI swagger（`https://openapi.taifex.com.tw/swagger.json`）的「聯絡窗口」：`s0160116@taifex.com.tw`。
> 寄出前請補上〔〕內的寄件人資料；收到書面同意後，在部署環境設定 `TAIFEX_CONDITIONAL_CONFIRMED=true`（見下方「收到回覆後」）。
>
> **狀態：產品負責人 2026-11-12 決定先不寄信**（`PRODUCT.md`「初期資料源不付費」）。草稿保留備用；在寄出並取得同意前，
> `TAIFEX_CONDITIONAL_CONFIRMED` 維持預設 `false`，這些資料集只存檔、不顯示。

---

**收件人**：s0160116@taifex.com.tw
**主旨**：OpenAPI 資料集於收費 App 顯示之授權詢問（期貨／選擇權每日交易行情、每日外幣參考匯率等）

臺灣期貨交易所 OpenAPI 承辦人員 您好：

我是 Forliosa 的開發者。Forliosa 是以台股為主的個人投資記帳與資訊 App，目前供本人與少數親友使用，未來可能開放註冊並收取訂閱費。App **不提供下單**、不提供即時或盤中行情，只在畫面上以表格與圖表顯示**盤後**資料，並逐項標示資料來源。

我們目前每個交易日晚間從貴公司 OpenAPI（`https://openapi.taifex.com.tw/v1/`）各取一次資料，請求間隔 2 秒以上，User-Agent 誠實標示，不下載每筆成交資料，也不擷取貴公司網站。

在政府資料開放平臺上，我們找到貴公司以 OGDL 釋出、並指向本 OpenAPI 的資料集（例如三大法人 11592–11601、臺指選擇權 Put/Call 比 11322、大額交易人未沖銷部位 11337／11338），這些我們會依 OGDL 顯名使用。下列資料集則**沒有找到對應的政府資料開放平臺資料集**，想請教是否同樣可依 OGDL 利用：

1. `DailyMarketReportFut`　期貨每日交易行情
2. `DailyMarketReportOpt`　選擇權每日交易行情
3. `DailyForeignExchangeRates`　每日外幣參考匯率（我們想用 USD/NTD 換算使用者美股帳戶的台幣市值）
4. `OpenInterestOfLargeTradersOptions`　選擇權大額交易人未沖銷部位資料（是否已包含在 11337／11338？）
5. 另外也想一併確認：`FinalSettlementPrice`（最後結算價）、`IndexFuturesAndOptionsMargining`、`SingleStockFuturesMargining`、`SingleStockFuturesETFMargining`（保證金一覽表）、`SSFLists`、`SSOLists`（股票期貨／選擇權交易標的）

想請教：

1. 上述資料集是否屬於貴公司已授權政府資料開放平臺、可依《政府資料開放授權條款－第 1 版》利用（含商業利用、長期存檔、加工後顯示）的資料？若不是，App 向註冊使用者顯示這些盤後數字需要哪一種授權與費用？
2. 顯名聲明以「臺灣期貨交易所〈期貨每日交易行情〉（2026），依政府資料開放授權條款第 1 版」並附授權條款連結（https://data.gov.tw/license），是否符合要求？
3. OpenAPI 是否有呼叫頻率上限、資料公布時間或異動通知管道？我們目前於每個交易日 21:40 取一次。
4. `FinalSettlementPrice` 在 2026-11-12 的回應中，最新的最後結算日是 2025-12-05，請問是否已停止更新？若有替代的 OpenAPI 端點，請告知。
5. `DailyForeignExchangeRates` 以 `Accept: application/json` 請求時，有時回傳 CSV（`content-disposition: …csv`），有時回傳 JSON；請問兩種格式是否都會長期提供？

若上述問題應改洽其他窗口，也請不吝告知。謝謝您撥冗回覆。

Forliosa 開發者　〔姓名〕〔Email〕〔電話〕

---

## 收到回覆後

| 回覆 | 要做的事 |
|---|---|
| 書面同意可依 OGDL 商用（全部或部分資料集） | 部署環境設定 `TAIFEX_CONDITIONAL_CONFIRMED=true`；若只同意部分資料集，請改為逐一開放（`datapolicy.DATASETS` 的 `license_status` 改成 `ogdl`，並在 `basis` 記下回覆日期），不要用總開關。把回覆信存檔（例如 `docs/research/`）。 |
| 需要另簽授權或付費 | 維持 `false`（預設）；`/derivatives/overview` 繼續只顯示三大法人、大額交易人（期貨）與 Put/Call 比；USD/TWD 維持固定 31.5 並在績效 `notes` 說明。 |
| 沒有回覆 | 同上，維持 `false`。 |

開關的效果（`DATA_POLICY=commercial` 時）：

- `false`（預設）：上述資料集照常每日存檔，但 API、AI 工具與 `/meta/attributions` 的 `datasets` 都不顯示；`/meta/attributions.conditional` 列出它們與原因。
- `true`：期貨行情（`/derivatives/overview.futures`、`/derivatives/futures/{code}/history`）、選擇權大額交易人、USD/TWD 參考匯率開始顯示，並附顯名聲明。
