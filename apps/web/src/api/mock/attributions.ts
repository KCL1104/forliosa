/**
 * `GET /meta/attributions` 的示範版：資料集清單取自後端 2026-11-12 的實際回應（apps/api/src/forliosa/datapolicy.py）。
 * 顯名聲明格式依政府資料開放授權條款第 1 版：「提供機關〈資料集名稱〉（年份），依政府資料開放授權條款第 1 版」。
 */
import type { AttributionDataset, Attributions } from "../types"

const OGDL = "政府資料開放授權條款第 1 版"
const OGDL_URL = "https://data.gov.tw/license"
const YEAR = 2026

type Row = [key: string, agency: string, dataset: string, url: string, usedFor: string]

const ROWS: Row[] = [
  ["twse-openapi/price", "臺灣證券交易所", "上市個股日成交資訊", "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", "收盤價、日線、成交量"],
  ["twse-openapi/valuation", "臺灣證券交易所", "上市個股日本益比、殖利率及股價淨值比", "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL", "本益比、殖利率、股價淨值比"],
  ["twse-openapi/reference", "臺灣證券交易所", "上市個股股價升降幅度", "https://openapi.twse.com.tw/v1/exchangeReport/TWT84U", "參考價、漲跌停"],
  ["twse-openapi/margin", "臺灣證券交易所", "集中市場融資融券餘額", "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN", "融資融券"],
  ["twse-openapi/ex_dividend", "臺灣證券交易所", "上市股票除權除息預告表", "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL", "除權息日、股利"],
  ["twse-openapi/attention", "臺灣證券交易所", "集中市場當日公布注意股票", "https://openapi.twse.com.tw/v1/announcement/notice", "注意股票"],
  ["twse-openapi/disposition", "臺灣證券交易所", "集中市場公布處置股票", "https://openapi.twse.com.tw/v1/announcement/punish", "處置股票"],
  ["twse-openapi/material_info", "臺灣證券交易所", "上市公司每日重大訊息", "https://openapi.twse.com.tw/v1/opendata/t187ap04_L", "重大訊息、公告、財報與法說會日期"],
  ["twse-openapi/shareholder_meeting", "臺灣證券交易所", "上市公司召開股東常（臨時）會日期、地點及採用電子投票情形等資料彙總表", "https://openapi.twse.com.tw/v1/opendata/t187ap41_L", "股東會"],
  ["twse-openapi/revenue", "臺灣證券交易所", "上市公司每月營業收入彙總表", "https://openapi.twse.com.tw/v1/opendata/t187ap05_L", "月營收公布日"],
  ["twse-openapi/income", "臺灣證券交易所", "上市公司綜合損益表", "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci", "季報損益"],
  ["twse-openapi/balance", "臺灣證券交易所", "上市公司資產負債表", "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci", "季報資產負債"],
  ["twse-openapi/margins", "臺灣證券交易所", "上市公司營益分析查詢彙總表", "https://openapi.twse.com.tw/v1/opendata/t187ap17_L", "利潤率"],
  ["twse-openapi/calendar", "臺灣證券交易所", "有價證券集中交易市場開（休）市日期", "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule", "交易日、定期定額扣款日順延"],
  ["twse-openapi/news", "臺灣證券交易所", "證交所新聞", "https://openapi.twse.com.tw/v1/news/newsList", "公告"],
  ["twse-openapi/fund", "臺灣證券交易所", "基金基本資料彙總表", "https://openapi.twse.com.tw/v1/opendata/t187ap47_L", "ETF 基本資料"],
  ["tpex-openapi/price", "證券櫃檯買賣中心", "上櫃股票行情", "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes", "收盤價、日線、成交量"],
  ["tpex-openapi/valuation", "證券櫃檯買賣中心", "上櫃股票個股本益比、殖利率、股價淨值比", "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis", "本益比、殖利率、股價淨值比"],
  ["tpex-openapi/reference", "證券櫃檯買賣中心", "上櫃股票行情", "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes", "參考價、漲跌停（次一交易日）"],
  ["tpex-openapi/margin", "證券櫃檯買賣中心", "上櫃股票融資融券餘額", "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance", "融資融券"],
  ["tpex-openapi/institutional", "證券櫃檯買賣中心", "上櫃股票三大法人買賣明細資訊", "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading", "三大法人買賣超"],
  ["tpex-openapi/foreign_holding", "證券櫃檯買賣中心", "上櫃僑外資及陸資持股比例排行表", "https://www.tpex.org.tw/openapi/v1/tpex_3insti_qfii", "外資持股比率"],
  ["tpex-openapi/ex_dividend", "證券櫃檯買賣中心", "上櫃股票除權除息預告表", "https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost", "除權息日、股利"],
  ["tpex-openapi/attention", "證券櫃檯買賣中心", "上櫃公布注意股票資訊", "https://www.tpex.org.tw/openapi/v1/tpex_trading_warning_information", "注意股票"],
  ["tpex-openapi/disposition", "證券櫃檯買賣中心", "上櫃處置有價證券資訊", "https://www.tpex.org.tw/openapi/v1/tpex_disposal_information", "處置股票"],
  ["tpex-openapi/material_info", "證券櫃檯買賣中心", "上櫃公司每日重大訊息", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O", "重大訊息、公告、財報與法說會日期"],
  ["tpex-openapi/shareholder_meeting", "證券櫃檯買賣中心", "上櫃公司召開股東常（臨時）會日期、地點及採用電子投票情形等資料彙總表", "https://www.tpex.org.tw/openapi/v1/t187ap41_O", "股東會"],
  ["tpex-openapi/revenue", "證券櫃檯買賣中心", "上櫃公司每月營業收入彙總表", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O", "月營收公布日"],
  ["tpex-openapi/income", "證券櫃檯買賣中心", "上櫃公司綜合損益表", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci", "季報損益"],
  ["tpex-openapi/balance", "證券櫃檯買賣中心", "上櫃公司資產負債表", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap07_O_ci", "季報資產負債"],
  ["tpex-openapi/margins", "證券櫃檯買賣中心", "上櫃公司營益分析查詢彙總表", "https://www.tpex.org.tw/openapi/v1/mopsfin_187ap17_O", "利潤率"],
  ["tdcc-opendata/distribution", "臺灣集中保管結算所", "集保戶股權分散表", "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5", "大戶持股分級"],
  ["cbc-opendata/fx", "中央銀行", "銀行間新臺幣對美元收盤匯率", "https://cpx.cbc.gov.tw/api/OpenData/FTDOpenData_Day", "美股換算新台幣"],
  ["shioaji-data/official", "永豐金證券 shioaji-data（彙整臺灣證券交易所、證券櫃檯買賣中心、公開資訊觀測站開放資料）", "公司基本資料、每日收盤與市值、月營收、季報", "https://github.com/Sinotrade/shioaji-data", "商品主檔、月營收、季報、市值"],
]

export function attributionOf(agency: string, dataset: string, year = YEAR): string {
  return `${agency}〈${dataset}〉（${year}），依${OGDL}`
}

/** 依資料集 key（例如 `twse-openapi/price`）取得顯名聲明，給各端點的 `sources` 用 */
export function sourceOf(key: string): string {
  if (key.startsWith("sec-edgar/")) return secSourceOf(key)
  const row = ROWS.find((r) => r[0] === key)
  return row ? attributionOf(row[1], row[2]) : key
}

/** SEC EDGAR：美國政府公開資料（「sec.gov 的政府內容與 EDGAR 公開申報可自由存取與再利用」），顯名結尾不同 */
const SEC = "美國證券交易委員會（SEC）"
const SEC_LICENSE = "SEC 網站政策：sec.gov 的政府內容與 EDGAR 公開申報可自由存取與再利用"
const SEC_LICENSE_URL = "https://www.sec.gov/about/webmaster-frequently-asked-questions"
const SEC_ROWS: Row[] = [
  ["sec-edgar/companyfacts", SEC, "EDGAR XBRL 財報數據（companyfacts）", "https://data.sec.gov/api/xbrl/companyfacts/", "美股季報、年報：營收、淨利、稀釋 EPS、資產負債、現金流量"],
  ["sec-edgar/submissions", SEC, "EDGAR 公司申報清單（submissions）", "https://data.sec.gov/submissions/", "美股事件：8-K、10-Q、10-K 申報（附 sec.gov 原文連結）"],
  ["sec-edgar/tickers", SEC, "公司代號與 CIK 對照表（company_tickers.json）", "https://www.sec.gov/files/company_tickers.json", "美股代號對應 SEC 公司編號（CIK）"],
]

export function secSourceOf(key: string, year = YEAR): string {
  const row = SEC_ROWS.find((r) => r[0] === key)
  return row ? `${row[1]}〈${row[2]}〉（${year}），美國政府公開資料` : key
}

export function buildAttributions(policy: "commercial" | "personal"): Attributions {
  const datasets: AttributionDataset[] = ROWS.map(([key, agency, dataset, url, used_for]) => ({
    key, agency, dataset, url, used_for, year: YEAR, license: OGDL, license_url: OGDL_URL, commercial: true,
    attribution: attributionOf(agency, dataset),
  }))
  for (const [key, agency, dataset, url, used_for] of SEC_ROWS) {
    datasets.push({ key, agency, dataset, url, used_for, year: YEAR, license: SEC_LICENSE, license_url: SEC_LICENSE_URL, commercial: true, attribution: secSourceOf(key) })
  }
  if (policy === "personal") {
    datasets.push({
      key: "finmind", agency: "FinMind", dataset: "FinMind 開放 API（台股資料）", url: "https://finmind.github.io/",
      used_for: "僅在明確設定時：回補、新聞（非商用）", year: YEAR, license: "FinMind 使用條款（非商用）",
      license_url: "https://finmind.github.io/Disclaimer/", commercial: false, attribution: "FinMind（非商用）",
    })
  }
  return {
    policy,
    notice: [
      "此開放資料依政府資料開放授權條款 (Open Government Data License) 進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。",
      `政府資料開放授權條款：${OGDL_URL}`,
      `${SEC}：sec.gov 上的政府內容與 EDGAR 公開申報可自由存取與再利用（${SEC_LICENSE_URL}）`,
    ],
    datasets,
    not_used: [
      "臺灣證券交易所網站（T86 三大法人、MI_QFIIS 外資持股等）與基本市況報導 MIS：網站條款禁止未經同意以程式下載",
      "證券櫃檯買賣中心網站歷史查詢、公開資訊觀測站網站：同上，只使用 OpenAPI 版本",
    ],
  }
}
