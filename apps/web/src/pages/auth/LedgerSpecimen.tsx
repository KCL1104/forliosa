import { DemoTag } from "@/components/section"
import { direction, directionGlyph, formatMoney, formatPercent, toneClass } from "@/lib/format"
import { cn } from "@/lib/utils"

/**
 * 登入頁的示範畫面：用示範資料畫的帳本（主數字＋持倉的前幾列），讓還沒登入的人看得到登入之後是什麼。
 * 和帳本頁同一套字級、格線與漲跌色（手機版的排法），數字和 mock 的示範帳本相同；不是截圖，所以跟著淺色／深色、
 * 也不會糊。畫面上沒有日期（寫死的日期過幾個月會像壞掉的資料），也沒有可以按的東西。
 * 內容對螢幕報讀器隱藏（一串假數字沒有意義），改讀一句說明。
 */
const TOTAL = 3_707_922
const DAY = { amount: 78_015, pct: 0.0215 }
const PNL = { amount: 1_005_572, pct: 0.354 }
const ROWS: { name: string; code: string; qty: string; price: string; pct: number }[] = [
  { name: "台積電", code: "2330", qty: "1 張 500 股", price: "1,085", pct: 0.0483 },
  { name: "鴻海", code: "2317", qty: "2 張", price: "236.5", pct: 0.0238 },
  { name: "元大台灣50", code: "0050", qty: "5 張 779 股", price: "72.40", pct: 0.0077 },
  { name: "環球晶", code: "6488", qty: "1 張", price: "398", pct: -0.0185 },
  { name: "國泰永續高股息", code: "00878", qty: "13 張 260 股", price: "22.86", pct: -0.0022 },
]

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

export function LedgerSpecimen({ className }: { className?: string }) {
  return (
    <figure className={cn("min-w-0", className)}>
      <figcaption className="sr-only">
        示範畫面：登入後的帳本。上面是總資產、今日漲跌與總損益，下面一列一檔持股，寫著股數、收盤價與當天漲跌。數字是示範資料。
      </figcaption>
      <div aria-hidden>
        <p className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm text-ink-2">
          <b className="text-base font-medium text-ink">總資產</b>
          <DemoTag />
        </p>
        <p className="hero-figure mt-1 flex items-baseline text-4xl font-medium tracking-[-0.015em] text-ink">
          <span className="mr-1.5 text-lg font-normal tracking-normal text-ink-2">NT$</span>
          <span className="num">{formatMoney(TOTAL, { bare: true })}</span>
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

        <div className="form-head mt-7 flex items-center justify-between gap-3 pb-2">
          <span>持有 9 檔</span>
          <span>收盤價・今日漲跌</span>
        </div>
        <ul>
          {ROWS.map((r) => {
            const d = direction(r.pct)
            return (
              <li key={r.code} className="flex items-center justify-between gap-4 border-b border-rule py-3">
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
      </div>
    </figure>
  )
}
