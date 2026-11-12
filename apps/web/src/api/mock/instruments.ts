import type { InstrumentDetail } from "../types"

/** 示範資料用的商品主檔。數字為示意，不代表真實行情。 */
export interface MockInstrumentSpec extends Omit<InstrumentDetail, "is_demo"> {
  /** 示範報價：現價與昨收 */
  price: number
  prev_close: number
  /** 歷史走勢的年化漂移與波動（產生示範 K 線用） */
  drift: number
  vol: number
  /** 平均日成交量（股） */
  avg_volume: number
  /** 估值：目前近四季 EPS、每股淨值，以及河流圖倍數 */
  eps_now?: number
  eps_growth?: number
  bvps_now?: number
  per_multiples?: number[]
  pbr_multiples?: number[]
  /** 月營收基準（千元）與年成長 */
  revenue_base?: number
  revenue_growth?: number
}

const TWSE_SRC = ["臺灣證券交易所 OpenAPI（政府資料開放授權條款第 1 版）", "shioaji-data（政府資料開放授權條款第 1 版）"]

export const INSTRUMENTS: MockInstrumentSpec[] = [
  {
    symbol: "2330.TW", code: "2330", name: "台積電", market: "TWSE", type: "stock", currency: "TWD", industry: "半導體業",
    summary: "全球最大的專業積體電路製造服務（晶圓代工）公司，先進製程與先進封裝（CoWoS、SoIC）為主要成長動能。",
    chain_stage: "晶圓製造", themes: ["CoWoS", "AI 伺服器", "先進製程", "蘋果概念"],
    shares_outstanding: 25932666666, market_cap: 28137000000000, data_sources: TWSE_SRC,
    price: 1085, prev_close: 1035, drift: 0.19, vol: 0.27, avg_volume: 30_000_000,
    eps_now: 52.3, eps_growth: 0.24, bvps_now: 190.1, per_multiples: [12, 16, 20, 24, 28], pbr_multiples: [3, 4, 5, 6, 7],
    revenue_base: 330_000_000, revenue_growth: 0.31,
  },
  {
    symbol: "0050.TW", code: "0050", name: "元大台灣50", market: "TWSE", type: "etf", currency: "TWD", industry: "ETF",
    summary: "追蹤臺灣 50 指數，投資臺灣市值前 50 大上市公司，是國內規模最大的 ETF 之一。",
    chain_stage: null, themes: ["市值型", "大盤"], shares_outstanding: null, market_cap: null, data_sources: TWSE_SRC,
    price: 72.4, prev_close: 71.85, drift: 0.14, vol: 0.19, avg_volume: 45_000_000,
  },
  {
    symbol: "00878.TW", code: "00878", name: "國泰永續高股息", market: "TWSE", type: "etf", currency: "TWD", industry: "ETF",
    summary: "追蹤 MSCI 臺灣 ESG 永續高股息精選 30 指數，季配息。",
    chain_stage: null, themes: ["高股息", "ESG", "季配息"], shares_outstanding: null, market_cap: null, data_sources: TWSE_SRC,
    price: 22.86, prev_close: 22.91, drift: 0.05, vol: 0.13, avg_volume: 38_000_000,
  },
  {
    symbol: "2454.TW", code: "2454", name: "聯發科", market: "TWSE", type: "stock", currency: "TWD", industry: "半導體業",
    summary: "全球主要 IC 設計公司，產品涵蓋手機晶片、智慧家庭、車用與 ASIC。",
    chain_stage: "IC 設計", themes: ["手機晶片", "ASIC", "邊緣 AI"], shares_outstanding: 1603000000, market_cap: 2300305000000, data_sources: TWSE_SRC,
    price: 1435, prev_close: 1450, drift: 0.17, vol: 0.33, avg_volume: 4_200_000,
    eps_now: 66.8, eps_growth: 0.1, bvps_now: 335, per_multiples: [12, 15, 18, 21, 24], pbr_multiples: [2.5, 3, 3.5, 4, 4.5],
    revenue_base: 51_000_000, revenue_growth: 0.09,
  },
  {
    symbol: "2317.TW", code: "2317", name: "鴻海", market: "TWSE", type: "stock", currency: "TWD", industry: "其他電子業",
    summary: "全球最大的電子製造服務（EMS）廠，AI 伺服器組裝與電動車為新成長動能。",
    chain_stage: "系統組裝", themes: ["AI 伺服器", "電動車", "蘋果概念"], shares_outstanding: 13900000000, market_cap: 3287350000000, data_sources: TWSE_SRC,
    price: 236.5, prev_close: 231, drift: 0.22, vol: 0.31, avg_volume: 52_000_000,
    eps_now: 13.9, eps_growth: 0.15, bvps_now: 132.4, per_multiples: [8, 11, 14, 17, 20], pbr_multiples: [1, 1.3, 1.6, 1.9, 2.2],
    revenue_base: 820_000_000, revenue_growth: 0.17,
  },
  {
    symbol: "6488.TWO", code: "6488", name: "環球晶", market: "TPEX", type: "stock", currency: "TWD", industry: "半導體業",
    summary: "全球前三大矽晶圓供應商，產品包含 12 吋、8 吋矽晶圓與化合物半導體基板。",
    chain_stage: "矽晶圓", themes: ["矽晶圓", "化合物半導體"], shares_outstanding: 478000000, market_cap: 190244000000, data_sources: ["櫃買中心 OpenAPI（政府資料開放授權條款第 1 版）"],
    price: 398, prev_close: 405.5, drift: -0.08, vol: 0.36, avg_volume: 2_100_000,
    eps_now: 14.2, eps_growth: -0.18, bvps_now: 224.5, per_multiples: [10, 14, 18, 22, 26], pbr_multiples: [1.5, 2, 2.5, 3, 3.5],
    revenue_base: 5_200_000, revenue_growth: -0.06,
  },
  {
    symbol: "AAPL", code: "AAPL", name: "Apple", market: "US", type: "stock", currency: "USD", industry: "Consumer Electronics",
    summary: "設計與銷售 iPhone、Mac、iPad 與穿戴裝置，並提供 App Store、iCloud 等服務。",
    chain_stage: "品牌", themes: ["消費電子", "服務訂閱"], shares_outstanding: 14840000000, market_cap: 3983352800000, data_sources: ["示範資料（美股資料來源待定）"],
    price: 268.42, prev_close: 266.1, drift: 0.16, vol: 0.26, avg_volume: 52_000_000,
    eps_now: 7.46, eps_growth: 0.09, bvps_now: 4.4, per_multiples: [18, 23, 28, 33, 38], pbr_multiples: [30, 40, 50, 60, 70],
  },
  {
    symbol: "NVDA", code: "NVDA", name: "NVIDIA", market: "US", type: "stock", currency: "USD", industry: "Semiconductors",
    summary: "GPU 與 AI 加速運算平台領導廠商，資料中心為最大營收來源。",
    chain_stage: "IC 設計", themes: ["AI 伺服器", "GPU"], shares_outstanding: 24300000000, market_cap: 5158890000000, data_sources: ["示範資料（美股資料來源待定）"],
    price: 212.3, prev_close: 208.75, drift: 0.55, vol: 0.5, avg_volume: 190_000_000,
    eps_now: 4.12, eps_growth: 0.6, bvps_now: 5.1, per_multiples: [25, 35, 45, 55, 65], pbr_multiples: [15, 25, 35, 45, 55],
  },
  {
    symbol: "VOO", code: "VOO", name: "Vanguard S&P 500 ETF", market: "US", type: "etf", currency: "USD", industry: "ETF",
    summary: "追蹤 S&P 500 指數的低成本 ETF，季配息。", chain_stage: null, themes: ["美股大盤", "季配息"],
    shares_outstanding: null, market_cap: null, data_sources: ["示範資料（美股資料來源待定）"],
    price: 634.2, prev_close: 631.9, drift: 0.13, vol: 0.17, avg_volume: 6_000_000,
  },
  // ── 不在持股中、但可以搜尋的商品 ───────────────────────────
  {
    symbol: "2382.TW", code: "2382", name: "廣達", market: "TWSE", type: "stock", currency: "TWD", industry: "電腦及週邊設備業",
    summary: "全球主要筆記型電腦代工廠，AI 伺服器與雲端資料中心為主要成長動能。",
    chain_stage: "系統組裝", themes: ["AI 伺服器", "筆電"], shares_outstanding: 3863000000, market_cap: 1207187500000, data_sources: TWSE_SRC,
    price: 312.5, prev_close: 310, drift: 0.2, vol: 0.34, avg_volume: 14_000_000,
    eps_now: 18.4, eps_growth: 0.2, bvps_now: 78.2, per_multiples: [10, 13, 16, 19, 22], pbr_multiples: [2, 2.5, 3, 3.5, 4],
    revenue_base: 150_000_000, revenue_growth: 0.22,
  },
  {
    symbol: "2308.TW", code: "2308", name: "台達電", market: "TWSE", type: "stock", currency: "TWD", industry: "電子零組件業",
    summary: "電源管理與散熱解決方案大廠，資料中心電源、電動車零組件與自動化為主要業務。",
    chain_stage: "電源與散熱", themes: ["AI 伺服器", "電源", "電動車"], shares_outstanding: 2597000000, market_cap: 2635955000000, data_sources: TWSE_SRC,
    price: 1015, prev_close: 1020, drift: 0.24, vol: 0.3, avg_volume: 6_500_000,
    eps_now: 21.6, eps_growth: 0.18, bvps_now: 118, per_multiples: [20, 26, 32, 38, 44], pbr_multiples: [4, 5, 6, 7, 8],
    revenue_base: 48_000_000, revenue_growth: 0.15,
  },
  {
    symbol: "2881.TW", code: "2881", name: "富邦金", market: "TWSE", type: "stock", currency: "TWD", industry: "金融保險業",
    summary: "台灣主要金融控股公司，旗下有富邦人壽、台北富邦銀行、富邦證券等。",
    chain_stage: "金融控股", themes: ["金融", "壽險"], shares_outstanding: 13700000000, market_cap: 1227520000000, data_sources: TWSE_SRC,
    price: 89.6, prev_close: 89.3, drift: 0.1, vol: 0.22, avg_volume: 18_000_000,
    eps_now: 9.8, eps_growth: 0.05, bvps_now: 78.5, per_multiples: [6, 8, 10, 12, 14], pbr_multiples: [0.8, 1, 1.2, 1.4, 1.6],
  },
  {
    symbol: "2409.TW", code: "2409", name: "友達", market: "TWSE", type: "stock", currency: "TWD", industry: "光電業",
    summary: "面板製造廠，近年轉型智慧移動、智慧零售等解決方案。面板景氣循環明顯，曾出現連續虧損。",
    chain_stage: "面板", themes: ["面板", "車用顯示"], shares_outstanding: 7620000000, market_cap: 112014000000, data_sources: TWSE_SRC,
    price: 14.7, prev_close: 14.55, drift: -0.04, vol: 0.32, avg_volume: 60_000_000,
    eps_now: 0.42, eps_growth: 0, bvps_now: 17.8, per_multiples: [8, 12, 16, 20, 24], pbr_multiples: [0.6, 0.8, 1, 1.2, 1.4],
    revenue_base: 24_000_000, revenue_growth: 0.02,
  },
  {
    symbol: "0056.TW", code: "0056", name: "元大高股息", market: "TWSE", type: "etf", currency: "TWD", industry: "ETF",
    summary: "追蹤臺灣高股息指數，季配息。", chain_stage: null, themes: ["高股息", "季配息"],
    shares_outstanding: null, market_cap: null, data_sources: TWSE_SRC,
    price: 36.12, prev_close: 36.05, drift: 0.04, vol: 0.14, avg_volume: 25_000_000,
  },
  {
    symbol: "2603.TW", code: "2603", name: "長榮", market: "TWSE", type: "stock", currency: "TWD", industry: "航運業",
    summary: "全球主要貨櫃航運公司。", chain_stage: "貨櫃航運", themes: ["航運"],
    shares_outstanding: 2115000000, market_cap: 438862500000, data_sources: TWSE_SRC,
    price: 207.5, prev_close: 209, drift: 0.05, vol: 0.38, avg_volume: 15_000_000,
    eps_now: 38.5, eps_growth: -0.3, bvps_now: 210, per_multiples: [3, 5, 7, 9, 11], pbr_multiples: [0.6, 0.8, 1, 1.2, 1.4],
    revenue_base: 33_000_000, revenue_growth: -0.12,
  },
  {
    symbol: "3008.TW", code: "3008", name: "大立光", market: "TWSE", type: "stock", currency: "TWD", industry: "光電業",
    summary: "手機鏡頭模組光學元件大廠。", chain_stage: "光學鏡頭", themes: ["蘋果概念", "光學"],
    shares_outstanding: 133000000, market_cap: 296590000000, data_sources: TWSE_SRC,
    price: 2230, prev_close: 2215, drift: 0.02, vol: 0.3, avg_volume: 450_000,
    eps_now: 168, eps_growth: 0.05, bvps_now: 1350, per_multiples: [10, 13, 16, 19, 22], pbr_multiples: [1.2, 1.6, 2, 2.4, 2.8],
    revenue_base: 5_800_000, revenue_growth: 0.04,
  },
  {
    symbol: "00919.TW", code: "00919", name: "群益台灣精選高息", market: "TWSE", type: "etf", currency: "TWD", industry: "ETF",
    summary: "精選高股息個股的 ETF，季配息。", chain_stage: null, themes: ["高股息", "季配息"],
    shares_outstanding: null, market_cap: null, data_sources: TWSE_SRC,
    price: 22.41, prev_close: 22.47, drift: 0.03, vol: 0.15, avg_volume: 30_000_000,
  },
  {
    symbol: "2412.TW", code: "2412", name: "中華電", market: "TWSE", type: "stock", currency: "TWD", industry: "通信網路業",
    summary: "臺灣最大電信業者。", chain_stage: "電信服務", themes: ["電信", "防禦型"],
    shares_outstanding: 7757000000, market_cap: 1031681000000, data_sources: TWSE_SRC,
    price: 133, prev_close: 132.5, drift: 0.04, vol: 0.09, avg_volume: 6_000_000,
    eps_now: 4.85, eps_growth: 0.02, bvps_now: 51.2, per_multiples: [22, 24, 26, 28, 30], pbr_multiples: [2.2, 2.4, 2.6, 2.8, 3],
    revenue_base: 19_000_000, revenue_growth: 0.02,
  },
  {
    symbol: "MSFT", code: "MSFT", name: "Microsoft", market: "US", type: "stock", currency: "USD", industry: "Software",
    summary: "作業系統、Office 與 Azure 雲端服務。", chain_stage: "軟體", themes: ["雲端", "AI"],
    shares_outstanding: 7430000000, market_cap: 3900000000000, data_sources: ["示範資料（美股資料來源待定）"],
    price: 524.9, prev_close: 527.1, drift: 0.18, vol: 0.24, avg_volume: 20_000_000,
    eps_now: 14.1, eps_growth: 0.14, bvps_now: 46, per_multiples: [25, 29, 33, 37, 41], pbr_multiples: [9, 11, 13, 15, 17],
  },
  // ── 「相關股票」會出現的商品（關係企業、同業、同指數 ETF） ─────────────
  {
    symbol: "3443.TW", code: "3443", name: "創意", market: "TWSE", type: "stock", currency: "TWD", industry: "半導體業",
    summary: null, chain_stage: "IC 設計服務", themes: ["ASIC"], shares_outstanding: 134011911, market_cap: 262663345560, data_sources: TWSE_SRC,
    price: 1960, prev_close: 1985, drift: 0.2, vol: 0.45, avg_volume: 1_400_000,
  },
  {
    symbol: "3711.TW", code: "3711", name: "日月光投控", market: "TWSE", type: "stock", currency: "TWD", industry: "半導體業",
    summary: null, chain_stage: "封裝測試", themes: ["先進封裝"], shares_outstanding: 4488089243, market_cap: 960451098002, data_sources: TWSE_SRC,
    price: 214, prev_close: 211, drift: 0.12, vol: 0.3, avg_volume: 18_000_000,
  },
  {
    symbol: "5483.TWO", code: "5483", name: "中美晶", market: "TPEX", type: "stock", currency: "TWD", industry: "半導體業",
    summary: null, chain_stage: "矽晶圓", themes: ["矽晶圓"], shares_outstanding: 641221651, market_cap: 75664154818, data_sources: ["櫃買中心 OpenAPI（政府資料開放授權條款第 1 版）"],
    price: 118, prev_close: 120, drift: -0.05, vol: 0.35, avg_volume: 3_000_000,
  },
  {
    symbol: "2258.TW", code: "2258", name: "鴻華先進-創", market: "TWSE", type: "stock", currency: "TWD", industry: "汽車工業",
    summary: null, chain_stage: null, themes: ["電動車"], shares_outstanding: 1751267300, market_cap: 109454206250, data_sources: TWSE_SRC,
    price: 62.5, prev_close: 61.8, drift: 0.05, vol: 0.4, avg_volume: 5_000_000,
  },
  {
    symbol: "2328.TW", code: "2328", name: "廣宇", market: "TWSE", type: "stock", currency: "TWD", industry: "電子零組件業",
    summary: null, chain_stage: null, themes: [], shares_outstanding: 518346282, market_cap: 21407701447, data_sources: TWSE_SRC,
    price: 41.3, prev_close: 40.9, drift: 0.04, vol: 0.3, avg_volume: 2_000_000,
  },
  {
    symbol: "006208.TW", code: "006208", name: "富邦台50", market: "TWSE", type: "etf", currency: "TWD", industry: "ETF",
    summary: null, chain_stage: null, themes: ["市值型"], shares_outstanding: null, market_cap: null, data_sources: TWSE_SRC,
    price: 139.2, prev_close: 138.4, drift: 0.14, vol: 0.19, avg_volume: 9_000_000,
  },
  {
    symbol: "006201.TWO", code: "006201", name: "元大富櫃50", market: "TPEX", type: "etf", currency: "TWD", industry: "ETF",
    summary: null, chain_stage: null, themes: ["中小型"], shares_outstanding: null, market_cap: null, data_sources: ["櫃買中心 OpenAPI（政府資料開放授權條款第 1 版）"],
    price: 34.85, prev_close: 35.1, drift: 0.08, vol: 0.22, avg_volume: 600_000,
  },
  // 上櫃債券 ETF：淨值是前一個營業日的（海外標的），示範「淨值日期與收盤日期不同」
  {
    symbol: "00679B.TWO", code: "00679B", name: "元大美債20年", market: "TPEX", type: "etf", currency: "TWD", industry: "ETF",
    summary: null, chain_stage: null, themes: ["債券", "美債"], shares_outstanding: null, market_cap: null, data_sources: ["櫃買中心 OpenAPI（政府資料開放授權條款第 1 版）"],
    price: 26.61, prev_close: 26.55, drift: 0.01, vol: 0.12, avg_volume: 9_000_000,
  },
]

/** 壓力測試情境（?mock=stress）用：超長名稱、上千億市值、大幅下跌 */
export const STRESS_INSTRUMENT: MockInstrumentSpec = {
  symbol: "00999.TW", code: "00999", name: "富邦特選台灣永續高股息低波動精選三十指數證券投資信託基金", market: "TWSE", type: "etf", currency: "TWD", industry: "ETF",
  summary: null, chain_stage: null, themes: [], shares_outstanding: null, market_cap: null, data_sources: ["壓力測試資料"],
  price: 12500, prev_close: 12705, drift: 0.02, vol: 0.2, avg_volume: 1_000_000,
}
INSTRUMENTS.push(STRESS_INSTRUMENT)

/** 2409 友達：示範「近四季 EPS ≤ 0」的期間（河流圖留白） */
export const NEGATIVE_EPS_WINDOWS: Record<string, { from: string; to: string; eps: number }[]> = {
  "2409.TW": [
    { from: "2023-01-01", to: "2023-12-31", eps: -2.18 },
    { from: "2024-01-01", to: "2024-09-30", eps: -0.86 },
  ],
}

export function findInstrument(symbol: string): MockInstrumentSpec | undefined {
  const s = symbol.toUpperCase()
  return INSTRUMENTS.find((i) => i.symbol.toUpperCase() === s || i.code.toUpperCase() === s)
}
