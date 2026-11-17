import type { MarketAnnouncement, MarketIndex, MarketMover, MarketOverview, MarketSector, MarketUs, MarketUsEtf, NewsItem } from "../types"
import { DATABENTO_ATTRIBUTION, GDELT_ATTRIBUTION, GDELT_GKG_ATTRIBUTION } from "./attributions"
import { INSTRUMENTS } from "./instruments"
import { addDays, MOCK_TODAY, parseDay } from "./market"

/**
 * 市場頁的示範資料（mock 模式）。形狀和後端 `GET /market/overview` 一樣；數字是示意，
 * 排行用示範商品主檔裡的普通股（不含 ETF、美股）算，和帳本、個股頁看到的價格一致。
 * 美股（`us`）是 SPY、DIA、ONEQ 在台北 `today` 之前最後一個美股交易日（紐約日期）的收盤，加上幾則 GDELT 的美股新聞。
 */

/** 往回數 n 個交易日（示範資料只排除週末），舊到新 */
function tradingDays(end: string, n: number): string[] {
  const out: string[] = []
  let d = end
  while (out.length < n) {
    if (![0, 6].includes(parseDay(d).getUTCDay())) out.push(d)
    d = addDays(d, -1)
  }
  return out.reverse()
}

/** 固定的假走勢：同一個 seed 每次一樣（截圖與測試穩定） */
function series(end: number, change: number, days: string[], seed: number, wobble: number): { t: string; v: number }[] {
  const prev = end - change
  let x = seed
  const rnd = () => {
    x = (x * 1103515245 + 12345) % 2147483648
    return x / 2147483648 - 0.5
  }
  const out: number[] = [end, prev]
  for (let i = 2; i < days.length; i++) out.push(out[i - 1]! * (1 - 0.004 + rnd() * wobble))
  return days.map((t, i) => ({ t, v: Number(out[days.length - 1 - i]!.toFixed(2)) }))
}

function index(key: MarketIndex["key"], name: string, unit: string, value: number, change: number, days: string[], seed: number, wobble = 0.02): MarketIndex {
  return { key, name, unit, value, change, change_pct: Number((change / (value - change)).toFixed(6)), date: days.at(-1)!, sparkline: series(value, change, days, seed, wobble) }
}

/** 美股收盤價的出處（和後端 datapolicy 的 `databento-equs/price` 同一句） */

/** 台北日期 `today` 之前的最後一個美股交易日（紐約日期；示範資料只排除週末）：美股收盤時台北已經是隔天早上 */
function usSessionBefore(today: string): string {
  let d = addDays(today, -1)
  while ([0, 6].includes(parseDay(d).getUTCDay())) d = addDays(d, -1)
  return d
}

function usEtf(symbol: "SPY" | "DIA" | "ONEQ", name: string, tracks: string, value: number, change: number, days: string[], seed: number): MarketUsEtf {
  return {
    key: symbol.toLowerCase(), symbol, name, tracks, unit: "美元", value, change,
    change_pct: Number((change / (value - change)).toFixed(6)), date: days.at(-1)!, sparkline: series(value, change, days, seed, 0.016),
  }
}

// 美股的新聞（GDELT，只有標題與連結）：和個股頁的示範報導一樣，虛構的媒體名稱、中性的英文標題、連到 example.com
// [標題, 媒體, 網址的最後一段, 台北早上 7 點之前幾小時]
const US_NEWS: [string, string, string, number][] = [
  ["Wall Street closes mixed as tech gains offset industrials (sample)", "Demo Wire", "us-market-1", 1],
  ["Treasury yields edge lower ahead of inflation data (sample)", "Demo Press", "us-market-2", 2],
  ["Chip stocks lift the Nasdaq; a sample market headline", "Demo Markets TV", "us-market-3", 4],
  ["Industrial shares slip after factory orders data (sample)", "Demo Wire", "us-market-4", 7],
  ["What investors watch in next week's retail earnings (sample)", "Demo Business Review", "us-market-5", 11],
]

function usMarket(today: string): MarketUs {
  const days = tradingDays(usSessionBefore(today), 20)
  // 新聞的時間：台北 `today` 早上 7 點之前（紐約前一天的下午到傍晚），比示範的「現在」早
  const base = Date.parse(`${today}T07:00:00+08:00`)
  const news: NewsItem[] = US_NEWS.map(([title, outlet, slug, hoursAgo]) => ({
    published_at: `${new Date(base - hoursAgo * 3_600_000 + 8 * 3_600_000).toISOString().slice(0, 19)}+08:00`,
    title, source: "GDELT", outlet, url: `https://example.com/demo-news/${slug}`, category: "media", date_only: false, sources: [GDELT_ATTRIBUTION],
  }))
  return {
    date: days.at(-1)!,
    items: [
      usEtf("SPY", "SPDR S&P 500 ETF Trust", "S&P 500", 683.41, 4.12, days, 13),
      usEtf("DIA", "SPDR Dow Jones Industrial Average ETF Trust", "道瓊工業指數", 471.86, -1.37, days, 17),
      usEtf("ONEQ", "Fidelity Nasdaq Composite Index ETF", "那斯達克綜合指數", 87.94, 0.88, days, 19),
    ],
    news,
  }
}

const SECTORS: [string, number][] = [
  ["半導體", 0.0312], ["電腦及週邊設備", 0.0241], ["其他電子", 0.0188], ["電子零組件", 0.0152], ["通信網路", 0.0097],
  ["電機機械", 0.0081], ["光電", 0.0066], ["電子通路", 0.0058], ["資訊服務", 0.0044], ["綠能環保", 0.0037], ["數位雲端", 0.0031],
  ["航運", 0.0024], ["金融保險", 0.0019], ["汽車", 0.0012], ["貿易百貨", 0.0006], ["運動休閒", 0.0002], ["居家生活", -0.0004],
  ["食品", -0.0011], ["紡織纖維", -0.0018], ["電器電纜", -0.0023], ["化學", -0.0029], ["生技醫療", -0.0036], ["油電燃氣", -0.0041],
  ["橡膠", -0.0052], ["造紙", -0.0063], ["鋼鐵", -0.0074], ["塑膠", -0.0089], ["建材營造", -0.0102], ["觀光餐旅", -0.0118],
  ["水泥", -0.0131], ["玻璃陶瓷", -0.0187], ["其他", -0.0009],
]

const TITLES = [
  "公告本公司董事會決議股利分派",
  "公告本公司 115 年第三季合併財務報告董事會通過日期",
  "本公司受邀參加證券商舉辦之法人說明會",
  "澄清媒體報導",
  "公告本公司取得機器設備",
  "代子公司公告資金貸與金額達公告標準",
  "公告本公司董事會決議召開 116 年股東常會",
  "公告本公司新增背書保證金額達公告標準",
  "公告本公司董事會通過發行限制員工權利新股",
  "本公司 115 年 10 月份自結合併營收",
  "公告本公司董事會決議買回庫藏股",
  "公告本公司更換會計主管",
]

export function buildMarketOverview(demo: boolean, today = MOCK_TODAY): MarketOverview {
  const days = tradingDays(today, 20)
  const day = days.at(-1)!
  const indices: MarketIndex[] = [
    index("taiex", "加權指數", "點", 27270.34, 318.55, days, 7),
    index("tpex", "櫃買指數", "點", 297.42, -1.86, days, 11),
    // 台指期的授權待確認：和後端一樣，預設（commercial）不提供
    ...(demo ? [index("tx", "台指期近月", "點", 27305, 331, days, 5)] : []),
    index("usdtwd", "美元兌新台幣", "元", 31.437, -0.063, days, 3, 0.004),
  ]
  const stocks = INSTRUMENTS.filter((i) => (i.market === "TWSE" || i.market === "TPEX") && i.type === "stock" && /^(?!00)\d{4}$/.test(i.code))
  const movers: MarketMover[] = stocks.map((i) => ({
    symbol: i.symbol, code: i.code, name: i.name, market: i.market, close: i.price,
    change: Number((i.price - i.prev_close).toFixed(2)), change_pct: Number(((i.price - i.prev_close) / i.prev_close).toFixed(6)), volume: i.avg_volume,
  }))
  const by = (f: (m: MarketMover) => number, only: (m: MarketMover) => boolean = () => true) => movers.filter(only).sort((a, b) => f(b) - f(a)).slice(0, 10)
  const announcements: MarketAnnouncement[] = TITLES.map((title, n) => {
    const i = stocks[n % stocks.length]!
    const minutes = 18 * 60 + 40 - n * 23
    return { symbol: i.symbol, code: i.code, name: i.name, title, date: day, time: `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`, url: null }
  })
  const sectors: MarketSector[] = SECTORS.map(([name, change_pct], n) => ({ name, index_name: `${name}類指數`, close: Number((180 + n * 37.4).toFixed(2)), change_pct })).sort((a, b) => b.change_pct - a.change_pct)
  return {
    as_of: day,
    indices,
    summary: {
      date: day,
      headline: "加權指數收漲 1.18%，半導體類股領漲",
      points: [
        { text: "加權指數終場上漲 318.55 點，收在 27,270.34 點，成交金額 4,820 億元。", sources: [{ url: "https://example.com/news/close", title: "台股收盤上漲 318 點", outlet: "示範通訊社" }] },
        { text: "半導體類股上漲 3.12%，台積電收 1,085 元、上漲 4.83%。", sources: [{ url: "https://example.com/news/semis", title: "半導體領軍 台積電創高", outlet: "示範日報" }, { url: "https://example.com/news/tsmc", title: "台積電收 1,085 元", outlet: "示範財經網" }] },
        { text: "三大法人合計買超 286 億元，外資買超 231 億元。", sources: [{ url: "https://example.com/news/flows", title: "三大法人買超 286 億元", outlet: "示範通訊社" }] },
        { text: "水泥與玻璃陶瓷類股下跌，跌幅都超過 1%。", sources: [{ url: "https://example.com/news/laggards", title: "傳產類股走弱", outlet: "示範日報" }] },
      ],
    },
    sectors: { date: day, items: sectors },
    movers: {
      date: day, prev_date: days.at(-2)!, count: movers.length,
      gainers: by((m) => m.change_pct ?? 0, (m) => (m.change_pct ?? 0) > 0),
      losers: by((m) => -(m.change_pct ?? 0), (m) => (m.change_pct ?? 0) < 0),
      volume: by((m) => m.volume ?? 0),
    },
    announcements: { date: day, start_date: day, total: 428, items: announcements },
    us: usMarket(today),
    is_demo: demo,
    notes: [],
    sources: [
      "臺灣證券交易所〈每日收盤行情-大盤統計資訊〉（2026），依政府資料開放授權條款第 1 版",
      "證券櫃檯買賣中心〈櫃買指數歷史資料〉（2026），依政府資料開放授權條款第 1 版",
      "中央銀行〈銀行間新臺幣對美元收盤匯率〉（2026），依政府資料開放授權條款第 1 版",
      "臺灣證券交易所〈上市個股日成交資訊〉（2026），依政府資料開放授權條款第 1 版",
      "證券櫃檯買賣中心〈上櫃股票行情〉（2026），依政府資料開放授權條款第 1 版",
      "臺灣證券交易所〈上市公司每日重大訊息〉（2026），依政府資料開放授權條款第 1 版",
      DATABENTO_ATTRIBUTION,
      GDELT_GKG_ATTRIBUTION, // 美股新聞：英文整批檔為主、查詢 API 備用（後端兩個都列）
      GDELT_ATTRIBUTION,
    ],
  }
}
