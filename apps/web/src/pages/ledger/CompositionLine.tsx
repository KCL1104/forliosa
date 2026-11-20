import { Masked } from "@/components/finance"
import type { Decomposition } from "@/lib/asset-composition"
import { direction, formatMoney, toneClass } from "@/lib/format"
import { cn } from "@/lib/utils"

/**
 * 總資產走勢下面的一句話（資產組成原型）：用圖上的說法（本金、賺的／虧的），股利另外說。
 * - 「全部」寫現在的組成：「總資產 NT$4,107,724＝本金 NT$2,960,000＋賺的 NT$1,147,724。另外領了股利 NT$221,484。」
 *   虧的時候「…＝本金 NT$2,400,000－虧的 NT$347,668。」
 * - 其他區間寫變化：「這段期間總資產多了 NT$503,212：本金多了 NT$400,000（買進），賺了 NT$103,212。」
 *   （本金少了 …（賣出）／本金沒有變；虧了 …）三個數字加得起來（`decompose`）。
 * 15px 墨色（要讀的句子）、關鍵數字 600；賺的、虧的是價格造成的，照漲跌色，方向用字說（賺／虧、＋／－）。
 * 本金與總資產的變化不是價格，不上色、方向用字說（多了／少了）。
 * 每一段 `whitespace-nowrap`：手機上放不下時在段落之間換行，不在金額中間斷。隱私模式金額都遮掉。
 */
export function CompositionLine({ d, privacy, className }: { d: Decomposition; privacy: boolean; className?: string }) {
  const money = (n: number) => (privacy ? <Masked className="text-ink" /> : <span className="num font-semibold">{formatMoney(n)}</span>)
  // 賺的／虧的：方向在字裡，金額不帶正負號，照漲跌色
  const pnl = (n: number) => (privacy ? <Masked className="text-ink" /> : <span className={cn("num font-semibold", toneClass(direction(n)))}>{formatMoney(Math.abs(n))}</span>)
  const part = (children: React.ReactNode) => <span className="whitespace-nowrap">{children}</span>
  const dividends = d.dividends > 0 && part(<>另外領了股利 {money(d.dividends)}。</>)
  if (d.kind === "levels") {
    return (
      <>
        <p className={cn("text-base text-ink", className)} data-composition-line>
          {part(<>總資產 {money(d.total)}＝</>)}
          {/* 本金照實帶正負號（formatMoney 的負號是「−」） */}
          {part(<>本金 {money(d.invested)}{d.profit < 0 ? "－" : "＋"}</>)}
          {part(<>{d.profit < 0 ? "虧的" : "賺的"} {pnl(d.profit)}。</>)}
          {dividends}
          {/* 賣股票收到的錢比買股票花的多：本金是負的，照實說一句（不然總資產＝本金＋賺的看起來對不起來） */}
          {d.invested < 0 && part(<>賣股票收到的錢已經比買股票花的多，所以本金是負的。</>)}
        </p>
        {/* 決定 5：app 不記現金，本金只算還在股票裡的錢——寫成現在的數字時說一次（淡墨小字，和資料說明同一層） */}
        <p className="mt-1 text-sm text-ink-2" data-composition-note>
          本金是買股票花的錢減掉賣股票收到的錢，只算還在股票裡的錢。
        </p>
      </>
    )
  }
  const total = d.total > 0 ? <>這段期間總資產多了 {money(d.total)}：</> : d.total < 0 ? <>這段期間總資產少了 {money(-d.total)}：</> : <>這段期間總資產沒有變：</>
  const flows = d.flows > 0 ? <>本金多了 {money(d.flows)}（買進），</> : d.flows < 0 ? <>本金少了 {money(-d.flows)}（賣出），</> : <>本金沒有變，</>
  const profit = d.profit > 0 ? <>賺了 {pnl(d.profit)}。</> : d.profit < 0 ? <>虧了 {pnl(d.profit)}。</> : <>沒賺也沒虧。</>
  return (
    <p className={cn("text-base text-ink", className)} data-composition-line>
      {part(total)}
      {part(flows)}
      {part(profit)}
      {dividends}
      {/* app 不記現金：賣出收到的錢不在總資產裡（本金少了時說一次） */}
      {d.flows < 0 && part(<>賣出收到的錢不算在總資產裡。</>)}
    </p>
  )
}
