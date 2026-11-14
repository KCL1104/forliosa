import { useQuery } from "@tanstack/react-query"
import { useId, useState } from "react"
import { toast } from "sonner"
import { listTransactionsUpTo, useAccountSnapshot, useDeleteAccount, useRecurringPlans } from "@/api/queries"
import { ApiError, type Account } from "@/api/types"
import { FieldError } from "@/components/form-field"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { sameAccountName } from "@/lib/account-name"
import { formatNumber } from "@/lib/format"

/** 最多數到幾筆（後端每頁 200 筆；再多就寫「1,000 筆以上」） */
const COUNT_MAX = 1000

/**
 * 刪除券商帳戶（產品負責人 2026-11-14 決定 2-5：要輸入帳戶名稱才能刪）。說清楚會一起刪掉什麼——紀錄（交易與股利）的筆數、
 * 只記持股帳戶的持股、這個帳戶的定期定額——不能復原，所以沒有「復原」。失敗就地說明，什麼都沒刪。
 */
export function DeleteBrokerAccountDialog({ account, onClose }: { account: Account; onClose: () => void }) {
  const id = useId()
  const [typed, setTyped] = useState("")
  const remove = useDeleteAccount()
  const records = useQuery({
    queryKey: ["transactions", "account-count", account.id],
    queryFn: () => listTransactionsUpTo({ account_id: account.id }, COUNT_MAX),
    staleTime: 0,
  })
  const snapshot = useAccountSnapshot(account.id, account.tracking_mode === "holdings")
  const plans = useRecurringPlans()
  const name = account.name.trim()
  const ready = sameAccountName(typed, name)

  const parts: string[] = []
  const held = snapshot.data?.holdings.length ?? 0
  if (held) parts.push(`${formatNumber(held)} 檔持股`)
  if (records.data) {
    const n = records.data.items.length
    if (records.data.more) parts.push(`${formatNumber(COUNT_MAX)} 筆以上的紀錄`)
    else if (n) parts.push(`${formatNumber(n)} 筆紀錄`)
  }
  const planCount = plans.data?.filter((p) => p.account_id === account.id).length ?? 0
  if (planCount) parts.push(`${formatNumber(planCount)} 個定期定額`)
  const counted = records.isSuccess && (account.tracking_mode !== "holdings" || snapshot.isSuccess)
  const what = !counted ? "帳戶裡的紀錄會一起刪除。" : parts.length ? `帳戶裡的 ${parts.join("、")}會一起刪除。` : "帳戶裡沒有任何紀錄。"

  return (
    <Dialog open onOpenChange={(open) => !open && !remove.isPending && onClose()}>
      <DialogContent className="sm:max-w-md">
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (!ready || remove.isPending) return
            remove.mutate(account.id, {
              onSuccess: () => {
                toast.success(`已刪除「${name}」`)
                onClose()
              },
            })
          }}
        >
          <DialogHeader>
            <DialogTitle>刪除「{name}」？</DialogTitle>
            <DialogDescription>刪除之後不能復原。</DialogDescription>
          </DialogHeader>
          <p className="num text-base text-pretty text-ink" aria-live="polite">
            {what}
          </p>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={id} className="text-sm font-medium">
              請輸入帳戶名稱「{name}」
            </label>
            <Input
              id={id}
              value={typed}
              autoComplete="off"
              spellCheck={false}
              aria-invalid={remove.isError}
              aria-describedby={remove.isError ? `${id}-error` : undefined}
              onChange={(e) => setTyped(e.target.value)}
            />
            {remove.isError && (
              <FieldError id={`${id}-error`}>
                帳戶沒有刪除，資料都還在。{remove.error instanceof ApiError ? remove.error.message : "請檢查網路後再試一次。"}
              </FieldError>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" disabled={remove.isPending} onClick={onClose}>
              取消
            </Button>
            <Button type="submit" variant="sign" disabled={!ready || remove.isPending}>
              {remove.isPending ? "刪除中…" : "刪除帳戶"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
