/**
 * 出清紀錄（示範）：依 apps/api/CONTRACT_NOTES.md「ClosedRound」的定義，從交易紀錄重播出每一個回合。
 * 一個回合＝某帳戶某檔從 0 股 → 大於 0 → 回到 0；金額為台幣（美股用交易日匯率換算）。
 * 出清後才入帳的股利（除息後賣出、發放日入帳）算在最近一個回合。
 */
import type { ClosedRound, PositionHistory, PositionMarker, Transaction } from "../types"
import { findInstrument } from "./instruments"
import { daysBetweenIso, usdTwd } from "./market"

const r2 = (n: number) => Math.round(n * 100) / 100
const LEDGER_SOURCE = ["本系統帳本"]

interface Open {
  qty: number
  costTwd: number
  round: ClosedRound
}

export function closedRounds(txns: Transaction[], opts: { accountId?: string; symbol?: string } = {}): ClosedRound[] {
  const open = new Map<string, Open>()
  const lastClosed = new Map<string, ClosedRound>()
  const done: ClosedRound[] = []
  const sorted = [...txns].sort((a, b) => (a.trade_date === b.trade_date ? a.id.localeCompare(b.id) : a.trade_date.localeCompare(b.trade_date)))
  for (const x of sorted) {
    if (!x.symbol) continue
    if (opts.accountId && x.account_id !== opts.accountId) continue
    if (opts.symbol && x.symbol !== opts.symbol) continue
    const key = `${x.account_id}|${x.symbol}`
    const fx = x.currency === "USD" ? usdTwd(x.trade_date) : 1
    const q = x.quantity ?? 0
    let pos = open.get(key)
    switch (x.type) {
      case "buy": {
        if (!pos) {
          const spec = findInstrument(x.symbol)
          pos = {
            qty: 0,
            costTwd: 0,
            round: {
              symbol: x.symbol, name: spec?.name ?? x.symbol, account_id: x.account_id, currency: x.currency,
              opened_at: x.trade_date, closed_at: x.trade_date, holding_days: 0, total_bought_qty: 0, total_sold_qty: 0,
              cost_basis: 0, realized_pnl: 0, realized_pnl_pct: null, dividends_received: 0, fees_and_taxes: 0, sources: LEDGER_SOURCE,
            },
          }
          open.set(key, pos)
        }
        pos.qty += q
        pos.costTwd += (x.amount + x.fee) * fx
        pos.round.cost_basis += (x.amount + x.fee) * fx
        pos.round.total_bought_qty += q
        pos.round.fees_and_taxes += (x.fee + x.tax) * fx
        break
      }
      case "sell": {
        if (!pos || pos.qty <= 0) break
        const ratio = Math.min(q / pos.qty, 1)
        const proceeds = (x.amount - x.fee - x.tax) * fx
        pos.round.realized_pnl += proceeds - pos.costTwd * ratio
        pos.round.total_sold_qty += q
        pos.round.fees_and_taxes += (x.fee + x.tax) * fx
        pos.costTwd -= pos.costTwd * ratio
        pos.qty -= q
        if (pos.qty <= 1e-9) {
          const r = pos.round
          r.closed_at = x.trade_date
          r.holding_days = daysBetweenIso(r.opened_at, r.closed_at)
          r.cost_basis = r2(r.cost_basis)
          r.realized_pnl = r2(r.realized_pnl)
          r.fees_and_taxes = r2(r.fees_and_taxes)
          r.realized_pnl_pct = r.cost_basis ? Math.round((r.realized_pnl / r.cost_basis) * 1e6) / 1e6 : null
          done.push(r)
          lastClosed.set(key, r)
          open.delete(key)
        }
        break
      }
      case "split":
        if (pos) pos.qty *= q || 1
        break
      case "stock_dividend":
        if (pos) pos.qty += Math.floor(pos.qty * ((x.price ?? 0) / 10))
        break
      case "cash_dividend": {
        const net = (x.amount - x.tax - x.health_insurance) * fx
        const target = pos?.round ?? lastClosed.get(key)
        if (target) target.dividends_received = r2(target.dividends_received + net)
        break
      }
    }
  }
  return done.sort((a, b) => b.closed_at.localeCompare(a.closed_at) || a.symbol.localeCompare(b.symbol))
}

export function positionHistory(txns: Transaction[], symbol: string): PositionHistory {
  const markers: PositionMarker[] = txns
    .filter((t) => t.symbol === symbol && ["buy", "sell", "cash_dividend", "stock_dividend"].includes(t.type))
    .map((t) => ({
      date: t.trade_date,
      type: t.type === "cash_dividend" ? "dividend" : (t.type as PositionMarker["type"]),
      quantity: t.quantity,
      price: t.price,
      amount: t.amount,
      account_id: t.account_id,
    }))
  return { symbol, rounds: closedRounds(txns, { symbol }), markers, sources: LEDGER_SOURCE }
}
