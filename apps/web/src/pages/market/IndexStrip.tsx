import type { MarketIndex } from "@/api/types"
import { Pct } from "@/components/finance"
import { Sparkline } from "@/components/sparkline"
import { Tray, type TrayTint } from "@/components/tray"
import { direction, directionGlyph, formatDateShort, formatNumber, toneClass } from "@/lib/format"
import { cn } from "@/lib/utils"

/** 小數位：指數 2 位、期貨是整數點、匯率 3 位（央行公布到小數第三位） */
const DECIMALS: Record<MarketIndex["key"], number> = { taiex: 2, tpex: 2, tx: 0, usdtwd: 3 }

/**
 * 指數那一盤：加權、櫃買、（授權開了才有的）台指期近月、美元兌新台幣，照後端的順序。
 * 第一個（加權指數）是主角：名稱與日期、大字的數值（手機 32px、寬 40px，比例數字）、漲跌點數與幅度、走勢小圖；
 * 其他的是它旁邊（寬的時候）或下面（窄的時候）的兩行列——名稱・日期｜小圖｜數值・漲跌，和持倉表同一種。
 * 每一個都帶自己的日期：上市、上櫃、匯率公布的時間不一樣。走勢小圖是最近 20 個收盤（墨色，不跟著當天漲跌換色）；
 * 不到兩點就不畫。這些不是連結（沒有指數頁）。`note` 是加權指數還沒更新時預計幾點更新的那一行，放在托盤最下面。
 * 一盤裝全部：主角與其他各自一盤的話，手機上「其他」那一盤、收盤重點、類股三盤相鄰，三種底色排不開（見 DESIGN.md〈市場頁〉）。
 */
export function IndexStrip({ indices, tint, note, className }: { indices: MarketIndex[]; tint?: TrayTint; note?: React.ReactNode; className?: string }) {
  const [lead, ...rest] = indices
  if (!lead) return null
  return (
    <Tray title="指數與匯率" titleHidden tint={tint} className={className} bodyClassName="@container">
      <ul
        aria-label="指數與匯率"
        style={{ "--rows": Math.max(rest.length, 1) } as React.CSSProperties}
        className={cn("grid grid-cols-1", rest.length > 0 && "@3xl:grid-cols-[minmax(0,1fr)_minmax(20rem,26rem)] @3xl:gap-x-6")}
      >
        <LeadIndex index={lead} beside={rest.length > 0} />
        {rest.map((i) => (
          <IndexRow key={i.key} index={i} />
        ))}
      </ul>
      {note}
    </Tray>
  )
}

function Change({ index: i, decimals, className }: { index: MarketIndex; decimals: number; className?: string }) {
  const d = direction(i.change)
  return (
    <p className={cn("flex items-baseline gap-2", className)}>
      {i.change !== null && (
        <span className={cn("num whitespace-nowrap", toneClass(d))}>
          {d !== "flat" && <span aria-hidden>{directionGlyph(d)}</span>}
          {formatNumber(Math.abs(i.change), decimals)}
        </span>
      )}
      <Pct value={i.change_pct} />
    </p>
  )
}

/** 主角：寬的時候佔左邊、高度跟著右邊的列，右緣一條格線；窄的時候在最上面，下面一條格線 */
function LeadIndex({ index: i, beside }: { index: MarketIndex; beside: boolean }) {
  const decimals = DECIMALS[i.key] ?? 2
  const values = i.sparkline.map((p) => p.v).filter((v): v is number => v !== null)
  const label = `${i.name}最近 ${values.length} 個交易日的收盤`
  return (
    <li
      className={cn(
        "flex min-w-0 flex-col",
        beside && "border-b border-rule pb-4 @3xl:row-span-(--rows) @3xl:border-r @3xl:border-b-0 @3xl:pr-6 @3xl:pb-0",
      )}
    >
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
        <p className="print-label text-base">{i.name}</p>
        <p className="num text-sm text-ink-2">{formatDateShort(i.date, false)}</p>
      </div>
      <div className="mt-1 flex min-w-0 items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="hero-figure text-[2rem] leading-10 font-medium whitespace-nowrap @3xl:text-[2.5rem] @3xl:leading-12">
            {i.value === null ? "—" : formatNumber(i.value, decimals)}
            <span className="sr-only"> {i.unit}</span>
          </p>
          <Change index={i} decimals={decimals} className="text-lg leading-6" />
        </div>
        {values.length >= 2 && (
          <>
            <Sparkline className="mb-1 @md:hidden" width={76} height={36} values={values} tone="ink" label={label} />
            <Sparkline className="mb-1 hidden @md:block" width={220} height={56} values={values} tone="ink" label={label} />
          </>
        )}
      </div>
    </li>
  )
}

/** 其他指數：兩行列（名稱・日期｜小圖｜數值・漲跌）。很窄的托盤（< 320px，320px 的手機）不放漲跌點數，第三欄照內容寬 */
function IndexRow({ index: i }: { index: MarketIndex }) {
  const decimals = DECIMALS[i.key] ?? 2
  const values = i.sparkline.map((p) => p.v).filter((v): v is number => v !== null)
  const d = direction(i.change)
  return (
    <li className="grid min-h-[72px] grid-cols-[minmax(0,1fr)_64px_auto] content-center items-center gap-x-3 border-b border-rule py-2 last:border-b-0 @xs:grid-cols-[minmax(0,1fr)_64px_7.5rem] @3xl:col-start-2">
      <div className="min-w-0">
        <p className="print-label text-lg leading-6 [overflow-wrap:anywhere]">{i.name}</p>
        <p className="num text-sm leading-5 text-ink-2">{formatDateShort(i.date, false)}</p>
      </div>
      {values.length >= 2 ? (
        <Sparkline width={64} height={32} values={values} tone="ink" label={`${i.name}最近 ${values.length} 個交易日的收盤`} />
      ) : (
        <span aria-hidden />
      )}
      <div className="text-right">
        <p className="num text-lg leading-6">
          {i.value === null ? "—" : formatNumber(i.value, decimals)}
          <span className="sr-only"> {i.unit}</span>
        </p>
        <p className="flex items-baseline justify-end gap-2 text-base leading-5">
          {i.change !== null && (
            <span className={cn("num whitespace-nowrap @max-xs:hidden", toneClass(d))}>
              {d !== "flat" && <span aria-hidden>{directionGlyph(d)}</span>}
              {formatNumber(Math.abs(i.change), decimals)}
            </span>
          )}
          <Pct value={i.change_pct} />
        </p>
      </div>
    </li>
  )
}
