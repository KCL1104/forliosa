/**
 * 定期定額（示範）：計畫的 CRUD、扣款日（遇週末順延到下一個交易日）、本週事項、交易草稿。
 * 規則與後端一致（apps/api/CONTRACT_NOTES.md「定期定額」）：成交日 = 扣款日；股數 = floor(金額 ÷ 收盤價)（含零股）；不自動算手續費。
 * 扣款日已經過去（補記）用**扣款日當天**的收盤價，今天或之後用最近收盤價；
 * 草稿**不會建立交易**，使用者簽名後才 `POST /transactions`。
 */
import { ApiError, type Account, type RecurringDraft, type RecurringPlan, type RecurringPlanInput, type UpcomingItem } from "../types"
import { computePreview } from "./fees"
import { findInstrument } from "./instruments"
import { addDays, closeOn, MOCK_TODAY, nextTradingDay } from "./market"

const CALENDAR_SOURCE = "臺灣證券交易所〈有價證券集中交易市場開（休）市日期〉（2026），依政府資料開放授權條款第 1 版"
const nt = (n: number) => `NT$${new Intl.NumberFormat("zh-TW").format(n)}`
const md = (d: string) => `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}`

/** 每一次扣款：[計畫原本的日子, 順延後的扣款日]，只回扣款日落在 [from, to] 的 */
export function debitDates(plan: Pick<RecurringPlan, "day_of_month" | "start_date" | "end_date">, from: string, to: string): [string, string][] {
  const out: [string, string][] = []
  // 從前一個月開始找，才能抓到「上個月底順延到這個月初」的扣款
  let month = addDays(`${from.slice(0, 7)}-01`, -1).slice(0, 7)
  const last = to.slice(0, 7)
  while (month <= last) {
    for (const day of plan.day_of_month) {
      const scheduled = `${month}-${String(day).padStart(2, "0")}`
      if (scheduled < plan.start_date || (plan.end_date && scheduled > plan.end_date)) continue
      const debit = nextTradingDay(scheduled)
      if (debit >= from && debit <= to) out.push([scheduled, debit])
    }
    month = addDays(`${month}-28`, 5).slice(0, 7)
  }
  return out.sort((a, b) => a[1].localeCompare(b[1]))
}

export function nextDebit(plan: Pick<RecurringPlan, "active" | "day_of_month" | "start_date" | "end_date">, today = MOCK_TODAY): [string, string] | null {
  if (!plan.active) return null
  return debitDates(plan, today, addDays(today, 62))[0] ?? null
}

function withNext(plan: RecurringPlan): RecurringPlan {
  return { ...plan, day_of_month: [...plan.day_of_month].sort((a, b) => a - b), next_date: nextDebit(plan)?.[1] ?? null }
}

export interface RecurringStore {
  list(accountId?: string): RecurringPlan[]
  create(body: RecurringPlanInput): RecurringPlan
  update(id: string, patch: Partial<RecurringPlanInput>): RecurringPlan
  remove(id: string): void
  upcoming(from: string, to: string): UpcomingItem[]
  draft(id: string, date?: string): RecurringDraft
}

/** 示範計畫：0050 每月 6 日 NT$10,000、00878 每月 12、26 日 NT$4,000（今天 11/12 是扣款日） */
export function seedPlans(accountId: string): RecurringPlan[] {
  const at = "2024-01-02T09:00:00+08:00"
  return [
    { id: "rcp_demo0050", account_id: accountId, symbol: "0050.TW", name: "元大台灣50", amount: 10_000, day_of_month: [6], start_date: "2024-01-01", end_date: null, active: true, note: "", next_date: null, created_at: at, updated_at: at },
    { id: "rcp_demo00878", account_id: accountId, symbol: "00878.TW", name: "國泰永續高股息", amount: 4_000, day_of_month: [12, 26], start_date: "2024-01-01", end_date: null, active: true, note: "季配息再投入", next_date: null, created_at: at, updated_at: at },
  ]
}

export function createRecurringStore(initial: RecurringPlan[], accounts: () => Account[]): RecurringStore {
  let plans = initial.map(withNext)
  let seq = 0
  const now = () => new Date().toISOString()

  const validate = (p: RecurringPlanInput) => {
    const account = accounts().find((a) => a.id === p.account_id)
    if (!account) throw new ApiError(422, "validation_error", "找不到這個帳戶")
    if (account.currency !== "TWD") throw new ApiError(422, "validation_error", "定期定額只支援新台幣帳戶")
    const spec = findInstrument(p.symbol)
    if (!spec) throw new ApiError(422, "unknown_symbol", "找不到商品")
    if (spec.market === "US") throw new ApiError(422, "validation_error", "定期定額只支援台股與 ETF")
    if (!Number.isInteger(p.amount) || p.amount <= 0) throw new ApiError(422, "validation_error", "扣款金額請填正整數（新台幣元）")
    if (p.day_of_month.length === 0 || p.day_of_month.some((d) => !Number.isInteger(d) || d < 1 || d > 28)) {
      throw new ApiError(422, "validation_error", "扣款日必須是 1–28 的整數")
    }
    if (p.end_date && p.start_date && p.end_date < p.start_date) throw new ApiError(422, "validation_error", "結束日不能早於開始日")
    return spec
  }
  const owned = (id: string) => {
    const found = plans.find((p) => p.id === id)
    if (!found) throw new ApiError(404, "not_found", "找不到這個定期定額計畫")
    return found
  }

  return {
    list: (accountId) => plans.filter((p) => !accountId || p.account_id === accountId).map(withNext),
    create(body) {
      const input = { ...body, day_of_month: [...new Set(body.day_of_month)], start_date: body.start_date ?? MOCK_TODAY }
      const spec = validate(input)
      const plan = withNext({
        id: `rcp_${Date.now().toString(36)}${++seq}`, account_id: input.account_id, symbol: spec.symbol, name: spec.name,
        amount: input.amount, day_of_month: input.day_of_month, start_date: input.start_date, end_date: input.end_date ?? null,
        active: input.active ?? true, note: input.note ?? "", next_date: null, created_at: now(), updated_at: now(),
      })
      plans = [...plans, plan]
      return plan
    },
    update(id, patch) {
      const cur = owned(id)
      const merged = { ...cur, ...patch, day_of_month: patch.day_of_month ? [...new Set(patch.day_of_month)] : cur.day_of_month }
      const spec = validate({ ...merged, end_date: merged.end_date ?? null })
      const next = withNext({ ...merged, symbol: spec.symbol, name: spec.name, end_date: merged.end_date ?? null, updated_at: now() })
      plans = plans.map((p) => (p.id === id ? next : p))
      return next
    },
    remove(id) {
      owned(id)
      plans = plans.filter((p) => p.id !== id)
    },
    upcoming(from, to) {
      return plans
        .filter((p) => p.active)
        .flatMap((p) =>
          debitDates(p, from, to).map(([scheduled, debit]): UpcomingItem => ({
            date: debit,
            type: "recurring",
            symbol: p.symbol,
            title: `${p.name} 定期定額 ${nt(p.amount)}${scheduled === debit ? "" : `（${md(scheduled)} 非交易日，順延）`}`,
            amount_estimate: p.amount,
            is_demo: false,
            sources: ["帳本紀錄", CALENDAR_SOURCE],
            plan_id: p.id,
            account_id: p.account_id,
            scheduled_date: scheduled,
          })),
        )
    },
    draft(id, date) {
      const plan = owned(id)
      const spec = findInstrument(plan.symbol)!
      let scheduled: string
      let debit: string
      if (date) {
        scheduled = date
        debit = nextTradingDay(date)
      } else {
        const next = nextDebit(plan)
        if (!next) throw new ApiError(409, "conflict", "這個計畫沒有下一次扣款（已停用或已結束）")
        scheduled = next[0]
        debit = next[1]
      }
      const account = accounts().find((a) => a.id === plan.account_id)
      // 扣款日已過（補記）：用那天的收盤價；今天或之後：示範報價固定在 13:30 收盤，現價就是最近收盤價
      const past = debit < MOCK_TODAY
      const price = past ? closeOn(spec, debit) : spec.price
      const priceAsOf = past ? debit : MOCK_TODAY
      const shares = Math.floor(plan.amount / price)
      if (shares < 1) throw new ApiError(422, "amount_too_small", `${nt(plan.amount)} 不足買 1 股（收盤價 ${price}）`)
      const transaction = {
        account_id: plan.account_id, symbol: plan.symbol, type: "buy" as const, trade_date: debit, quantity: shares, price,
        note: `定期定額 ${nt(plan.amount)}（${md(debit)}）`, source: "ai_draft" as const,
      }
      const preview = computePreview(transaction, account, spec, { auto: false })
      const lot = shares < 1000 ? "零股" : shares % 1000 === 0 ? "整張" : "整張＋零股"
      const rules = [`股數 = floor(${nt(plan.amount)} ÷ 收盤價 ${price}（${md(priceAsOf)}）) = ${shares} 股（${lot}）`, ...preview.rules]
      if (scheduled !== debit) rules.unshift(`扣款日 ${md(scheduled)} 不是交易日，順延到 ${md(debit)}`)
      return {
        plan_id: plan.id, scheduled_date: scheduled, date: debit, name: plan.name, amount: plan.amount, price_as_of: priceAsOf,
        transaction, preview: { ...preview, rules }, is_demo: false, sources: ["帳本紀錄", CALENDAR_SOURCE],
      }
    },
  }
}
