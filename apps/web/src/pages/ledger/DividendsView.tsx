import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { CoinsIcon } from "lucide-react"
import { useMemo } from "react"
import { appToday } from "@/api"
import { listTransactionsUpTo, useHoldings, useSummary, useUpcoming } from "@/api/queries"
import type { Transaction } from "@/api/types"
import { useAskAi } from "@/ai/use-ask"
import { Masked, SourceTag } from "@/components/finance"
import { Section } from "@/components/section"
import { ErrorState } from "@/components/states"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { formatDateShort, formatDaysUntil, formatMoney, formatNumber } from "@/lib/format"
import { codeOf } from "@/lib/tick"
import { usePrefs } from "@/stores/prefs"
import { useReadOnly } from "@/api/view-as"

/** 股利：接下來（除息、入帳、定期定額扣款）＋已入帳（依年份，已扣二代健保）。定期定額的計畫在設定頁管理 */
export function DividendsView() {
  const ask = useAskAi()
  const readOnly = useReadOnly()
  const summary = useSummary()
  const upcoming = useUpcoming(30)
  const holdings = useHoldings()
  const privacy = usePrefs((s) => s.privacyMode)
  const received = useQuery({
    queryKey: ["transactions", "dividends"],
    queryFn: async () => {
      const [cash, stock] = await Promise.all([listTransactionsUpTo({ type: "cash_dividend" }, 600), listTransactionsUpTo({ type: "stock_dividend" }, 600)])
      return [...cash.items, ...stock.items].sort((a, b) => b.trade_date.localeCompare(a.trade_date))
    },
  })
  const nameOf = useMemo(() => new Map((holdings.data ?? []).map((h) => [h.symbol, h.name])), [holdings.data])
  const byYear = useMemo(() => {
    const map = new Map<string, Transaction[]>()
    for (const t of received.data ?? []) {
      const y = t.trade_date.slice(0, 4)
      map.set(y, [...(map.get(y) ?? []), t])
    }
    return [...map.entries()]
  }, [received.data])
  const today = appToday()
  const money = (n: number, signed = false) => (privacy ? <Masked /> : formatMoney(n, { signed }))

  // 「接下來」：本週事項（含入帳、定期定額）＋ 60 天內除息
  const soon = [
    ...(upcoming.data ?? []),
    ...(summary.data?.upcoming_dividends ?? [])
      .filter((d) => !(upcoming.data ?? []).some((u) => u.type === "ex_dividend" && u.symbol === d.symbol && u.date === d.ex_dividend_date))
      .map((d) => ({ date: d.ex_dividend_date, type: "ex_dividend" as const, symbol: d.symbol, title: `${codeOf(d.symbol)} 除息`, amount_estimate: d.estimated_amount })),
  ].sort((a, b) => a.date.localeCompare(b.date))

  return (
    <div className="flex flex-col gap-10">
      <Section
        title="接下來"
        titleId="div-next"
        action={
          readOnly ? undefined : (
            <Button variant="outline" size="sm" onClick={() => ask.action("dividend")}>
              <CoinsIcon />
              股利入帳
            </Button>
          )
        }
      >
        {upcoming.isLoading || summary.isLoading ? (
          <Skeleton className="h-24 w-full rounded-sm" />
        ) : soon.length === 0 ? (
          <p className="py-2 text-md text-ink-2">接下來 60 天你的持股沒有除息、待入帳的股利，也沒有定期定額扣款。</p>
        ) : (
          <ul className="-mt-3">
            {soon.map((u) => (
              <li key={`${u.date}-${u.type}-${u.title}`} className="grid grid-cols-[88px_1fr_auto] items-baseline gap-3 border-b border-rule py-3 md:grid-cols-[120px_1fr_auto]">
                <span className="num text-ink">
                  {formatDateShort(u.date)}
                  <span className="block text-sm text-ink-2">{formatDaysUntil(u.date, today)}</span>
                </span>
                <span className="min-w-0">
                  {u.symbol ? (
                    <Link to="/stock/$symbol" params={{ symbol: u.symbol }} className="font-medium hover:underline">
                      {nameOf.get(u.symbol) ?? codeOf(u.symbol)}
                    </Link>
                  ) : null}
                  {u.type === "recurring" ? (
                    <Link to="/settings" hash="recurring" className="ml-2 text-ink-2 underline-offset-3 hover:text-ink hover:underline">
                      定期定額扣款
                    </Link>
                  ) : (
                    <span className="ml-2 text-ink-2">{u.type === "ex_dividend" ? "除息" : "股利入帳"}</span>
                  )}
                  {"scheduled_date" in u && u.scheduled_date && u.scheduled_date !== u.date && (
                    <span className="block text-sm text-ink-2">原訂 {formatDateShort(u.scheduled_date, false)}，遇休市順延</span>
                  )}
                </span>
                <span className="num text-right">
                  {u.amount_estimate === null ? "—" : u.type === "recurring" ? money(u.amount_estimate) : money(u.amount_estimate, true)}
                  <span className="block text-sm text-ink-2">{u.type === "recurring" ? "扣款" : "預估"}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="已入帳" titleId="div-received" aside="已扣二代健保與預扣稅">
        {received.isError ? (
          <ErrorState error={received.error} onRetry={() => void received.refetch()} />
        ) : received.isLoading ? (
          <Skeleton className="h-40 w-full rounded-sm" />
        ) : byYear.length === 0 ? (
          <p className="py-2 text-md text-ink-2">還沒有股利紀錄。台股股利會在除息日自動入帳；美股股利領到時跟 AI 說「AAPL 配息 2.6」就能入帳。</p>
        ) : (
          <div className="-mt-3 flex flex-col">
            <p className="pt-3 text-sm text-ink-2">台股股利在除息日自動入帳，美股股利要自己記。</p>
            {byYear.map(([year, rows]) => {
              const netOf = (c: "TWD" | "USD") => rows.filter((t) => t.currency === c).reduce((s, t) => s + t.amount - t.tax - t.health_insurance, 0)
              const twd = netOf("TWD")
              const usd = netOf("USD")
              return (
                <section key={year} aria-label={`${year} 年`} className="mt-3">
                  <h3 className="flex items-baseline justify-between border-b border-rule pt-3 pb-2 text-base font-bold">
                    {year} 年
                    <span className="num text-md font-normal text-ink-2">
                      合計 {money(Math.round(twd))}
                      {usd > 0 && <> ・ {privacy ? "••••" : formatMoney(usd, { currency: "USD" })}</>}
                    </span>
                  </h3>
                  <ul>
                    {rows.map((t) => (
                      <li key={t.id} className="grid grid-cols-[88px_1fr_auto] items-baseline gap-3 border-b border-rule py-2.5 md:grid-cols-[120px_1fr_auto_auto]">
                        <span className="num text-ink-2">{formatDateShort(t.trade_date)}</span>
                        {/* 名稱太長時截斷名稱與每股金額，來源標示一定看得到 */}
                        <span className="flex min-w-0 items-baseline">
                          <span className="min-w-0 truncate">
                            {t.symbol && (
                              <Link to="/stock/$symbol" params={{ symbol: t.symbol }} className="font-medium hover:underline">
                                {nameOf.get(t.symbol) ?? codeOf(t.symbol)}
                              </Link>
                            )}
                            <span className="ml-2 text-sm text-ink-2">{t.type === "stock_dividend" ? "股票股利" : t.price !== null ? `每股 ${t.price} 元` : "現金股利"}</span>
                          </span>
                          <SourceTag source={t.source} className="ml-2 shrink-0" />
                        </span>
                        <span className="num hidden text-right text-sm text-ink-2 md:block">
                          {t.health_insurance > 0 ? <>健保 {privacy ? "••••" : formatNumber(t.health_insurance)}</> : t.tax > 0 ? <>預扣 {privacy ? "••••" : formatNumber(t.tax, t.currency === "USD" ? 2 : 0)}</> : ""}
                        </span>
                        <span className="num text-right">{privacy ? <Masked /> : formatMoney(t.amount - t.tax - t.health_insurance, { currency: t.currency })}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )
            })}
          </div>
        )}
      </Section>
    </div>
  )
}
