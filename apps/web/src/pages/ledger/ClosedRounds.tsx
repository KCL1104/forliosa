import { Link, useNavigate } from "@tanstack/react-router"
import { ChevronDownIcon } from "lucide-react"
import { useState } from "react"
import { useAccounts, useClosedPositions } from "@/api/queries"
import type { Account, ClosedRound } from "@/api/types"
import { Masked, Pct } from "@/components/finance"
import { ErrorState } from "@/components/states"
import { direction, formatMoney, toneClass } from "@/lib/format"
import { closedByYear, closedTotals, holdingPeriod, type ClosedYear } from "@/lib/ledger-display"
import { codeOf } from "@/lib/tick"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { useLedgerPrefs } from "./ledger-prefs"

/**
 * 已出清：持倉底下一個安靜、預設收合的區塊。出清的股票不在持股裡，回合紀錄留在這裡。
 * 依出清年份分組（新的年份在前），每一年可以收合、有當年已實現損益小計（金額用 +／−，不加 ▲▼）；預設只展開最近一年。
 * 桌面一張格線表（名稱・持有期間・已實現損益・領過股利・手續費與稅，每一年一個 tbody），手機三行列。點一列到個股頁的「過去的持有」。
 */
export function ClosedRounds() {
  const closed = useClosedPositions()
  const accounts = useAccounts()
  const open = useLedgerPrefs((s) => s.showClosed)
  const setOpen = useLedgerPrefs((s) => s.setShowClosed)
  const privacy = usePrefs((s) => s.privacyMode)
  // 年份的收合：只記使用者動過的；沒動過時最近一年展開、其他收合
  const [toggled, setToggled] = useState<Record<string, boolean>>({})
  const rounds = closed.data ?? []
  if (closed.isError) return <ErrorState className="mt-9" title="出清紀錄沒有載入" error={closed.error} onRetry={() => void closed.refetch()} />
  if (rounds.length === 0) return null
  const totals = closedTotals(rounds)
  const years = closedByYear(rounds)
  const yearOpen = (y: string) => toggled[y] ?? y === years[0]?.year
  const toggleYear = (y: string) => setToggled((t) => ({ ...t, [y]: !yearOpen(y) }))
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
          className="flex min-h-[52px] w-full items-end gap-2 border-b border-print pb-2 text-left hover:text-ink"
        >
          <span className="text-lg font-bold md:text-base">已出清</span>
          <span className="num text-sm font-normal text-ink-2">
            {totals.symbols} 檔{rounds.length > totals.symbols && `・${rounds.length} 回合`}
          </span>
          <span className="num ml-auto text-sm font-normal text-ink-2">
            已實現
            <span className={cn("ml-1.5", toneClass(d))}>
              {privacy ? <Masked /> : formatMoney(totals.realized, { signed: true })}
              <span className="sr-only">{d === "up" ? "獲利" : d === "down" ? "虧損" : ""}</span>
            </span>
          </span>
          <ChevronDownIcon aria-hidden className={cn("mb-0.5 size-[18px] shrink-0 text-ink-2 transition-transform duration-200", open && "rotate-180")} />
        </button>
      </h2>
      {open && (
        <div id="closed-list" className="note-in">
          <ClosedTable years={years} isOpen={yearOpen} onToggle={toggleYear} accounts={accounts.data ?? []} multiAccount={multiAccount} />
          <ClosedList years={years} isOpen={yearOpen} onToggle={toggleYear} accounts={accounts.data ?? []} multiAccount={multiAccount} />
          <p className="mt-2 text-sm text-ink-2">已實現損益扣除買賣手續費與證交稅；股利已扣二代健保，出清後才入帳的股利算在最近一個回合。</p>
        </div>
      )}
    </section>
  )
}

function accountName(accounts: Account[], id: string) {
  return accounts.find((a) => a.id === id)?.name ?? ""
}

/** 一年的已實現小計：漲跌色＋正負號（金額不加 ▲▼；螢幕閱讀器讀「獲利／虧損」），隱私模式遮蔽 */
function YearTotal({ value, className }: { value: number; className?: string }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const d = direction(value)
  return (
    <span className={cn("num whitespace-nowrap", toneClass(d), className)}>
      {privacy ? <Masked /> : formatMoney(value, { signed: true })}
      <span className="sr-only">{d === "up" ? "獲利" : d === "down" ? "虧損" : ""}</span>
    </span>
  )
}

function yearCount(y: ClosedYear) {
  return `${y.symbols} 檔${y.rounds.length > y.symbols ? `・${y.rounds.length} 回合` : ""}`
}

interface YearProps {
  years: ClosedYear[]
  isOpen: (year: string) => boolean
  onToggle: (year: string) => void
  accounts: Account[]
  multiAccount: boolean
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

function ClosedTable({ years, isOpen, onToggle, accounts, multiAccount }: YearProps) {
  const navigate = useNavigate()
  const privacy = usePrefs((s) => s.privacyMode)
  const money = (n: number) => (privacy ? <Masked /> : formatMoney(n, { bare: true }))
  const th = "h-10"
  return (
    <table className="w-full border-collapse max-md:hidden" aria-label="已出清">
      <thead className="form-head">
        <tr>
          <th scope="col" className={cn(th, "text-left")}>名稱</th>
          <th scope="col" className={cn(th, "text-left")}>持有期間</th>
          <th scope="col" className={cn(th, "w-[220px] text-right")}>已實現損益</th>
          <th scope="col" className={cn(th, "w-[120px] text-right")}>領過股利</th>
          <th scope="col" className={cn(th, "w-[120px] text-right")}>手續費與稅</th>
        </tr>
      </thead>
      {years.map((y) => {
        const open = isOpen(y.year)
        return (
          <tbody key={y.year}>
            {/* 年份列：整列可點（滑鼠），鍵盤用年份按鈕；小計對齊「已實現損益」欄 */}
            <tr className="group/year cursor-pointer" onClick={() => onToggle(y.year)}>
              <th scope="colgroup" colSpan={2} className="h-14 border-b border-rule pb-2 text-left align-bottom font-normal">
                <button
                  type="button"
                  aria-expanded={open}
                  onClick={(e) => {
                    e.stopPropagation()
                    onToggle(y.year)
                  }}
                  className="inline-flex items-baseline gap-2 rounded-sm"
                >
                  <span className="num text-base font-medium">{y.year} 年</span>
                  <span className="num text-sm text-ink-2">{yearCount(y)}</span>
                </button>
              </th>
              <td className="border-b border-rule pb-2 text-right align-bottom text-md">
                <span className="mr-1.5 text-sm text-ink-2">小計</span>
                <YearTotal value={y.realized} />
              </td>
              <td colSpan={2} className="border-b border-rule pb-2 text-right align-bottom">
                <ChevronDownIcon aria-hidden className={cn("ml-auto size-[18px] text-ink-2 transition-transform duration-200 group-hover/year:text-ink", open && "rotate-180")} />
              </td>
            </tr>
            {open &&
              y.rounds.map((r) => {
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
        )
      })}
    </table>
  )
}

function ClosedList({ years, isOpen, onToggle, accounts, multiAccount }: YearProps) {
  const privacy = usePrefs((s) => s.privacyMode)
  const money = (n: number) => (privacy ? "••••" : formatMoney(n))
  return (
    <div className="md:hidden">
      {years.map((y) => {
        const open = isOpen(y.year)
        const listId = `closed-${y.year}`
        return (
          <section key={y.year} aria-labelledby={`${listId}-title`}>
            <h3 id={`${listId}-title`} className="m-0">
              <button
                type="button"
                aria-expanded={open}
                aria-controls={listId}
                onClick={() => onToggle(y.year)}
                className={cn("flex min-h-14 w-full items-end gap-2 pb-2 text-left", !open && "border-b border-rule")}
              >
                <span className="num text-base font-medium">{y.year} 年</span>
                <span className="num text-sm text-ink-2">{yearCount(y)}</span>
                <YearTotal value={y.realized} className="ml-auto text-md" />
                <ChevronDownIcon aria-hidden className={cn("mb-0.5 size-[18px] shrink-0 text-ink-2 transition-transform duration-200", open && "rotate-180")} />
              </button>
            </h3>
            {open && (
              <>
                {/* 印好的表頭：展開時就在年份下面（雙線取代年份列的底線） */}
                <div aria-hidden className="form-head flex h-8 items-end justify-between pb-2">
                  <span>名稱・持有</span>
                  <span>已實現</span>
                </div>
                <ul id={listId} aria-label={`${y.year} 年出清`}>
                  {y.rounds.map((r) => {
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
                          {/* 三段各自不換行，段與段之間可以換行（「・」前面不能斷行，所以用 flex-wrap） */}
                          <span className="num col-span-2 mt-0.5 flex flex-wrap text-sm leading-5 text-ink-2">
                            <span className="whitespace-nowrap">{period.range}</span>
                            <span className="whitespace-nowrap">・股利 {r.dividends_received ? money(r.dividends_received) : "—"}</span>
                            <span className="whitespace-nowrap">・手續費與稅 {money(r.fees_and_taxes)}</span>
                          </span>
                        </Link>
                      </li>
                    )
                  })}
                </ul>
              </>
            )}
          </section>
        )
      })}
    </div>
  )
}
