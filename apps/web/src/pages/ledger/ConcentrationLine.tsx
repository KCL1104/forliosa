import { useSummary } from "@/api/queries"
import { PlainLink } from "@/app/links"
import { overNote, topN } from "@/lib/allocation"
import { formatPercent } from "@/lib/format"

const pct = (w: number) => formatPercent(w, { signed: false, decimals: 1 })

/** 桌面的墨色細框小標（不用紅綠）；手機一行放不下，不放 */
function Tag({ children }: { children: React.ReactNode }) {
  return <span className="ml-1.5 hidden h-5 items-center rounded-xs border border-ink px-1 align-[1px] text-xs font-medium whitespace-nowrap text-ink lg:inline-flex">{children}</span>
}

/**
 * 持倉分段表頭上面的一行事實（產品負責人 2026-11-18，2A）：「最大一檔 台積電 39.6%・前 5 大 78.4%・最大產業 半導體業 56.3%・配置 →」。
 * 數字和「配置」分段、AI 面板同一份（`summary.concentration`）。手機一行放不下最大產業與「超過上限」小標；
 * 名稱太長時只截斷名稱（至少留 3 個字），360px 以下再拿掉「前 5 大」。
 * 桌面超過自己設的上限時多一個墨色小標：最大一檔本身超過才接在它後面；最大一檔是 ETF（不算個股）而別檔超過時，
 * 另外寫「1 檔超過上限」，不讓人以為是 ETF 超過。
 * 持股不到 2 檔、或舊的後端沒有這一份時不放。
 */
export function ConcentrationLine() {
  const c = useSummary().data?.concentration
  if (!c || c.holdings_count < 2 || !c.top_holding) return null
  const top = topN(c)
  const holdingOver = overNote(c, "holding")
  const industryOver = overNote(c, "industry")
  return (
    <p className="num -mt-1 mb-1 flex min-h-11 items-center gap-x-3 gap-y-0.5 text-md text-ink-2 lg:mb-1.5 lg:flex-wrap lg:gap-x-4">
      {/* 名稱太長時只截斷名稱，百分比一定印出來 */}
      <span className="flex min-w-0 items-baseline gap-x-1 whitespace-nowrap">
        <span className="shrink-0">最大一檔</span>{" "}
        <b className="min-w-[3em] truncate font-medium text-ink" title={c.top_holding.name}>
          {c.top_holding.name}
        </b>{" "}
        <b className="shrink-0 font-medium text-ink">{pct(c.top_holding.weight)}</b>
        {holdingOver?.onTop && <Tag>超過上限</Tag>}
      </span>
      {top && (
        <span className="shrink-0 whitespace-nowrap max-[360px]:hidden">
          前 {top.n} 大 <b className="font-medium text-ink">{pct(top.weight)}</b>
        </span>
      )}
      {c.top_industry && (
        <span className="whitespace-nowrap max-lg:hidden">
          最大產業 <b className="font-medium text-ink">{c.top_industry.label} {pct(c.top_industry.weight)}</b>
          {industryOver?.onTop && <Tag>超過上限</Tag>}
        </span>
      )}
      {holdingOver && !holdingOver.onTop && (
        <span className="max-lg:hidden">
          <Tag>{holdingOver.short}</Tag>
        </span>
      )}
      <PlainLink to="/" search={{ view: "allocation" }} className="ml-auto inline-flex min-h-11 shrink-0 items-center gap-1 whitespace-nowrap text-ink hover:underline" aria-label="看配置">
        配置 <span aria-hidden>→</span>
      </PlainLink>
    </p>
  )
}
