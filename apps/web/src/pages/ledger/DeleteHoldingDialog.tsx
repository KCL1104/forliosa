import { useNavigate } from "@tanstack/react-router"
import { useId, useRef, useState } from "react"
import { toast } from "sonner"
import { appToday } from "@/api"
import { useAccounts, useDeleteHolding, useHoldings, useInvalidatePortfolio, useRecurringPlans } from "@/api/queries"
import { type Account, ApiError } from "@/api/types"
import { useUi } from "@/app/ui-store"
import { FieldError } from "@/components/form-field"
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
import { inText } from "@/lib/cjk"
import { formatNumber } from "@/lib/format"
import { recurringLabel } from "@/lib/ledger-display"
import { codeOf } from "@/lib/tick"
import { usePrefs } from "@/stores/prefs"
import { recordBreakdown, runningPlans } from "./delete-holding"
import { useSymbolTransactions } from "./symbol-records"

/**
 * 刪除這檔（產品負責人 2026-11-17：「還要有刪除股票的功能」）：一個帳戶裡這一檔的**每一筆紀錄**——買賣、股利（含自動入帳的）、
 * 分割、減資——都刪掉，持股、損益與績效重算（`DELETE /accounts/{id}/holdings/{symbol}`）。和「全部賣出」不同：什麼都不記，
 * 像從來沒記過這一檔（記錯、匯入錯的時候用）。
 * - 標題就說清楚刪什麼：「刪除台積電在「永豐－一般」的 7 筆紀錄？」；不只一種紀錄時下一句列出各幾筆（「包括 5 筆買賣、2 筆股利。」），
 *   淡墨一句「賣掉了就用「全部賣出」，損益才會留著。」（兩個動作就在同一個選單裡，刪錯會丟掉已實現損益）。
 *   筆數和展開後的每一筆、「紀錄」同一份資料（`useSymbolTransactions`，最多讀 500 筆）；還在數時標題沒有數字，超過時寫「所有紀錄」。
 * - 這一檔在好幾個帳戶都有紀錄時，一次刪一個帳戶：一列一個帳戶（radio，帳戶名＋筆數）。預設是**現在持有**這一檔的帳戶
 *   （持倉列代表的就是它們；照帳戶清單的順序取第一個），不受紀錄讀完與否影響——已經賣光的帳戶只在紀錄裡，要自己選，
 *   選了它那句淡墨字換成「這個帳戶已實現的損益也會一起刪掉。」（那裡沒有持股，「全部賣出」用不上）。
 * - 這個帳戶有還在進行的定期定額時多一個勾選「同時暫停定期定額」（預設勾著：不暫停的話下次扣款日又會提出這一檔的草稿）；
 *   暫停不是刪除，在設定可以恢復。沒勾的話通知裡說定期定額還在進行，附「到設定」。
 * - 刪除不用紅色（紅色是「漲」）：確認框的簽名格「刪除這檔」；刪除中不能關。伺服器拒絕時就地說「沒有刪除，紀錄都還在。」＋原因；
 *   404 `no_records`（別的分頁或裝置已經刪掉）當成刪好了：重抓、關掉、通知「…的紀錄已經不在了」。連不上伺服器時不知道刪了沒有，
 *   就照實說，再按一次會是刪掉或 `no_records`；這時取消也重抓，畫面照實際的。
 * - 刪掉之後那一列（連同打開確認框的「⋯」或文字動作）不在了：焦點交給持倉表／清單（`data-holdings-focus`；base-ui 會落在裡面
 *   第一個可以按的），刪光了就給主內容。取消時照常回到打開確認框的地方。
 * 查看別人的資產時沒有這個確認框（AppShell 不放），入口也都藏起來。
 */
export function DeleteHoldingHost() {
  const { open, symbol, n } = useUi((s) => s.deleteHolding)
  const close = useUi((s) => s.closeDeleteHolding)
  if (!symbol) return null
  return <DeleteHoldingDialog key={n} symbol={symbol} open={open} onClose={close} />
}

function DeleteHoldingDialog({ symbol, open, onClose }: { symbol: string; open: boolean; onClose: () => void }) {
  const id = useId()
  const navigate = useNavigate()
  const holdings = useHoldings()
  const accounts = useAccounts()
  const plans = useRecurringPlans()
  const records = useSymbolTransactions(symbol)
  const remove = useDeleteHolding()
  const refresh = useInvalidatePortfolio()
  const privacy = usePrefs((s) => s.privacyMode)
  const [picked, setPicked] = useState<string | null>(null)
  const [pause, setPause] = useState(true)
  // 刪好了（或本來就不在了）：關掉時焦點不回到已經卸載的「⋯」
  const [done, setDone] = useState(false)
  // 連不上伺服器：不知道刪了沒有，取消時重抓
  const unsure = useRef(false)

  const holding = holdings.data?.find((h) => h.symbol === symbol)
  // 有這一檔紀錄的帳戶：持股所在的帳戶，加上紀錄裡出現的（另一個帳戶已經賣光的也算），照帳戶清單的順序
  const held = new Set(holding?.account_ids ?? [])
  const rows = records.data?.items ?? []
  const ids = new Set([...held, ...rows.map((t) => t.account_id)])
  const listed: Account[] = (accounts.data ?? []).filter((a) => ids.has(a.id))
  // 預設只從現在持有的帳戶挑（紀錄讀完後也不會換）；完全沒有持股時（只剩紀錄）才取第一個
  const fallback = held.size > 0 ? listed.find((a) => held.has(a.id))?.id : listed[0]?.id
  const accountId = picked && ids.has(picked) ? picked : fallback
  const inAccount = rows.filter((t) => t.account_id === accountId)
  const counted = records.isSuccess && !records.data.more
  const live = {
    name: holding?.name ?? codeOf(symbol),
    listed: listed.map((a) => ({ ...a, count: counted ? rows.filter((t) => t.account_id === a.id).length : null })),
    accountId,
    account: listed.find((a) => a.id === accountId),
    what: counted ? ` ${formatNumber(inAccount.length)} 筆紀錄` : records.data?.more ? "所有紀錄" : "紀錄",
    breakdown: counted ? recordBreakdown(inAccount) : null,
    // 這個帳戶還持有：賣掉的話用「全部賣出」；已經賣光的帳戶刪掉就是丟掉記下來的已實現損益
    note: accountId && !held.has(accountId) ? "這個帳戶已實現的損益也會一起刪掉。" : "賣掉了就用「全部賣出」，損益才會留著。",
    running: runningPlans(plans.data ?? [], accountId, symbol, appToday()),
  }
  // 按下刪除的那一刻定住畫面：刪掉之後持股與紀錄馬上重抓，確認框淡出的那一下維持刪除前的字（不會閃成「刪除2330的紀錄？」）
  const [sent, setSent] = useState<typeof live | null>(null)
  const view = sent ?? live
  const { name, account, what, breakdown, note, running } = view

  const finish = () => {
    setDone(true)
    onClose()
  }

  const submit = () => {
    if (!accountId || remove.isPending) return
    setSent(live)
    remove.mutate(
      { accountId, symbol, pausePlans: pause && running.length > 0 },
      {
        onError: (err) => {
          if (err instanceof ApiError && err.code === "no_records") {
            // 別的分頁或裝置已經刪掉了：和刪好一樣，重抓、關掉
            refresh()
            finish()
            toast(`${inText(name)}${account ? `在「${account.name}」` : ""}的紀錄已經不在了`, { description: "可能已經在別的地方刪掉了。" })
            return
          }
          if (!(err instanceof ApiError)) unsure.current = true
          setSent(null)
        },
        onSuccess: (res) => {
          finish()
          const title = `已刪除${inText(name)}的 ${formatNumber(res.deleted)} 筆紀錄`
          if (res.plans_running > 0) {
            toast.success(title, {
              description: "這一檔的定期定額還在進行，下次扣款日會再提出草稿。",
              action: { label: "到設定", onClick: () => void navigate({ to: "/settings", hash: running[0] ? `plan-${running[0].id}` : undefined }) },
            })
          } else {
            toast.success(title, { description: res.plans_paused > 0 ? "這一檔的定期定額已暫停。" : undefined })
          }
        },
      },
    )
  }

  const close = () => {
    if (remove.isPending) return
    if (unsure.current) refresh()
    onClose()
  }

  return (
    <AlertDialog open={open} onOpenChange={(o) => !o && close()}>
      <AlertDialogContent className="sm:max-w-md" finalFocus={done ? afterDeleteFocus : true}>
        <AlertDialogHeader>
          {/* 帳戶名稱整段一起換行（inline-block）：手機上不會斷成「「永 / 豐・一般」」；太長時才在裡面換行 */}
          <AlertDialogTitle className="num">
            刪除{inText(name)}
            {account && (
              <>
                在<span className="inline-block">「{account.name}」</span>
              </>
            )}
            的{what}？
          </AlertDialogTitle>
          {/* 兩句都在 Description 裡（aria-describedby）：讀屏也會唸到「全部賣出」那一句 */}
          <AlertDialogDescription render={<div />} className="num flex flex-col gap-3">
            <p>
              {breakdown}
              持股、損益與績效會重新計算，刪除後無法復原。
            </p>
            <p className="text-ink-2">{note}</p>
          </AlertDialogDescription>
        </AlertDialogHeader>

        {view.listed.length > 1 && (
          <fieldset>
            <legend className="mb-1.5 text-sm font-medium">從哪個帳戶刪除</legend>
            {/* 最後一列底下不畫線：下面緊接著頁尾的格線（或定期定額的勾選），兩條線疊在一起會像空了一列 */}
            <ul className="border-t border-rule">
              {view.listed.map((a) => (
                <li key={a.id} className="border-b border-rule last:border-b-0">
                  <label className="flex min-h-11 cursor-pointer items-center gap-3 px-1 hover:bg-hov">
                    <input
                      type="radio"
                      name={`${id}-account`}
                      value={a.id}
                      checked={a.id === view.accountId}
                      onChange={() => setPicked(a.id)}
                      className="size-4 shrink-0 accent-ink"
                    />
                    <span className="min-w-0 flex-1 truncate">{a.name}</span>
                    {a.count !== null && <span className="num shrink-0 text-sm text-ink-2">{formatNumber(a.count)} 筆</span>}
                  </label>
                </li>
              ))}
            </ul>
          </fieldset>
        )}

        {running.length > 0 && (
          <label className="-mx-1 flex min-h-11 cursor-pointer items-start gap-3 rounded-sm px-1 py-1.5 hover:bg-hov">
            <input
              type="checkbox"
              checked={pause}
              onChange={(e) => setPause(e.target.checked)}
              className="mt-[3px] size-4 shrink-0 accent-ink"
            />
            <span className="flex flex-col gap-0.5">
              <span className="text-base">同時暫停這一檔的定期定額</span>
              <span className="num text-sm text-ink-2">{recurringLabel(running, privacy).replace(/^定期定額：/, "")}</span>
            </span>
          </label>
        )}

        {remove.isError && !done && (
          <FieldError>
            {remove.error instanceof ApiError
              ? `沒有刪除，紀錄都還在。${remove.error.message}`
              : "連不上伺服器，不確定有沒有刪除。請檢查網路後再試一次。"}
          </FieldError>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={remove.isPending}>取消</AlertDialogCancel>
          <AlertDialogAction disabled={!view.accountId || remove.isPending} onClick={submit}>
            {remove.isPending ? "刪除中…" : "刪除這檔"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

/**
 * 刪掉之後焦點的去處：看得到的那一個持倉表／清單（桌面是表格、手機是清單，另一個藏著；base-ui 交給裡面第一個可以按的），
 * 都沒有（刪光了）就是主內容
 */
function afterDeleteFocus(): HTMLElement | null {
  const lists = [...document.querySelectorAll<HTMLElement>("[data-holdings-focus]")]
  return lists.find((el) => el.getClientRects().length > 0) ?? document.getElementById("main")
}
