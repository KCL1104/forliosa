import { Link, useRouterState } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { toast } from "sonner"
import { api, appToday } from "@/api"
import { useAccounts, useCreateRecurring, useDeleteRecurring, useQuote, useRecurringPlans, useUpdateRecurring } from "@/api/queries"
import type { Account, Instrument, RecurringPlan, RecurringPlanInput } from "@/api/types"
import { DayOfMonthPicker } from "@/components/day-picker"
import { daysLabel, planStatus } from "@/lib/ledger-display"
import { FormField as Field } from "@/components/form-field"
import { Section } from "@/components/section"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
import { SymbolPicker } from "@/components/symbol-picker"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { formatDate, formatDateShort, formatMoney, formatQuantity } from "@/lib/format"
import { codeOf, formatQuote } from "@/lib/tick"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"

/** 對話框裡的輸入框與下拉選單：觸控時 44px 高 */
const TOUCH_FIELDS = "pointer-coarse:[&_input]:h-11 pointer-coarse:[&_[data-slot=select-trigger]]:h-11!"

/**
 * 定期定額：設定頁的一個區塊（頭像選單、帳本的定期定額扣款都連到這裡 `#recurring`；持倉的定期定額標記連到 `#plan-<id>`）。
 * 列出計畫（每月幾日、金額、帳戶、下一次扣款）、新增／修改（對話框）、刪除（確認）、啟用開關。
 * 列上的動作和設定頁其他清單同一套：改內容的是文字動作（「修改」），這一列最重的動作（「刪除」）是外框按鈕；沒有只有圖示的按鈕。
 * 扣款日當天 AI 面板會提出交易草稿，使用者簽名後才入帳。
 */
export function RecurringPlans() {
  const plans = useRecurringPlans()
  const accounts = useAccounts()
  const update = useUpdateRecurring()
  const privacy = usePrefs((s) => s.privacyMode)
  const [editing, setEditing] = useState<RecurringPlan | "new" | null>(null)
  const [deleting, setDeleting] = useState<RecurringPlan | null>(null)
  const today = appToday()
  const twd = (accounts.data ?? []).filter((a) => a.currency === "TWD")
  const nameOf = (id: string) => accounts.data?.find((a) => a.id === id)?.name ?? ""
  // 從持倉的定期定額標記進來（#plan-…）：計畫載入後捲到那一列並標示
  const hash = useRouterState({ select: (s) => s.location.hash })
  const ready = !!plans.data && !!accounts.data
  useEffect(() => {
    if (!ready || !hash.startsWith("plan-")) return
    document.getElementById(hash)?.scrollIntoView({ block: "center" })
  }, [ready, hash])

  const setActive = (p: RecurringPlan, active: boolean) =>
    update.mutate(
      { id: p.id, patch: { active } },
      {
        onSuccess: () => toast.success(active ? `已恢復「${p.name}」定期定額` : `已暫停「${p.name}」定期定額`, { description: active ? "下一次扣款日 AI 會提出草稿。" : "暫停期間不會出現扣款提醒。" }),
        onError: (err) => toast.error("沒有更新", { description: err.message }),
      },
    )

  return (
    <Section
      id="recurring"
      title="定期定額"
      titleId="set-recurring"
      className="scroll-mt-20"
      bodyClassName="pt-0"
      action={
        <Button variant="outline" size="sm" onClick={() => setEditing("new")} disabled={!accounts.data || twd.length === 0}>
          新增定期定額
        </Button>
      }
    >
      {plans.isError ? (
        <ErrorState flush error={plans.error} onRetry={() => void plans.refetch()} />
      ) : !plans.data || !accounts.data ? (
        <SkeletonLines rows={3} className="pt-3" />
      ) : twd.length === 0 ? (
        <EmptyState flush title="還沒有新台幣帳戶" description="定期定額要從新台幣帳戶扣款。先在上面的「券商帳戶」新增一個，例如「永豐・一般」。" />
      ) : plans.data.length === 0 ? (
        <EmptyState
          flush
          title="還沒有定期定額"
          description="扣款日 AI 會寫好交易草稿，等你簽名。"
          action={
            <Button variant="outline" size="sm" onClick={() => setEditing("new")}>
              新增第一個計畫
            </Button>
          }
        />
      ) : (
        // 標題的印刷線就是清單上面那條線
        <ul className="flex flex-col divide-y divide-rule border-b border-rule">
          {plans.data.map((p) => {
            const status = planStatus(p, today)
            return (
              <li
                key={p.id}
                id={`plan-${p.id}`}
                aria-current={hash === `plan-${p.id}` ? "true" : undefined}
                // 和其他設定列同一個左緣；從持倉標記進來的那一列（選取語法 (c)）才內縮，讓字不貼著 2px 的墨線
                className="sel-row flex scroll-mt-24 flex-col gap-2 py-4 aria-[current=true]:px-3 sm:flex-row sm:items-start sm:gap-4"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <Link to="/stock/$symbol" params={{ symbol: p.symbol }} className="font-medium hover:underline pointer-coarse:-my-2.5 pointer-coarse:py-2.5">
                      {p.name}
                    </Link>
                    <span className="num text-sm text-ink-2">{codeOf(p.symbol)}</span>
                    {status !== "active" && <span className="demo-tag text-ink-2">{status === "paused" ? "已暫停" : "已結束"}</span>}
                  </div>
                  {/* 觸控時這一行不接收點按：上面名稱連結往下的可按範圍（合計 44px）落在這裡 */}
                  <p className="num mt-1 text-md pointer-coarse:pointer-events-none">
                    {daysLabel(p.day_of_month)}・{privacy ? "••••" : formatMoney(p.amount)}
                    <span className="text-ink-2">・{nameOf(p.account_id)}</span>
                  </p>
                  <p className="num mt-0.5 text-sm text-ink-2">
                    {status === "active" && p.next_date
                      ? `下次扣款 ${formatDateShort(p.next_date)}${p.day_of_month.includes(Number(p.next_date.slice(8, 10))) ? "" : "（遇休市順延）"}`
                      : status === "paused"
                        ? "暫停中，不會提出草稿"
                        : "沒有下一次扣款"}
                    ・自 {formatDate(p.start_date)} 起{p.end_date && `，到 ${formatDate(p.end_date)}`}
                  </p>
                  {p.note && <p className="mt-0.5 text-sm text-ink-2">{p.note}</p>}
                </div>
                <div className="flex items-center gap-3 max-sm:-ml-1">
                  <label className="mr-1 inline-flex min-h-10 cursor-pointer items-center gap-2 px-1 text-sm text-ink-2 pointer-coarse:min-h-11">
                    啟用
                    <Switch
                      checked={p.active}
                      disabled={update.isPending || status === "ended"}
                      onCheckedChange={(v) => setActive(p, v)}
                      aria-label={p.active ? `暫停「${p.name}」定期定額` : `恢復「${p.name}」定期定額`}
                    />
                  </label>
                  <button type="button" onClick={() => setEditing(p)} aria-label={`修改「${p.name}」定期定額`} className={textAction}>
                    修改
                  </button>
                  {/* 刪除前先確認（DeletePlan）。和授權的「撤銷」同一種外框按鈕，不是只有圖示的垃圾桶 */}
                  <Button variant="outline" size="sm" onClick={() => setDeleting(p)} aria-label={`刪除「${p.name}」定期定額`}>
                    刪除
                  </Button>
                </div>
              </li>
            )
          })}
        </ul>
      )}
      {editing && <PlanDialog key={editing === "new" ? "new" : editing.id} plan={editing === "new" ? null : editing} accounts={twd} onClose={() => setEditing(null)} />}
      <DeletePlan plan={deleting} onClose={() => setDeleting(null)} />
    </Section>
  )
}

function DeletePlan({ plan, onClose }: { plan: RecurringPlan | null; onClose: () => void }) {
  const remove = useDeleteRecurring()
  return (
    <AlertDialog open={!!plan} onOpenChange={(o) => !o && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>刪除「{plan?.name}」定期定額？</AlertDialogTitle>
          <AlertDialogDescription>
            {plan && `${daysLabel(plan.day_of_month)}的計畫會刪除，之後不會再出現扣款提醒。`}已經入帳的交易不受影響。只是暫時不想扣，可以改用開關暫停。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction
            onClick={() => {
              if (!plan) return
              const name = plan.name
              onClose()
              remove.mutate(plan.id, {
                onSuccess: () => toast.success(`已刪除「${name}」定期定額`),
                onError: (err) => toast.error("沒有刪除", { description: err.message }),
              })
            }}
          >
            刪除計畫
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

/** 新增或修改計畫（plan 為 null 時新增） */
function PlanDialog({ plan, accounts, onClose }: { plan: RecurringPlan | null; accounts: Account[]; onClose: () => void }) {
  const create = useCreateRecurring()
  const update = useUpdateRecurring()
  const [accountId, setAccountId] = useState(plan?.account_id ?? accounts[0]?.id ?? "")
  const [symbol, setSymbol] = useState<Instrument | null>(null)
  const [amountText, setAmountText] = useState(plan ? String(plan.amount) : "")
  const [days, setDays] = useState<number[]>(plan?.day_of_month ?? [])
  const [start, setStart] = useState(plan?.start_date ?? appToday())
  const [end, setEnd] = useState(plan?.end_date ?? "")
  const [active, setActive] = useState(plan?.active ?? true)
  const [note, setNote] = useState(plan?.note ?? "")
  const [touched, setTouched] = useState(false)

  // 修改時帶入原本的商品
  useEffect(() => {
    if (!plan) return
    void api.getInstrument(plan.symbol).then((i) => setSymbol((s) => s ?? i))
  }, [plan])

  const amount = Number(amountText.replace(/[,\s]/g, ""))
  const errors = {
    account: !accountId ? "請選擇扣款帳戶" : null,
    symbol: !symbol ? "請選擇台股或 ETF" : null,
    amount: !amountText.trim() || !Number.isInteger(amount) || amount <= 0 ? "請填每次扣款金額（新台幣整數元），例如 3000" : null,
    days: days.length === 0 ? "至少選一個扣款日" : null,
    end: end && start && end < start ? "結束日不能早於開始日" : null,
  }
  const invalid = Object.values(errors).some(Boolean)
  const pending = create.isPending || update.isPending

  const save = () => {
    setTouched(true)
    if (invalid || !symbol) return
    const body: RecurringPlanInput = { account_id: accountId, symbol: symbol.symbol, amount, day_of_month: days, start_date: start || undefined, end_date: end || null, active, note: note.trim() }
    const done = {
      onSuccess: (p: RecurringPlan) => {
        toast.success(plan ? `已更新「${p.name}」定期定額` : `已新增「${p.name}」定期定額`, {
          description: p.next_date ? `下次扣款 ${formatDateShort(p.next_date)}，當天 AI 會先寫好草稿。` : "目前沒有下一次扣款。",
        })
        onClose()
      },
      onError: (err: Error) => toast.error("沒有存成功，內容還在。", { description: err.message }),
    }
    if (plan) update.mutate({ id: plan.id, patch: body }, done)
    else create.mutate(body, done)
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{plan ? "修改定期定額" : "新增定期定額"}</DialogTitle>
          <DialogDescription>股數 = 扣款金額 ÷ 收盤價（無條件捨去，含零股）。補記過去的扣款用那天的收盤價。</DialogDescription>
        </DialogHeader>
        <div className={cn("grid gap-4", TOUCH_FIELDS)}>
          <Field label="股票或 ETF" error={touched ? errors.symbol : null}>
            <SymbolPicker label="股票或 ETF" value={symbol} onChange={setSymbol} invalid={touched && !!errors.symbol} accept={(i) => i.market !== "US"} rejectReason="美股不支援" />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="扣款帳戶" error={touched ? errors.account : null}>
              <Select value={accountId} onValueChange={(v) => setAccountId(v as string)} items={accounts.map((a) => ({ value: a.id, label: a.name }))}>
                <SelectTrigger className="w-full" aria-label="扣款帳戶">
                  <SelectValue placeholder="選擇帳戶" />
                </SelectTrigger>
                <SelectContent>
                  {accounts.map((a) => (
                    <SelectItem key={a.id} value={a.id}>
                      {a.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field label="每次扣款（新台幣）" htmlFor="rcp-amount" error={touched ? errors.amount : null}>
              <Input id="rcp-amount" inputMode="numeric" value={amountText} onChange={(e) => setAmountText(e.target.value)} placeholder="例如 3000" aria-invalid={touched && !!errors.amount} />
            </Field>
          </div>
          {symbol && amount > 0 && Number.isInteger(amount) && <SharesHint symbol={symbol} amount={amount} />}
          <Field label="每月扣款日（可複選）" error={touched ? errors.days : null} hint={days.length ? daysLabel(days) : undefined}>
            <DayOfMonthPicker value={days} onChange={setDays} invalid={touched && !!errors.days} />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="開始日" htmlFor="rcp-start">
              <Input id="rcp-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
            </Field>
            <Field label="結束日（選填）" htmlFor="rcp-end" error={touched ? errors.end : null}>
              <Input id="rcp-end" type="date" value={end} min={start || undefined} onChange={(e) => setEnd(e.target.value)} aria-invalid={touched && !!errors.end} />
            </Field>
          </div>
          <Field label="備註（選填）" htmlFor="rcp-note">
            <Input id="rcp-note" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} placeholder="例如：季配息再投入" />
          </Field>
          <label className="flex min-h-11 items-center justify-between gap-3 border-y border-rule py-2">
            <span>
              <span className="block font-medium">啟用</span>
              <span className="block text-base text-ink">暫停時不會出現扣款提醒，也不會提出草稿。</span>
            </span>
            <Switch checked={active} onCheckedChange={setActive} />
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button variant="sign" onClick={save} disabled={pending}>
            {pending ? "儲存中…" : plan ? "儲存" : "新增計畫"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** 以最近收盤價估算一次能買幾股（只是提示；草稿在扣款日用最近收盤價，補記過去的扣款用那天的收盤價） */
function SharesHint({ symbol, amount }: { symbol: Instrument; amount: number }) {
  const quote = useQuote(symbol.symbol)
  const price = quote.data?.price
  if (!price) return null
  const shares = Math.floor(amount / price)
  return (
    <p className="num -mt-2 text-sm text-ink-2" aria-live="polite">
      {shares < 1
        ? `最近收盤 ${formatQuote(price, symbol.market, symbol.type)}，NT$${amount.toLocaleString("zh-TW")} 不足買 1 股。`
        : `最近收盤 ${formatQuote(price, symbol.market, symbol.type)}，一次約 ${formatQuantity(shares, "lot", symbol.market)}${shares < 1000 ? "（零股）" : ""}。`}
    </p>
  )
}
