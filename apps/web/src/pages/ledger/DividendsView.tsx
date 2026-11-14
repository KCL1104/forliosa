import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { useMemo } from "react"
import { PlainLink } from "@/app/links"
import { appToday } from "@/api"
import { listTransactionsUpTo, useHoldings, useSummary, useUpcoming } from "@/api/queries"
import type { Transaction } from "@/api/types"
import { useUi } from "@/app/ui-store"
import { Masked, SourceTag } from "@/components/finance"
import { Section } from "@/components/section"
import { EmptyState, ErrorState } from "@/components/states"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { formatDateShort, formatDaysUntil, formatMoney, formatNumber, formatPerShare } from "@/lib/format"
import { codeOf, marketOf } from "@/lib/tick"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { useReadOnly, useWho } from "@/api/view-as"
import { DateCell } from "@/components/date-cell"
import { useSymbolNames } from "./use-symbol-names"

/** 整列可點：股票名稱連結的 ::after 蓋滿整列（和持倉的手機列同一招），列上其他可以按的東西用 `relative z-10` 浮在上面 */
const STRETCH = "after:absolute after:inset-0 after:content-[''] focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-ink"

/** 股利：接下來（除息、入帳、定期定額扣款）＋已入帳（依年份，已扣二代健保）。定期定額的計畫在設定頁管理 */
export function DividendsView() {
  const openTradeForm = useUi((s) => s.openTradeForm)
  // 台股股利在除息日自動入帳：只有美股要自己記。沒有美股就不放按鈕（2026-11-14 第七次評分）
  const usHeld = (useHoldings().data ?? []).filter((h) => h.market === "US")
  const readOnly = useReadOnly()
  const you = useWho("你")
  const summary = useSummary()
  const upcoming = useUpcoming(30)
  const privacy = usePrefs((s) => s.privacyMode)
  const received = useQuery({
    queryKey: ["transactions", "dividends"],
    queryFn: async () => {
      const [cash, stock] = await Promise.all([listTransactionsUpTo({ type: "cash_dividend" }, 600), listTransactionsUpTo({ type: "stock_dividend" }, 600)])
      return [...cash.items, ...stock.items].sort((a, b) => b.trade_date.localeCompare(a.trade_date))
    },
  })
  // 名稱：目前的持股＋出清過的（已經賣掉的股票領過的股利也有名稱）
  const nameOf = useSymbolNames()
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
          readOnly || usHeld.length === 0 ? undefined : (
            // 直接開完整表單、類型選「股利」（只有一檔美股時先選好），不產生對話
            <Button
              variant="outline"
              size="sm"
              className="pointer-coarse:h-11"
              onClick={() =>
                openTradeForm({
                  symbol: usHeld.length === 1 ? usHeld[0]!.code : undefined,
                  full: true,
                  prefill: { type: "cash_dividend", accountId: usHeld.length === 1 ? usHeld[0]!.account_ids[0] : undefined },
                })
              }
            >
              美股股利入帳
            </Button>
          )
        }
      >
        {upcoming.isLoading || summary.isLoading ? (
          <Skeleton className="h-24 w-full rounded-sm" />
        ) : upcoming.isError || summary.isError ? (
          // 讀不到不是「沒有事項」（2026-11-14 review）
          <ErrorState
            flush
            error={upcoming.error ?? summary.error}
            onRetry={() => {
              void upcoming.refetch()
              void summary.refetch()
            }}
          />
        ) : soon.length === 0 ? (
          <EmptyState className="-mt-3 border-t-0" title="接下來沒有事項" description={`${you}的持股接下來 60 天沒有除息，30 天內沒有股利入帳，也沒有定期定額扣款。`} />
        ) : (
          <div className="-mt-3">
            <div aria-hidden className="form-head grid h-10 grid-cols-[88px_1fr_auto] items-end gap-3 pb-2 md:grid-cols-[120px_1fr_auto]">
              <span>日期</span>
              <span>項目</span>
              <span className="text-right">金額</span>
            </div>
            <ul>
            {soon.map((u) => (
              <li key={`${u.date}-${u.type}-${u.title}`} className={cn("relative grid grid-cols-[88px_1fr_auto] items-center gap-3 py-3 md:grid-cols-[120px_1fr_auto]", u.symbol ? "ruled-row" : "border-b border-rule")}>
                <DateCell date={u.date} pad="-my-3 py-3" inline>
                  <span className="mt-0.5 text-sm font-normal text-ink-2">{formatDaysUntil(u.date, today)}</span>
                </DateCell>
                <span className="min-w-0">
                  {/* 名稱與類型：放不下時類型整個換到下一行（靠左，不縮排） */}
                  <span className="flex flex-wrap items-baseline gap-x-2">
                    {u.symbol ? (
                      <Link to="/stock/$symbol" params={{ symbol: u.symbol }} className={cn("font-medium", STRETCH)}>
                        {nameOf.get(u.symbol) ?? codeOf(u.symbol)}
                      </Link>
                    ) : null}
                    {u.type === "recurring" && readOnly ? (
                      // 查看模式：設定頁是查看者自己的（被擋下），不連過去
                      <span className="whitespace-nowrap text-ink-2">定期定額扣款</span>
                    ) : u.type === "recurring" ? (
                      // 第二個連結（到設定的定期定額）浮在整列的連結上面；觸控時可點範圍放大到 44px
                      <PlainLink
                        to="/settings"
                        hash="recurring"
                        className="relative z-10 whitespace-nowrap text-ink-2 underline decoration-ctl underline-offset-3 before:absolute before:-inset-x-2 before:-inset-y-3 before:content-[''] hover:text-ink hover:decoration-ink"
                      >
                        定期定額扣款
                      </PlainLink>
                    ) : (
                      <span className="whitespace-nowrap text-ink-2">{u.type === "ex_dividend" ? "除息" : "股利入帳"}</span>
                    )}
                  </span>
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
          </div>
        )}
      </Section>

      <Section title="已入帳" titleId="div-received" aside="已扣二代健保與預扣稅">
        {received.isError ? (
          <ErrorState error={received.error} onRetry={() => void received.refetch()} />
        ) : received.isLoading ? (
          <Skeleton className="h-40 w-full rounded-sm" />
        ) : byYear.length === 0 ? (
          <EmptyState
            className="-mt-3 border-t-0"
            title="還沒有股利紀錄"
            description={readOnly ? undefined : "台股股利會在除息日自動入帳；美股股利領到時跟 AI 說「AAPL 配息 2.6」就能入帳。"}
          />
        ) : (
          // 每一年是一張印好的表：年份與合計 → 表頭（雙線）→ 一列一筆
          <div className="flex flex-col gap-8">
            {byYear.map(([year, rows]) => {
              const netOf = (c: "TWD" | "USD") => rows.filter((t) => t.currency === c).reduce((s, t) => s + t.amount - t.tax - t.health_insurance, 0)
              const twd = netOf("TWD")
              const usd = netOf("USD")
              return (
                <section key={year} aria-label={`${year} 年`}>
                  <h3 className="flex flex-wrap items-baseline justify-between gap-x-3 pt-1 text-base font-bold">
                    {year} 年
                    <span className="num text-md font-normal text-ink-2">
                      合計 {money(Math.round(twd))}
                      {usd > 0 && <> ・ {privacy ? "••••" : formatMoney(usd, { currency: "USD" })}</>}
                    </span>
                  </h3>
                  <div aria-hidden className="form-head grid h-9 grid-cols-[88px_1fr_auto] items-end gap-3 pb-2 md:grid-cols-[120px_1fr_auto_auto]">
                    <span>日期</span>
                    <span>股票</span>
                    <span className="hidden text-right md:block">健保・預扣</span>
                    <span className="text-right">實收</span>
                  </div>
                  <ul>
                    {rows.map((t) => (
                      <li key={t.id} className={cn("relative grid min-h-11 grid-cols-[88px_1fr_auto] items-center gap-3 py-2.5 md:grid-cols-[120px_1fr_auto_auto]", t.symbol ? "ruled-row" : "border-b border-rule")}>
                        <DateCell date={t.trade_date} inline />
                        {/*
                          每股金額與來源標示一定看得到（不截斷、不縮）：放不下時整個換到名稱下面一行（靠左，和「接下來」同一招）；
                          名稱自己就超過一行時才截斷名稱
                        */}
                        <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                          {t.symbol && (
                            <span className="max-w-full min-w-0 truncate">
                              <Link to="/stock/$symbol" params={{ symbol: t.symbol }} className={cn("font-medium", STRETCH)}>
                                {nameOf.get(t.symbol) ?? codeOf(t.symbol)}
                              </Link>
                            </span>
                          )}
                          <span className="flex shrink-0 items-baseline gap-x-2">
                            {/* 每股金額帶幣別：台股「每股 5 元」，美股「每股 US$0.27」（不是「0.27 元」） */}
                            <span className="text-sm whitespace-nowrap text-ink-2">
                              {t.type === "stock_dividend" ? "股票股利" : t.price !== null ? `每股 ${formatPerShare(t.price, t.symbol ? marketOf(t.symbol) : "TWSE", { dividend: true })}` : "現金股利"}
                            </span>
                            {/* 標示浮在整列的連結上面：滑過仍然看得到說明 */}
                            <SourceTag source={t.source} className="relative z-10 shrink-0" />
                          </span>
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
