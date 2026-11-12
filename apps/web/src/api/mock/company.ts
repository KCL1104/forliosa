/**
 * 「相關股票」與「關於〈公司〉」的示範資料（後端：services/related.py、services/company.py）。
 * 公司資料取自 2026-11-12 證交所／櫃買〈公司基本資料〉實際回應（董事長、總經理照原文）；
 * 台積電的簡介是當天的中文維基百科條目開頭（CC BY-SA 4.0，原文節錄、不改寫）。
 */
import type { CompanyAbout, CompanyDescription, RelatedCard, RelatedReason, RelatedStocks } from "../types"
import { sourceOf, WIKIPEDIA_ATTRIBUTION, WIKIPEDIA_LICENSE_URL } from "./attributions"
import { findInstrument, INSTRUMENTS, type MockInstrumentSpec } from "./instruments"
import { dailyCandles, MOCK_TODAY } from "./market"

const round = (n: number, d = 4) => Math.round(n * 10 ** d) / 10 ** d

/** 關係企業（董監事持股餘額明細 2026 年 9 月）：`holder` 是 `symbol` 的法人董事或大股東 */
const BOARD_LINKS: { symbol: string; holder: string; roles: "both" | "director" | "major" }[] = [
  { symbol: "3443.TW", holder: "2330.TW", roles: "both" },
  { symbol: "6488.TWO", holder: "5483.TWO", roles: "both" },
  { symbol: "2258.TW", holder: "2317.TW", roles: "both" },
  { symbol: "2328.TW", holder: "2317.TW", roles: "major" },
]
const ROLE_TEXT = { both: "法人董事及大股東", director: "法人董事", major: "大股東" } as const
/** 富櫃五十成分股（櫃買中心 2026-11-12） */
const TPEX50 = new Set(["6488.TWO", "5483.TWO"])
/** ETF：追蹤指數、類型與集保股東戶數（2026 年 10 月） */
const FUNDS: Record<string, { index: string; kind: string; holders: number }> = {
  "0050.TW": { index: "臺灣50指數", kind: "國內股票型", holders: 3_741_557 },
  "006208.TW": { index: "臺灣50指數", kind: "國內股票型", holders: 727_518 },
  "0056.TW": { index: "臺灣高股息指數", kind: "國內股票型", holders: 1_752_954 },
  "00878.TW": { index: "MSCI臺灣ESG永續高股息精選30指數", kind: "國內股票型", holders: 1_711_531 },
  "00919.TW": { index: "臺灣指數公司特選臺灣上市上櫃精選高息指數", kind: "國內股票型", holders: 1_498_736 },
}
const ELECTRONICS = new Set(["半導體業", "電腦及週邊設備業", "光電業", "通信網路業", "電子零組件業", "電子通路業", "資訊服務業", "其他電子業"])

function card(spec: MockInstrumentSpec, reason: RelatedReason, reason_label: string): RelatedCard {
  const candles = dailyCandles(spec).filter((c) => c.t <= MOCK_TODAY).slice(-22)
  const change = spec.prev_close ? (spec.price - spec.prev_close) / spec.prev_close : null
  return {
    symbol: spec.symbol, name: spec.name, reason, reason_label, close: spec.price, change_pct: change === null ? null : round(change),
    as_of: MOCK_TODAY, sparkline: candles.map((c) => ({ t: c.t, price: c.c })), is_index: false, notes: [], is_demo: false,
  }
}

const cap = (s: MockInstrumentSpec) => s.market_cap ?? (s.shares_outstanding ?? 0) * s.price
const distance = (a: number, b: number) => (a > 0 && b > 0 ? Math.abs(Math.log(a) - Math.log(b)) : Infinity)

/** 規則與後端相同：基準／成分股 1 張、關係企業 1 張（雜項產業 2 張）、同業補滿 4 張；ETF 頁用同指數、同類型受益人數多 */
export function buildRelated(spec: MockInstrumentSpec, benchmark: string): RelatedStocks {
  const out: RelatedStocks = { symbol: spec.symbol, items: [], sources: [], notes: [] }
  if (spec.market === "US") return { ...out, notes: ["美股目前沒有可商用的相關股票資料"] }
  const picked: RelatedCard[] = []
  const add = (s: MockInstrumentSpec | undefined, reason: RelatedReason, label: string) => {
    if (!s || s.symbol === spec.symbol || picked.some((p) => p.symbol === s.symbol) || picked.length >= 4) return
    picked.push(card(s, reason, label))
  }
  const sources = new Set<string>()
  if (spec.type === "etf") {
    const me = FUNDS[spec.symbol]
    if (!me) return out
    const others = Object.entries(FUNDS).filter(([s]) => s !== spec.symbol).sort((a, b) => b[1].holders - a[1].holders)
    for (const [s, f] of others) if (f.index === me.index && f.kind === me.kind) add(findInstrument(s), "same_index", "追蹤同一指數")
    for (const [s, f] of others) if (f.kind === me.kind) add(findInstrument(s), "same_type", `同為${f.kind}、受益人數多`)
    sources.add(sourceOf("twse-openapi/fund")).add(sourceOf("tdcc-opendata/holders_twse"))
  } else {
    const misc = spec.industry === "其他電子業" || spec.industry === "其他業"
    if (TPEX50.has(spec.symbol)) {
      add(findInstrument("006201.TWO"), "constituent", "富櫃五十成分股（櫃買中心公布）")
      sources.add(sourceOf("tpex-openapi/tpex50"))
    } else {
      add(findInstrument(benchmark), "benchmark", "你的比較基準")
    }
    const affiliates = BOARD_LINKS.flatMap((l) => {
      if (l.holder === spec.symbol) return [{ s: findInstrument(l.symbol), label: `${spec.name}是其${ROLE_TEXT[l.roles]}` }]
      if (l.symbol === spec.symbol) return [{ s: findInstrument(l.holder), label: `${spec.name}的${ROLE_TEXT[l.roles]}` }]
      return []
    }).sort((a, b) => cap(b.s!) - cap(a.s!))
    affiliates.slice(0, misc ? 2 : 1).forEach((a) => add(a.s, "affiliate", a.label))
    if (affiliates.length) {
      out.notes = ["關係企業依董監事持股餘額明細（2026 年 9 月）"]
      sources.add(sourceOf(spec.market === "TPEX" ? "tpex-openapi/board" : "twse-openapi/board"))
    }
    const stocks = INSTRUMENTS.filter((i) => i.type === "stock" && i.market !== "US" && i.symbol !== spec.symbol && i.symbol !== "00999.TW")
    if (spec.industry === "其他電子業") {
      stocks.filter((i) => i.industry && ELECTRONICS.has(i.industry)).sort((a, b) => distance(cap(a), cap(spec)) - distance(cap(b), cap(spec)))
        .forEach((i) => add(i, "peer", "電子類、市值相近"))
    } else {
      const same = stocks.filter((i) => i.industry === spec.industry)
      const leader = [...same, spec].sort((a, b) => cap(b) - cap(a))[0]
      if (leader && leader.symbol !== spec.symbol) add(leader, "leader", `${spec.industry}市值最大`)
      same.sort((a, b) => distance(cap(a), cap(spec)) - distance(cap(b), cap(spec))).forEach((i) => add(i, "peer", `同為${spec.industry}`))
    }
    affiliates.slice(misc ? 2 : 1).forEach((a) => add(a.s, "affiliate", a.label))
    sources.add(sourceOf(spec.market === "TPEX" ? "tpex-openapi/company" : "twse-openapi/company"))
  }
  for (const c of picked) sources.add(sourceOf(c.symbol.endsWith(".TWO") ? "tpex-openapi/price" : "twse-openapi/price"))
  return { ...out, items: picked, sources: [...sources] }
}

// ── 關於〈公司〉 ──────────────────────────────────────────────────────────────
type Facts = Pick<CompanyAbout, "name" | "english_short_name" | "incorporated" | "listed_date" | "hq" | "registered_in" | "website" | "paid_in_capital" | "chairman" | "president" | "auditor" | "transfer_agent">

/** 2026-11-12 證交所 t187ap03_L／櫃買 mopsfin_t187ap03_O 的實際內容（董事長、總經理照原文） */
const FACTS: Record<string, Facts> = {
  "2330.TW": { name: "台灣積體電路製造股份有限公司", english_short_name: "TSMC", incorporated: "1987-02-21", listed_date: "1994-09-05", hq: "新竹科學園區", registered_in: null, website: "https://www.tsmc.com", paid_in_capital: 259323700670, chairman: "魏哲家", president: "總裁: 魏哲家", auditor: "勤業眾信聯合會計師事務所", transfer_agent: "中國信託商業銀行 代理部" },
  "2454.TW": { name: "聯發科技股份有限公司", english_short_name: "MediaTek", incorporated: "1997-05-28", listed_date: "2001-07-23", hq: "新竹科學園區", registered_in: null, website: "https://www.mediatek.com", paid_in_capital: 16049526130, chairman: "蔡明介", president: "陳冠州", auditor: "安永聯合會計師事務所", transfer_agent: "中國信託商業銀行股務代理部" },
  "2317.TW": { name: "鴻海精密工業股份有限公司", english_short_name: "HON HAI", incorporated: "1974-02-20", listed_date: "1991-06-18", hq: "新北市", registered_in: null, website: "https://www.honhai.com/zh-tw", paid_in_capital: 140757464970, chairman: "劉揚偉", president: "劉揚偉", auditor: "資誠聯合會計師事務所", transfer_agent: "福邦證券股份有限公司" },
  "6488.TWO": { name: "環球晶圓股份有限公司", english_short_name: "GWC", incorporated: "2011-10-18", listed_date: "2015-09-25", hq: "新竹科學園區", registered_in: null, website: "https://www.sas-globalwafers.com", paid_in_capital: 5281137250, chairman: "徐秀蘭", president: "Mark England", auditor: "安侯建業聯合會計師事務所", transfer_agent: "元大證券(股)公司股務代理部" },
}

const TSMC_WIKI: CompanyDescription = {
  kind: "wikipedia", label: "節錄", source: "維基百科", title: "台積電", url: "https://zh.wikipedia.org/zh-tw/%E5%8F%B0%E7%A9%8D%E9%9B%BB",
  license: "CC BY-SA 4.0", license_url: WIKIPEDIA_LICENSE_URL, revision_id: 95542651, updated_at: "2026-11-12T14:35:00+08:00",
  text: "台灣積體電路製造，簡稱台積電、TSMC，與旗下子公司合稱台積電集團，是臺灣一家專注於半導體晶片製造的高科技跨國企業，總部位於新竹科學園區，近年市值穩居全球前十大企業，也是全球最領先的半導體晶片製造商。台積電開創了專業積體電路製造服務 商業模式，只為客戶製造晶片，不設計、生產或銷售自有品牌的半導體產品，以確保不與客戶競爭；此一模式也促成了全球無廠IC設計產業的興起。",
}
/** 示範：沒有維基百科條目時，AI 只依官方資料寫的 2–3 句（真實環境由 worker 產生） */
const AI_DESCRIPTIONS: Record<string, string> = {
  "6488.TWO": "環球晶圓是半導體業公司，2011 年成立、2015 年在櫃買中心上櫃，總部位於新竹科學園區。依 ESG 揭露，主要產品為半導體晶片與晶錠；實收資本額約 53 億元。",
}

function age(from: string | null | undefined): number | null {
  if (!from) return null
  const [y, m, d] = from.split("-").map(Number) as [number, number, number]
  const [ty, tm, td] = MOCK_TODAY.split("-").map(Number) as [number, number, number]
  return ty - y - (tm < m || (tm === m && td < d) ? 1 : 0)
}

export function buildCompany(spec: MockInstrumentSpec): CompanyAbout {
  const base: CompanyAbout = {
    symbol: spec.symbol, name: spec.name, short_name: spec.name, market: spec.market, type: spec.type, industry: spec.industry,
    listing: spec.market === "TWSE" ? "上市" : spec.market === "TPEX" ? "上櫃" : null, description: null, sources: [], notes: [],
    exchanges: [], former_names: [], fund: null,
  }
  if (spec.market === "US") {
    if (spec.symbol !== "AAPL") return { ...base, notes: ["SEC 公司資料尚未取得"] }
    return {
      ...base, name: "Apple Inc.", industry: "Electronic Computers", hq: "Cupertino, CA", exchanges: ["Nasdaq"], fiscal_year_end: "09-26",
      former_names: [{ name: "APPLE INC", from: "2007-01-10", to: "2019-08-05" }, { name: "APPLE COMPUTER INC", from: "1994-01-26", to: "2007-01-04" }],
      data_date: MOCK_TODAY, sources: [sourceOf("sec-edgar/submissions")],
    }
  }
  if (spec.type === "etf") {
    const f = FUNDS[spec.symbol]
    return f
      ? { ...base, fund: { fund_type: "國內成分證券指數股票型基金", index_name: f.index, custodian: null, units: null }, data_date: MOCK_TODAY, sources: [sourceOf("twse-openapi/fund")] }
      : base
  }
  const facts = FACTS[spec.symbol]
  if (!facts) return { ...base, notes: ["公司基本資料尚未存檔"] }
  const wiki = spec.symbol === "2330.TW" ? TSMC_WIKI : null
  const ai = AI_DESCRIPTIONS[spec.symbol]
  const description: CompanyDescription | null = wiki ?? (ai ? { kind: "ai", label: "AI 依公開資料整理", text: ai, updated_at: "2026-11-12T14:35:00+08:00" } : null)
  return {
    ...base, ...facts, short_name: spec.name, years_since_incorporation: age(facts.incorporated), description, data_date: "2026-11-11",
    sources: [sourceOf(spec.market === "TPEX" ? "tpex-openapi/company" : "twse-openapi/company"), ...(wiki ? [WIKIPEDIA_ATTRIBUTION] : [])],
  }
}
