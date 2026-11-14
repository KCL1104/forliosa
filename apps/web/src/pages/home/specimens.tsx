import { ChevronDownIcon } from "lucide-react"
import { direction, directionGlyph, formatMoney, formatNumber, formatPercent, formatPrice, toneClass } from "@/lib/format"
import { cn } from "@/lib/utils"

/**
 * 介紹頁的三個示範畫面：帳本、個股頁、問 AI。用示範資料、照產品自己的樣子畫（手機版的排法、同一套字級、格線、
 * 漲跌色與草稿卡的樣式），不是截圖——所以跟著淺色／深色，也不會糊。數字和 mock 的示範帳本相同。
 * - 畫面上沒有日期（寫死的日期過幾個月會像壞掉的資料）。
 * - 沒有可以按的東西：按鈕都畫成 `<span>`，整塊不接收滑鼠（`pointer-events-none`），也不在 Tab 順序裡。
 * - 內容對螢幕報讀器隱藏（一串假數字沒有意義），外框（`HomePage` 的 `Specimen`）另外讀一句說明。
 * 這裡不 import 帳本、個股頁或 AI 面板的元件：那些要登入後的資料與狀態。
 */

function Delta({ amount, pct }: { amount: number; pct: number }) {
  const d = direction(amount)
  return (
    <span className={cn("num inline-flex flex-wrap items-baseline gap-x-2 [&>*]:whitespace-nowrap", toneClass(d))}>
      <span>{formatMoney(amount, { signed: true })}</span>
      <span>
        {directionGlyph(d)}
        {formatPercent(Math.abs(pct), { signed: false, decimals: Math.abs(pct) >= 0.1 ? 1 : 2 })}
      </span>
    </span>
  )
}

// -- 帳本 -------------------------------------------------------------------------------------------------
const TOTAL = 3_707_922
const DAY = { amount: 78_015, pct: 0.0215 }
const PNL = { amount: 1_005_572, pct: 0.354 }
// 九檔裡的三檔：台積電是「個股」那一欄的那一檔，0050 是「問 AI」那一欄買的那一檔，再一檔下跌的（漲跌兩種顏色都看得到）
const HOLDINGS: { name: string; code: string; qty: string; price: string; pct: number }[] = [
  { name: "台積電", code: "2330", qty: "1 張 500 股", price: "1,085", pct: 0.0483 },
  { name: "元大台灣50", code: "0050", qty: "5 張 779 股", price: "72.40", pct: 0.0077 },
  { name: "國泰永續高股息", code: "00878", qty: "13 張 260 股", price: "22.86", pct: -0.0022 },
]

/** 帳本：總資產、今日與總損益，下面一列一檔持股 */
export function LedgerSpecimen() {
  return (
    <>
      <p className="text-base font-medium text-ink">總資產</p>
      <p className="hero-figure mt-1 flex items-baseline text-4xl font-medium tracking-[-0.015em] text-ink">
        <span className="mr-1.5 text-lg font-normal tracking-normal text-ink-2">NT$</span>
        {formatMoney(TOTAL, { bare: true })}
      </p>
      <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-3 gap-y-1">
        <dt className="text-sm text-ink-2">今日</dt>
        <dd className="text-lg font-medium">
          <Delta {...DAY} />
        </dd>
        <dt className="text-sm text-ink-2">總損益（含股利）</dt>
        <dd className="text-lg font-medium">
          <Delta {...PNL} />
        </dd>
      </dl>

      <div className="form-head mt-6 flex items-center justify-between gap-3 pb-2">
        <span>持有 9 檔</span>
        <span>收盤價・今日漲跌</span>
      </div>
      {/* 桌面三欄等高：這一欄比較短時，多出來的高度平分給每一列，最後一列的格線落在欄底（和另外兩欄的底線同一個高度） */}
      <ul className="flex flex-1 flex-col">
        {HOLDINGS.map((r) => {
          const d = direction(r.pct)
          return (
            <li key={r.code} className="flex flex-1 items-center justify-between gap-4 border-b border-rule py-3">
              <span className="min-w-0">
                <span className="block truncate text-lg font-medium text-ink">{r.name}</span>
                <span className="num block text-sm text-ink-2">
                  {r.code}・{r.qty}
                </span>
              </span>
              <span className="num shrink-0 text-right">
                <span className="block text-lg text-ink">{r.price}</span>
                <span className={cn("block text-base", toneClass(d))}>
                  {directionGlyph(d)}
                  {formatPercent(Math.abs(r.pct), { signed: false })}
                </span>
              </span>
            </li>
          )
        })}
      </ul>
    </>
  )
}

// -- 個股頁 -----------------------------------------------------------------------------------------------
// 一季左右的收盤價（示範）：最後一天 1,035 → 1,085，和帳本那一列的 ▲4.83% 是同一天
const CLOSES = [
  959, 971, 978, 970, 968, 980, 986, 992, 976, 972, 981, 972, 972, 964, 958, 954, 966, 956, 958, 962, 972, 983, 989, 1000, 1010, 1015, 1020, 1015, 1010, 1035, 1025, 1045,
  1040, 1060, 1055, 1065, 1070, 1055, 1055, 1035, 1035, 1035, 1025, 1020, 1020, 1010, 1025, 1015, 1040, 1025, 1040, 1035, 1045, 1035, 1045, 1040, 1050, 1040, 1040, 1030,
  1040, 1040, 1035, 1085,
]
// 縱軸 950–1,100，格線在 1,050／1,000／950：最下面那條格線就是圖的下緣（桌面三欄的底線對齊在這裡）；
// 最後一天的價位標籤（1,085）和最近的刻度隔 20px 以上，不會疊在一起
const Y_MIN = 950
const Y_MAX = 1100
const Y_TICKS = [1050, 1000, 950]
/** 價位在圖上的高度（0 是最上面，100 是最下面） */
const yOf = (v: number) => ((Y_MAX - v) / (Y_MAX - Y_MIN)) * 100
const LINE = CLOSES.map((v, i) => `${i === 0 ? "M" : "L"}${((i / (CLOSES.length - 1)) * 100).toFixed(2)} ${yOf(v).toFixed(2)}`).join("")
const LAST = CLOSES.at(-1)!
const PREV = CLOSES.at(-2)!

/** 個股頁：名稱、收盤價與漲跌、我的部位、走勢 */
export function StockSpecimen() {
  const change = LAST - PREV
  return (
    <>
      <p className="num flex flex-wrap gap-x-3 text-sm text-ink-2">
        <span>2330</span>
        <span>上市・半導體業</span>
      </p>
      <p className="mt-1 text-2xl font-bold tracking-[-0.01em] text-ink">台積電</p>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <p className="hero-figure text-4xl font-medium tracking-[-0.015em] text-ink">{formatPrice(LAST, "TWSE", "stock")}</p>
        <p className="num text-xl font-medium text-rise">
          {directionGlyph("up")}
          {change}
          <span className="ml-3">
            {directionGlyph("up")}
            {formatPercent(change / PREV, { signed: false })}
          </span>
        </p>
      </div>
      <p className="num mt-1 flex flex-wrap gap-x-4 text-sm text-ink-2">
        <span>
          參考價 <span className="text-ink">{formatPrice(PREV, "TWSE", "stock")}</span>
        </span>
        <span>
          漲停 <span className="text-ink">1,135</span>・跌停 <span className="text-ink">932</span>
        </span>
      </p>

      <dl className="num mt-5 flex flex-wrap gap-x-5 gap-y-1.5 border-y border-rule py-2.5 text-base">
        <Item label="持有" value="1 張 500 股" />
        <Item label="均價" value="692.61" />
        <Item
          label="未實現"
          value={
            <span className="inline-flex items-baseline gap-1.5 text-rise">
              {formatMoney(588_587, { signed: true })}
              <span>
                {directionGlyph("up")}
                {formatPercent(0.5665, { signed: false })}
              </span>
            </span>
          }
        />
      </dl>

      <p className="num mt-4 flex flex-wrap gap-x-4 text-sm text-ink-2">
        <span>
          收 <span className="text-ink">{formatPrice(LAST, "TWSE", "stock")}</span>
        </span>
        <span>
          量 <span className="text-ink">{formatNumber(36_212)} 張</span>
        </span>
      </p>
      {/* 走勢：線用 SVG（跟著欄寬伸縮，線寬不變）；價位的字是 HTML，不會被拉寬。右邊留 3rem 給縱軸 */}
      <div className="relative mt-2 min-h-36 flex-1 lg:min-h-28">
        {Y_TICKS.map((t) => (
          <span key={t} className="absolute inset-x-0 flex -translate-y-1/2 items-center gap-2" style={{ top: `${yOf(t)}%` }}>
            {/* 最下面那條是圖的下緣：用格線色（和帳本最後一列的格線同一種），其他是圖表的淡格線 */}
            <span className={cn("h-px flex-1", t === Y_MIN ? "bg-rule" : "bg-chart-grid")} />
            <span className="num w-10 text-xs text-ink-2">{formatNumber(t)}</span>
          </span>
        ))}
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-y-0 left-0 h-full w-[calc(100%-3rem)] overflow-visible">
          <path d={LINE} fill="none" stroke="var(--chart-mine)" strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        </svg>
        {/* 最後一天的價位：和走勢圖縱軸上的標籤同一組顏色（on-bg／on-fg；深色是格線藍底，不是白色實塊） */}
        <span className="num absolute right-0 flex h-5 w-12 -translate-y-1/2 items-center bg-on-bg pl-2 text-xs text-on-fg" style={{ top: `${yOf(LAST)}%` }}>
          {formatPrice(LAST, "TWSE", "stock")}
        </span>
      </div>
    </>
  )
}

function Item({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="text-sm text-ink-2">{label}</dt>
      <dd className="font-medium text-ink">{value}</dd>
    </div>
  )
}

// -- 問 AI -------------------------------------------------------------------------------------------
/** 問 AI：使用者打的一句話 → 草稿卡（石墨灰虛線；稅費算在合計裡）→ 簽名格 */
export function DraftSpecimen() {
  return (
    <div className="flex flex-1 flex-col">
      <p className="max-w-[85%] self-end rounded-sm border border-rule bg-raised px-3.5 py-1.5 text-base text-ink">買 0050 2 張 52.4</p>
      {/* 桌面三欄等高：草稿卡靠欄底（下緣和另外兩欄的底線同一個高度），多出來的高度留在使用者那句話下面。
          不放助理的回覆句：這一頁字越少越好，草稿卡自己就是回覆 */}
      <div className="mt-4 border border-dashed border-ai-rule bg-ai-wash lg:mt-auto">
        <div className="border-b border-rule px-3 pt-3.5 pb-3 min-[360px]:px-4">
          <p className="flex items-baseline gap-2 text-lg font-bold text-ai">
            買進 元大台灣50
            <span className="num text-sm font-normal">0050</span>
          </p>
          <p className="mt-0.5 text-sm text-ink-2">永豐・一般</p>
        </div>
        <dl className="grid grid-cols-2">
          <Cell label="股數" value="2,000 股" />
          <Cell label="成交價" value="52.40 元" right />
          <div className="col-span-2 flex items-center justify-between border-b border-rule px-3 py-3 min-[360px]:px-4">
            <dt className="font-bold text-ink">合計</dt>
            <dd className="num text-xl font-bold text-ai">{formatMoney(104_800)}</dd>
          </div>
        </dl>
        <div className="flex items-center gap-2.5 py-3 pr-3 pl-3 min-[360px]:pl-4">
          <span className="mr-auto inline-flex items-center gap-0.5 text-sm text-ai underline underline-offset-3">
            怎麼算的
            <ChevronDownIcon className="size-3.5" />
          </span>
          <span className="inline-flex h-9 items-center rounded-sm border border-ctl px-2.5 text-sm font-medium text-ink">修改</span>
          <span className="sign-box">
            <small className="text-xs font-normal opacity-85">簽名</small>
            確認入帳
          </span>
        </div>
      </div>
    </div>
  )
}

function Cell({ label, value, right }: { label: string; value: string; right?: boolean }) {
  return (
    // 很窄的手機（320px）上整張卡的左右留白收一點（12px）：「成交價 52.40 元」放得下一行，不會拆成兩行
    <div className={cn("flex items-baseline justify-between gap-2 border-b border-rule px-3 py-2.5 whitespace-nowrap min-[360px]:gap-3 min-[360px]:px-4", !right && "border-r")}>
      <dt className="text-sm text-ink-2">{label}</dt>
      <dd className="num text-base font-medium text-ai">{value}</dd>
    </div>
  )
}
