import type { InstrumentType, Market } from "@/api/types"
import { formatPrice } from "@/lib/format"
import { limitTrack, type LimitTrackInput } from "@/lib/limit-track"
import { cn } from "@/lib/utils"

/**
 * 漲跌停軌道（產品負責人 2026-11-21 選方向 C 的結構）：跌停—參考價—漲停一條 1px 的尺，收盤是墨色實心點，
 * 當天的最低到最高畫成一段淡墨的範圍、範圍的數字寫在它下面。只有台股（美股沒有漲跌停，由呼叫端不放）。
 *
 * 顏色不代表意思：點、範圍、刻度都是墨色與控制項的框色，不用紅綠——方向看位置（參考價左邊是跌、右邊是漲），
 * 收在漲停或跌停由價格旁的「漲停／跌停」標記說。標籤只有名詞與數字，沒有說明句。
 *
 * 標籤的位置：收盤與範圍的標籤用「自己的 p% 對齊尺的 p%」（`left: p%` ＋ `translateX(-p%)`），
 * 在兩端時自動往內靠、任何寬度都不超出托盤；跌停、參考價、漲停三個固定標籤排成三欄（參考價永遠在正中間附近：
 * 漲跌停是參考價的 ±10%）。圖是 aria-hidden，同樣的事實另外寫成一句給螢幕閱讀器。
 * 資料對不起來（`limitTrack` 回 null）時整個不畫。
 */
export function LimitTrack({
  close,
  reference,
  up,
  down,
  low,
  high,
  market,
  type,
  className,
}: LimitTrackInput & { market: Market; type: InstrumentType; className?: string }) {
  const g = limitTrack({ close, reference, up, down, low, high })
  if (!g) return null
  const p = (n: number) => formatPrice(n, market, type)
  const pct = (x: number) => `${+(x * 100).toFixed(3)}%`
  // 標籤自己的 x% 對齊尺的 x%：在左端靠左、右端靠右、中間置中，不會超出
  const follow = (x: number) => ({ left: pct(x), transform: `translateX(-${pct(x)})` })
  const band = g.band
  const range = band && low != null && high != null ? (low === high ? `最低＝最高 ${p(low)}` : `最低 ${p(low)}・最高 ${p(high)}`) : null
  return (
    <div className={cn("min-w-0", className)} data-limit-track="">
      <div aria-hidden className={cn("relative select-none", range ? "h-[60px]" : "h-[38px]")}>
        {/* 收盤的標籤 */}
        <span data-close-label="" className="num absolute top-0 text-sm font-medium whitespace-nowrap text-ink" style={follow(g.close)}>
          收 {p(close)}
        </span>
        {/* 尺：1px 線、兩端與參考價的刻度（參考價的刻度長一點） */}
        <span className="absolute inset-x-0 top-[29px] h-px bg-ctl" />
        <span className="absolute top-[25px] left-0 h-[9px] w-px bg-ctl" />
        <span className="absolute top-[25px] right-0 h-[9px] w-px bg-ctl" />
        <span data-ref-tick="" className="absolute top-[22px] h-[15px] w-px -translate-x-1/2 bg-ink-2" style={{ left: pct(g.reference) }} />
        {/* 當天的範圍：淡墨，最少 3px（一字漲停的那種一天也看得到） */}
        {band && (
          <span
            data-band=""
            className="absolute top-[26px] h-[7px] w-[max(3px,var(--w))] rounded-xs bg-ink/20"
            style={{ left: `min(${pct(band.from)}, calc(100% - 3px))`, "--w": pct(band.to - band.from) } as React.CSSProperties}
          />
        )}
        {/* 收盤：墨色實心點＋紙色外圈（和估值尺的「現在」同一種點） */}
        <span data-close="" className="absolute top-[29.5px] size-[11px] -translate-1/2 rounded-full bg-ink ring-2 ring-paper" style={{ left: pct(g.close) }} />
        {range && (
          <span data-band-label="" className="num absolute top-[40px] text-sm whitespace-nowrap text-ink-2" style={follow((band!.from + band!.to) / 2)}>
            {range}
          </span>
        )}
      </div>
      {/* 三個固定的標籤：夠寬（≥ 20rem，393px 的手機以上）時標籤和數字同一行；320px 的手機上標籤在數字上面 */}
      <dl className="mt-1.5 grid grid-cols-3 gap-x-2 @container">
        {(
          [
            ["跌停", down, ""],
            ["參考價", reference, "text-center"],
            ["漲停", up, "text-right"],
          ] as const
        ).map(([label, value, align]) => (
          <div key={label} className={cn("min-w-0", align)}>
            <dt className="print-label inline text-sm @max-[20rem]:block">{label}</dt>
            <dd className="num ml-1.5 inline text-base whitespace-nowrap text-ink @max-[20rem]:ml-0 @max-[20rem]:block">{p(value)}</dd>
          </div>
        ))}
      </dl>
      <p className="sr-only">
        收盤 {p(close)}
        {g.at === "up" ? "，漲停" : g.at === "down" ? "，跌停" : ""}
        {range ? `；${range}` : ""}。
      </p>
    </div>
  )
}
