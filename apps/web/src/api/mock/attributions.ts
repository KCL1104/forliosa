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
  ["twse-openapi/fund", "臺灣證券交易所", "基金基本資料彙總表", "https://openapi.twse.com.tw/v1/opendata/t187ap47_L", "ETF 基本資料、相關股票（追蹤同一指數、同類型 ETF）"],
  ["twse-openapi/foreign_top20", "臺灣證券交易所", "集中市場外資及陸資持股前20名彙總表", "https://openapi.twse.com.tw/v1/fund/MI_QFIIS_sort_20", "上市股票的外資持股比（只有名列前 20 名的股票）"],
  ["twse-openapi/board", "臺灣證券交易所", "上市公司董事、監察人持股餘額明細資料", "https://openapi.twse.com.tw/v1/opendata/t187ap11_L", "相關股票：關係企業（只用上市櫃公司擔任法人董事或大股東的列，不存個人資料）"],
  ["twse-openapi/esg_products", "臺灣證券交易所", "上市公司企業ESG資訊揭露彙總資料-產品品質與安全", "https://openapi.twse.com.tw/v1/opendata/t187ap46_L_14", "AI 公司簡介的官方資料（依產品類別之產品產量）"],
  ["twse-openapi/company", "臺灣證券交易所", "上市公司基本資料", "https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "已發行股數、市值、產業別、上市日期；「關於」：總部縣市、網站、實收資本額、董事長、總經理、簽證會計師事務所、股務代理"],
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
  ["tpex-openapi/company", "證券櫃檯買賣中心", "上櫃股票基本資料", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", "已發行股數、市值、產業別、上櫃日期；「關於」：總部縣市、網站、實收資本額、董事長、總經理、簽證會計師事務所、股務代理"],
  ["tpex-openapi/tpex50", "證券櫃檯買賣中心", "富櫃五十指數成分股", "https://www.tpex.org.tw/openapi/v1/tpex50_constituents", "相關股票：上櫃股票是否為富櫃五十成分股"],
  ["tpex-openapi/board", "證券櫃檯買賣中心", "上櫃公司董事、監察人持股餘額明細資料", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap11_O", "相關股票：關係企業（只用上市櫃公司擔任法人董事或大股東的列，不存個人資料）"],
  ["tpex-openapi/esg_products", "證券櫃檯買賣中心", "上櫃公司企業ESG資訊揭露彙總資料-產品品質與安全", "https://www.tpex.org.tw/openapi/v1/t187ap46_O_14", "AI 公司簡介的官方資料（依產品類別之產品產量）"],
  ["tdcc-opendata/distribution", "臺灣集中保管結算所", "集保戶股權分散表", "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5", "大戶持股分級"],
  ["tdcc-opendata/holders_twse", "臺灣集中保管結算所", "有價證券集中保管個別股票異動月分析表－上市證券", "https://opendata.tdcc.com.tw/getOD.ashx?id=2-22", "相關股票：ETF 受益人數（集保股東戶數）"],
  ["tdcc-opendata/holders_tpex", "臺灣集中保管結算所", "有價證券集中保管個別股票異動月分析表－上櫃證券", "https://opendata.tdcc.com.tw/getOD.ashx?id=2-23", "相關股票：ETF 受益人數（集保股東戶數）"],
  ["cbc-opendata/fx", "中央銀行", "銀行間新臺幣對美元收盤匯率", "https://cpx.cbc.gov.tw/api/OpenData/FTDOpenData_Day", "美股換算新台幣"],
  ["sfb-opendata/nav", "金融監督管理委員會證券期貨局", "證券投資信託基金每日淨值", "https://www.sitca.org.tw/MemberK0000/F/03/nav.csv", "ETF 淨值、盤後折溢價（同一天的收盤價 ÷ 淨值 − 1）"],
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

/** 新聞報導的來源（後端 datapolicy.py 的 gdelt/doc、yahoo-rss/stock） */
const GDELT_TERMS_URL = "https://www.gdeltproject.org/about.html#termsofuse"
export const GDELT_ATTRIBUTION = `The GDELT Project〈GDELT DOC 2.0 新聞索引〉（${YEAR}），依 GDELT 使用條款引用：https://www.gdeltproject.org/`
export const YAHOO_RSS_ATTRIBUTION = `Yahoo股市〈個股新聞 RSS〉（${YEAR}），保留「Yahoo股市」與原始媒體標示（非商用）`
export const AI_SEARCH_ATTRIBUTION = "AI 網路搜尋補充（只取搜尋結果的標題、媒體、時間與連結）"

/** 「關於」的公司簡介：中文維基百科節錄（CC BY-SA 4.0）；Wikidata（CC0）只用來找條目 */
const WIKIPEDIA_LICENSE = "創用 CC 姓名標示－相同方式分享 4.0 國際（CC BY-SA 4.0）"
export const WIKIPEDIA_LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/deed.zh-hant"
export const WIKIPEDIA_ATTRIBUTION = `維基百科〈中文維基百科條目（開頭節錄）〉（${YEAR}），依 CC BY-SA 4.0 節錄（不改寫）`
const WIKIDATA_ATTRIBUTION = `Wikidata〈Wikidata 項目（股票代號、交易所、條目連結）〉（${YEAR}），CC0 1.0（公眾領域）`

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
  datasets.push({
    key: "gdelt/doc", agency: "The GDELT Project", dataset: "GDELT DOC 2.0 新聞索引", url: "https://api.gdeltproject.org/api/v2/doc/doc",
    used_for: "個股頁「新聞報導」：媒體標題、媒體名稱、時間與原文連結", year: YEAR, license: "GDELT 使用條款（免費、可商用，需引用 GDELT）",
    license_url: GDELT_TERMS_URL, commercial: true, attribution: GDELT_ATTRIBUTION,
  })
  datasets.push({
    key: "wikipedia/zh", agency: "維基百科", dataset: "中文維基百科條目（開頭節錄）", url: "https://zh.wikipedia.org/",
    used_for: "個股頁「關於」公司簡介（節錄、不改寫，附條目連結）", year: YEAR, license: WIKIPEDIA_LICENSE,
    license_url: WIKIPEDIA_LICENSE_URL, commercial: true, attribution: WIKIPEDIA_ATTRIBUTION,
  })
  datasets.push({
    key: "wikidata/entities", agency: "Wikidata", dataset: "Wikidata 項目（股票代號、交易所、條目連結）", url: "https://www.wikidata.org/",
    used_for: "找出公司對應的中文維基百科條目", year: YEAR, license: "CC0 1.0 公眾領域貢獻宣告",
    license_url: "https://creativecommons.org/publicdomain/zero/1.0/deed.zh-hant", commercial: true, attribution: WIKIDATA_ATTRIBUTION,
  })
  if (policy === "personal") {
    datasets.push({
      key: "yahoo-rss/stock", agency: "Yahoo股市", dataset: "個股新聞 RSS", url: "https://tw.stock.yahoo.com/rss-index",
      used_for: "個股頁「新聞報導」（只在 DATA_POLICY=personal）：標題、原始媒體、時間與連結", year: YEAR,
      license: "Yahoo股市 RSS 使用條款（限個人、非商業用途）", license_url: "https://tw.stock.yahoo.com/rss-index", commercial: false,
      attribution: YAHOO_RSS_ATTRIBUTION,
    })
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
      `The GDELT Project：資料集可「unlimited and unrestricted use for any academic, commercial, or governmental use of any kind without fee」，需引用 GDELT 並連到 https://www.gdeltproject.org/（${GDELT_TERMS_URL}）`,
      `維基百科：條目文字依 CC BY-SA 4.0 授權；個股頁「關於」只節錄條目開頭、不改寫，並標示「節錄」、連到原條目與授權條款（${WIKIPEDIA_LICENSE_URL}）`,
    ],
    datasets,
    not_used: [
      "臺灣證券交易所網站（T86 三大法人、MI_QFIIS 外資持股等）與基本市況報導 MIS：網站條款禁止未經同意以程式下載",
      "證券櫃檯買賣中心網站歷史查詢、公開資訊觀測站網站：同上，只使用 OpenAPI 版本",
      "新聞網站本身：不爬取，也不存內文、摘要或圖片；「新聞報導」只存標題、媒體、時間與原文連結",
      ...(policy === "personal" ? [] : ["Yahoo股市 RSS（個股新聞）：條款限個人、非商業使用，只在 DATA_POLICY=personal 使用"]),
    ],
  }
}
