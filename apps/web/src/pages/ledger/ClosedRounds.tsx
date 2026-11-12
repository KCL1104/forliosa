import { Link, useNavigate } from "@tanstack/react-router"
import { ChevronDownIcon } from "lucide-react"
import { useAccounts, useClosedPositions } from "@/api/queries"
import type { Account, ClosedRound } from "@/api/types"
import { Masked, Pct } from "@/components/finance"
import { ErrorState } from "@/components/states"
import { direction, directionGlyph, formatMoney, toneClass } from "@/lib/format"
import { closedTotals, holdingPeriod } from "@/lib/ledger-display"
import { codeOf } from "@/lib/tick"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { useLedgerPrefs } from "./ledger-prefs"

/**
 * 已出清：持倉底下一個安靜、預設收合的區塊。出清的股票不在持股裡，回合紀錄留在這裡。
 * 桌面一張格線表（名稱・持有期間・已實現損益・領過股利・手續費與稅），手機三行列。點一列到個股頁的「過去的持有」。
 */
export function ClosedRounds() {
  const closed = useClosedPositions()
  const accounts = useAccounts()
  const open = useLedgerPrefs((s) => s.showClosed)
  const setOpen = useLedgerPrefs((s) => s.setShowClosed)
  const privacy = usePrefs((s) => s.privacyMode)
  const rounds = closed.data ?? []
  if (closed.isError) return <ErrorState className="mt-9" title="出清紀錄沒有載入" error={closed.error} onRetry={() => void closed.refetch()} />
  if (rounds.length === 0) return null
  const totals = closedTotals(rounds)
  const multiAccount = (accounts.data?.length ?? 0) > 1
  const d = direction(totals.realized)
  return (
    <section aria-labelledby="closed-title" className="mt-9">
      <h2 id="closed-title" className="m-0">
        <button
          type="button"
          aria-expanded={open}
          aria-controls="closed-list"
          onClick={() => setOpen(!open)}
          className="flex min-h-[52px] w-full items-end gap-2 border-b border-rule pb-2 text-left hover:text-ink"
        >
          <span className="text-lg font-bold md:text-base">已出清</span>
          <span className="num text-sm font-normal text-ink-2">
            {totals.symbols} 檔{rounds.length > totals.symbols && `・${rounds.length} 回合`}
          </span>
          <span className="num ml-auto text-sm font-normal text-ink-2">
            已實現
            <span className={cn("ml-1.5", toneClass(d))}>
              {d !== "flat" && <span aria-hidden className="mr-0.5 text-[0.8em]">{directionGlyph(d)}</span>}
              {privacy ? <Masked /> : formatMoney(totals.realized, { signed: true })}
              <span className="sr-only">{d === "up" ? "獲利" : d === "down" ? "虧損" : ""}</span>
            </span>
          </span>
          <ChevronDownIcon aria-hidden className={cn("mb-0.5 size-[18px] shrink-0 text-ink-2 transition-transform duration-200", open && "rotate-180")} />
        </button>
      </h2>
      {open && (
        <div id="closed-list" className="note-in">
          <ClosedTable rounds={rounds} accounts={accounts.data ?? []} multiAccount={multiAccount} />
          <ClosedList rounds={rounds} accounts={accounts.data ?? []} multiAccount={multiAccount} />
          <p className="mt-2 text-xs text-ink-2">已實現損益扣除買賣手續費與證交稅；股利已扣二代健保，出清後才入帳的股利算在最近一個回合。</p>
        </div>
      )}
    </section>
  )
}

function accountName(accounts: Account[], id: string) {
  return accounts.find((a) => a.id === id)?.name ?? ""
}

function RealizedCell({ r }: { r: ClosedRound }) {
  const privacy = usePrefs((s) => s.privacyMode)
  return (
    <span className="inline-flex items-baseline gap-2">
      <span className={toneClass(direction(r.realized_pnl))}>{privacy ? <Masked /> : formatMoney(r.realized_pnl, { signed: true })}</span>
      <Pct value={r.realized_pnl_pct} className="text-md" />
    </span>
  )
}

function ClosedTable({ rounds, accounts, multiAccount }: { rounds: ClosedRound[]; accounts: Account[]; multiAccount: boolean }) {
  const navigate = useNavigate()
  const privacy = usePrefs((s) => s.privacyMode)
  const money = (n: number) => (privacy ? <Masked /> : formatMoney(n, { bare: true }))
  const th = "h-10 border-b border-rule text-sm font-normal text-ink-2"
  return (
    <table className="w-full border-collapse max-md:hidden" aria-label="已出清">
      <thead>
        <tr>
          <th scope="col" className={cn(th, "text-left")}>名稱</th>
          <th scope="col" className={cn(th, "text-left")}>持有期間</th>
          <th scope="col" className={cn(th, "w-[220px] text-right")}>已實現損益</th>
          <th scope="col" className={cn(th, "w-[120px] text-right")}>領過股利</th>
          <th scope="col" className={cn(th, "w-[120px] text-right")}>手續費與稅</th>
        </tr>
      </thead>
      <tbody>
        {rounds.map((r) => {
          const period = holdingPeriod(r)
          return (
            <tr key={`${r.account_id}-${r.symbol}-${r.opened_at}`} className="ruled-row cursor-pointer" onClick={() => void navigate({ to: "/stock/$symbol", params: { symbol: r.symbol } })}>
              <th scope="row" className="h-[60px] py-1.5 pr-3 text-left font-normal">
                <Link to="/stock/$symbol" params={{ symbol: r.symbol }} className="group block rounded-sm" onClick={(e) => e.stopPropagation()}>
                  <span className="block text-lg leading-snug font-medium group-hover:underline">{r.name}</span>
                  <span className="num block text-sm text-ink-2">
                    {codeOf(r.symbol)}
                    {multiAccount && ` ・ ${accountName(accounts, r.account_id)}`}
                  </span>
                </Link>
              </th>
              <td className="num py-1.5 pr-3">
                <span className="block text-base leading-snug">{period.range}</span>
                <span className="block text-sm text-ink-2">{period.days}</span>
              </td>
              <td className="num text-right text-lg whitespace-nowrap">
                <RealizedCell r={r} />
              </td>
              <td className="num text-right text-lg whitespace-nowrap">{r.dividends_received ? money(r.dividends_received) : <span className="text-ink-2">—</span>}</td>
              <td className="num text-right text-lg whitespace-nowrap text-ink-2">{money(r.fees_and_taxes)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function ClosedList({ rounds, accounts, multiAccount }: { rounds: ClosedRound[]; accounts: Account[]; multiAccount: boolean }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const money = (n: number) => (privacy ? "••••" : formatMoney(n))
  return (
    <ul className="md:hidden" aria-label="已出清">
      {rounds.map((r) => {
        const period = holdingPeriod(r)
        return (
          <li key={`${r.account_id}-${r.symbol}-${r.opened_at}`}>
            <Link to="/stock/$symbol" params={{ symbol: r.symbol }} className="ruled-row grid grid-cols-[1fr_auto] content-center gap-x-3 gap-y-0.5 py-3">
              <span className="truncate text-lg leading-6 font-medium">{r.name}</span>
              <span className={cn("num text-right text-lg leading-6", toneClass(direction(r.realized_pnl)))}>{privacy ? <Masked /> : formatMoney(r.realized_pnl, { signed: true })}</span>
              <span className="num text-sm leading-5 text-ink-2">
                {codeOf(r.symbol)} ・ {period.days}
                {multiAccount && ` ・ ${accountName(accounts, r.account_id)}`}
              </span>
              <span className="text-right text-base leading-5">
                <Pct value={r.realized_pnl_pct} />
              </span>
              <span className="num col-span-2 mt-0.5 text-sm leading-5 text-ink-2">
                <span className="whitespace-nowrap">{period.range}</span>
                <span className="whitespace-nowrap">・股利 {r.dividends_received ? money(r.dividends_received) : "—"}</span>
                <span className="whitespace-nowrap">・手續費與稅 {money(r.fees_and_taxes)}</span>
              </span>
            </Link>
          </li>
        )
      })}
    </ul>
  )
}
