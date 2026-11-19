import { useNavigate } from "@tanstack/react-router"
import { useId, useRef, useState } from "react"
import { toast } from "sonner"
import { useAccounts, useClearRecords, useInvalidatePortfolio, useRecordCounts } from "@/api/queries"
import { useGroups } from "@/api/sharing-queries"
import { ApiError, type RecordCount } from "@/api/types"
import { useUi } from "@/app/ui-store"
import { FieldError } from "@/components/form-field"
import { SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { formatNumber } from "@/lib/format"
import { breakdownText } from "@/pages/ledger/delete-holding"
import { exportErrorText, useExportMe } from "./export-me"

/** 要輸入這兩個字才能按（和刪除帳號、刪除券商帳戶一樣：不可逆的動作要打字確認） */
export const CLEAR_RECORDS_CONFIRMATION = "清除"
const ALL = "all"

/**
 * 清除所有持倉（產品負責人 2026-11-17：「也要有清除所有持倉的功能」）：一個帳戶或全部帳戶的**每一筆紀錄**——買賣、股利（含自動入帳的）、
 * 分割、減資、存提款——都刪掉，帳戶留著（`DELETE /portfolio/records`）。和刪除這檔同一套規則，只是範圍是整個帳戶。
 * - 從設定「帳號與資料」的「清除…」或帳本「自訂」最下面的「清除所有持倉…」打開；AppShell 掛一個 Host，查看別人的資產時不掛。
 * - 範圍：有紀錄的帳戶不只一個時，一列一個 radio（「全部帳戶」在最上面、預設選它；帳戶名＋淡墨筆數，筆數是後端數的
 *   `GET /portfolio/records`）。只有一個帳戶有紀錄時不用選，直接寫那個帳戶的名字。
 *   **範圍第一次讀到筆數時就定下來，之後只有使用者點選才會換**：筆數重抓（別的分頁清掉了一個帳戶、又記了一筆）時不會自己變成
 *   「全部帳戶」或換成沒選的帳戶。選的帳戶已經沒有紀錄時照實說「「國泰・複委託」已經沒有紀錄了」，不能按，要清別的就重新選；
 *   換範圍時打好的「清除」清空，重打一次。
 * - 「會刪除」「會留下」兩個清單（和刪除帳號的對話框同一種寫法）：刪幾筆、幾檔、各是什麼；有加入群組、範圍裡有買賣時多一項
 *   「群組動態裡這些交易，連同上面的留言與表情」（後端 `sharing.purge_trade_threads_bulk`：別人的留言也會不見）；帳戶、觀察清單、
 *   群組成員身分、AI 對話與設定留著。
 * - 範圍裡有還在進行的定期定額時一個勾選（預設勾）「同時暫停 N 個定期定額」：暫停不是刪除，在設定可以恢復。
 * - 「要留一份的話，先匯出資料。」：就地下載匯出檔（和設定的「匯出」同一個），不離開對話框；下載好了就地說。
 * - 要輸入「清除」才能按簽名格「清除 186 筆紀錄」；刪除不用紅色（紅色是「漲」）。清除中不能關。
 * - 後端自己回的錯誤（JSON 錯誤內容：commit 之前就停了、交易已經 rollback）就地說「沒有清除，紀錄都還在。」＋原因。
 *   連不上伺服器，或前面的閘道回了不是後端寫的 5xx（Cloudflare 524、Railway 重新部署時的 502／503，`http_<status>`：後端可能已經
 *   commit）時照實說「不確定有沒有清除」，範圍與筆數定在送出的那一刻（範圍的選項停用），再按一次一定送同一個範圍；取消時重抓。
 * - 404 `no_records`（別的分頁或裝置已經清掉）當成清好了：關掉、通知；勾了暫停的話後端照樣暫停，通知裡說。
 *   成功後通知筆數，持股、總資產、紀錄、本週事項重抓（`useClearRecords`）。
 * - 關掉之後焦點回到打開它的按鈕（`returnTo`；帳本的連結在「自訂」選單裡，會跟著選單關掉，所以給「自訂」那顆），不在了就給主內容。
 */
export function ClearRecordsHost() {
  const { open, n, returnTo } = useUi((s) => s.clearRecords)
  const close = useUi((s) => s.closeClearRecords)
  if (n === 0) return null
  return <ClearRecordsDialog key={n} open={open} returnTo={returnTo ?? null} onClose={close} />
}

interface Scope extends RecordCount {
  /** null：全部帳戶 */
  accountId: string | null
  /** 「全部帳戶」或「「永豐－一般」」（放進句子裡） */
  label: string
  /** 只清一個帳戶、但還有別的帳戶有紀錄 */
  othersKept: boolean
}

const NONE: RecordCount = { records: 0, trades: 0, dividends: 0, symbols: 0, plans_running: 0 }

/**
 * 送出去了、但不知道後端做了沒有：`"network"` 連不上伺服器；`"gateway"` 前面的閘道（Cloudflare、Railway）回了不是後端寫的 5xx
 * （`http.ts` 讀不到 JSON 錯誤內容時的 `http_<status>`），後端可能已經 commit。後端自己回的錯誤（有 code，例如 `internal_error`）
 * 是在 commit 之前、交易已經 rollback：`null`，紀錄都還在。
 */
function unsureKind(err: unknown): "network" | "gateway" | null {
  if (!(err instanceof ApiError)) return "network"
  return err.status >= 500 && err.code.startsWith("http_") ? "gateway" : null
}

function errorText(err: unknown): string {
  const kind = unsureKind(err)
  if (kind === "network") return "連不上伺服器，不確定有沒有清除。請檢查網路後再試一次。"
  if (kind === "gateway") return "伺服器沒有回應，不確定有沒有清除。請稍後再試一次。"
  return `沒有清除，紀錄都還在。${err instanceof ApiError ? err.message : ""}`
}

/** 通知的第二句：定期定額暫停了幾個，或還有幾個在進行（清好了，或 `no_records` 時後端照樣做了要求的暫停） */
function planNote(paused: number, running: number): string | undefined {
  if (running > 0) return `還有 ${formatNumber(running)} 個定期定額在進行，下次扣款日會再提出草稿。`
  return paused > 0 ? `${formatNumber(paused)} 個定期定額已暫停。` : undefined
}

const count = (v: unknown) => (typeof v === "number" ? v : 0)

function ClearRecordsDialog({ open, returnTo, onClose }: { open: boolean; returnTo: HTMLElement | null; onClose: () => void }) {
  const id = useId()
  const navigate = useNavigate()
  const accounts = useAccounts()
  const counts = useRecordCounts(open)
  const groups = useGroups(open)
  const clear = useClearRecords()
  const refresh = useInvalidatePortfolio()
  const [exported, setExported] = useState(false)
  const exportMe = useExportMe(() => setExported(true))
  // 選的範圍：ALL 或帳戶 id；null 是筆數還沒讀到
  const [picked, setPicked] = useState<string | null>(null)
  const [pause, setPause] = useState(true)
  const [typed, setTyped] = useState("")
  // 送出去了、不知道後端做了沒有（連不上、閘道 5xx）：取消時重抓
  const unsure = useRef(false)

  const names = new Map((accounts.data ?? []).map((a) => [a.id, a.name]))
  const loaded = !!counts.data && !!accounts.data && !groups.isPending
  // 有紀錄的帳戶（帳戶清單的順序）；選項只列叫得出名字的（帳戶清單還沒重抓到的新帳戶不列，算在「全部帳戶」裡）
  const listed = loaded ? counts.data!.accounts.filter((a) => a.records > 0) : []
  const rows = loaded ? counts.data!.accounts.filter((a) => names.has(a.account_id)) : []
  // 範圍在第一次讀到筆數時定下來（只有一個帳戶有紀錄時就是那個帳戶，不然是全部帳戶），之後只有使用者點選才會換：
  // 打開期間筆數重抓時，不會自己從選好的帳戶變成全部帳戶，或從一個帳戶擴大、換成沒選的帳戶
  const only = listed.length === 1 ? listed[0] : undefined
  if (picked === null && listed.length > 0) setPicked(only && names.has(only.account_id) ? only.account_id : ALL)
  const live: Scope | null = !loaded || picked === null
    ? null
    : picked === ALL
      ? { ...counts.data!, accountId: null, label: "全部帳戶", othersKept: false }
      : {
          ...(rows.find((a) => a.account_id === picked) ?? NONE),
          accountId: picked,
          label: names.has(picked) ? `「${names.get(picked)}」` : "這個帳戶",
          othersKept: listed.some((a) => a.account_id !== picked),
        }
  // 範圍的選項：有紀錄的帳戶（加上選了、但已經沒有紀錄的那個）不只一個時，「全部帳戶」在最上面
  const choices = rows.filter((a) => a.records > 0 || a.account_id === picked)
  const liveOptions = choices.length > 1
    ? [{ id: ALL, name: "全部帳戶", records: counts.data!.records }, ...choices.map((a) => ({ id: a.account_id, name: names.get(a.account_id)!, records: a.records }))]
    : []
  // 按下清除的那一刻定住範圍與畫面：清完之後筆數馬上重抓，對話框淡出的那一下維持清除前的字與選項（不會少一列、跳一下）；
  // 不確定有沒有清除時也定著，再按一次送的一定是同一個範圍
  const [sent, setSent] = useState<{ scope: Scope; options: typeof liveOptions } | null>(null)
  const scope = sent?.scope ?? live
  const options = sent?.options ?? liveOptions
  // 一筆紀錄都沒有
  const empty = !sent && loaded && counts.data!.records === 0
  // 選的帳戶已經沒有紀錄（別的帳戶還有）
  const gone = !empty && !!scope && scope.records === 0
  const ready = typed.trim() === CLEAR_RECORDS_CONFIRMATION
  const pausing = !!scope && scope.plans_running > 0 && pause
  const inGroups = groups.isError || (groups.data?.length ?? 0) > 0

  const toSettings = { label: "到設定", onClick: () => void navigate({ to: "/settings", hash: "recurring" }) }

  const submit = () => {
    if (!scope || empty || gone || !ready || clear.isPending) return
    setSent({ scope, options })
    clear.mutate(
      { accountId: scope.accountId, pausePlans: pausing },
      {
        onError: (err) => {
          if (err instanceof ApiError && err.code === "no_records") {
            // 別的分頁或裝置已經清掉了：和清好一樣，關掉（`useClearRecords` 重抓）；要求的暫停後端照樣做了
            onClose()
            const running = count(err.extra.plans_running)
            toast(`${scope.label}的紀錄已經不在了`, {
              description: `可能已經在別的地方清除了。${planNote(count(err.extra.plans_paused), running) ?? ""}`,
              action: running > 0 ? toSettings : undefined,
            })
            return
          }
          if (unsureKind(err)) unsure.current = true
          else setSent(null)
        },
        onSuccess: (res) => {
          onClose()
          toast.success(`已清除${scope.label}的 ${formatNumber(res.deleted)} 筆紀錄`, {
            description: planNote(res.plans_paused, res.plans_running),
            action: res.plans_running > 0 ? toSettings : undefined,
          })
        },
      },
    )
  }

  const close = () => {
    if (clear.isPending) return
    if (unsure.current) refresh()
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()}>
      <DialogContent
        className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg"
        finalFocus={() => (returnTo?.isConnected ? returnTo : document.getElementById("main"))}
      >
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <DialogHeader>
            <DialogTitle>清除所有持倉？</DialogTitle>
            <DialogDescription>每一筆紀錄都會刪掉，刪除之後不能復原。</DialogDescription>
            <p className="text-base text-ink">
              {exported ? (
                "已下載匯出檔。"
              ) : (
                <>
                  要留一份的話，先
                  <button type="button" className={textAction} disabled={exportMe.isPending} onClick={() => exportMe.mutate()}>
                    {exportMe.isPending ? "準備匯出檔…" : "匯出資料"}
                  </button>
                  。
                </>
              )}
            </p>
            {exportMe.isError && <FieldError>{exportErrorText(exportMe.error)}</FieldError>}
          </DialogHeader>

          {counts.isError ? (
            <FieldError>
              筆數沒有載入，還不能清除。
              <button type="button" className={`${textAction} ml-1`} onClick={() => void counts.refetch()}>
                再試一次
              </button>
            </FieldError>
          ) : empty ? (
            <p className="text-base text-ink">目前沒有任何紀錄，不用清除。</p>
          ) : !loaded || !scope ? (
            <SkeletonLines rows={4} />
          ) : (
            <>
              {options.length > 0 && (
                <fieldset disabled={clear.isPending || !!sent}>
                  <legend className="mb-1.5 text-sm font-medium">清除哪些帳戶</legend>
                  <ul className="border-t border-rule">
                    {options.map((a) => (
                      <li key={a.id} className="border-b border-rule last:border-b-0">
                        <label className="flex min-h-11 cursor-pointer items-center gap-3 px-1 hover:bg-hov">
                          <input
                            type="radio"
                            name={`${id}-scope`}
                            value={a.id}
                            checked={a.id === (scope.accountId ?? ALL)}
                            onChange={() => {
                              setPicked(a.id)
                              // 「清除」是對這個範圍打的：換了範圍就重打
                              setTyped("")
                            }}
                            className="size-4 shrink-0 accent-ink"
                          />
                          <span className="min-w-0 flex-1 truncate">{a.name}</span>
                          <span className="num shrink-0 text-sm text-ink-2">{formatNumber(a.records)} 筆</span>
                        </label>
                      </li>
                    ))}
                  </ul>
                </fieldset>
              )}

              {gone ? (
                <p className="text-base text-ink" aria-live="polite">
                  {scope.label}已經沒有紀錄了，可能已經在別的地方清除了。
                </p>
              ) : (
                /* 和刪除帳號的對話框同一種寫法：會刪除／會留下 */
                <div className="flex flex-col gap-3 text-md" aria-live="polite">
                  <div>
                    <p className="font-medium">會刪除</p>
                    <ul className="num mt-1 flex list-disc flex-col gap-0.5 pl-5 text-ink-2 marker:text-ink-2">
                      <li>
                        {scope.label}的 {formatNumber(scope.records)} 筆紀錄{scope.symbols > 0 && `（${formatNumber(scope.symbols)} 檔股票）`}
                        {breakdownText(scope) && <span className="block">{breakdownText(scope)}</span>}
                      </li>
                      <li>這些紀錄算出來的持股、損益、出清紀錄與績效</li>
                      {/* 後端連同群組成員寫在上面的留言與表情一起刪（別的帳戶同一天買同一檔撐著的除外） */}
                      {inGroups && scope.trades > 0 && <li>群組動態裡這些交易，連同上面的留言與表情</li>}
                    </ul>
                  </div>
                  <div>
                    <p className="font-medium">會留下</p>
                    <ul className="mt-1 flex list-disc flex-col gap-0.5 pl-5 text-ink-2 marker:text-ink-2">
                      <li>券商帳戶，清除後可以重新記</li>
                      {scope.othersKept && <li>其他帳戶的紀錄</li>}
                      <li>{inGroups ? "觀察清單、群組成員身分、AI 對話與設定" : "觀察清單、AI 對話與設定"}</li>
                    </ul>
                  </div>
                </div>
              )}

              {!gone && scope.plans_running > 0 && (
                <label className="-mx-1 flex min-h-11 cursor-pointer items-start gap-3 rounded-sm px-1 py-1.5 hover:bg-hov">
                  <input
                    type="checkbox"
                    checked={pause}
                    onChange={(e) => setPause(e.target.checked)}
                    className="mt-[3px] size-4 shrink-0 accent-ink"
                  />
                  <span className="flex flex-col gap-0.5">
                    <span className="num text-base">同時暫停 {formatNumber(scope.plans_running)} 個定期定額</span>
                    <span className="text-sm text-ink-2">暫停不是刪除，在設定可以恢復。</span>
                  </span>
                </label>
              )}

              {!gone && (
                <div className="flex flex-col gap-1.5">
                  <label htmlFor={id} className="print-label text-sm">
                    請輸入「{CLEAR_RECORDS_CONFIRMATION}」
                  </label>
                  <Input
                    id={id}
                    value={typed}
                    autoComplete="off"
                    spellCheck={false}
                    className="pointer-coarse:h-11"
                    aria-invalid={clear.isError}
                    aria-describedby={clear.isError ? `${id}-error` : undefined}
                    onChange={(e) => setTyped(e.target.value)}
                  />
                  {clear.isError && <FieldError id={`${id}-error`}>{errorText(clear.error)}</FieldError>}
                </div>
              )}
            </>
          )}

          <DialogFooter>
            {empty ? (
              <Button type="button" variant="outline" onClick={close}>
                關閉
              </Button>
            ) : (
              <>
                <Button type="button" variant="outline" disabled={clear.isPending} onClick={close}>
                  取消
                </Button>
                <Button type="submit" variant="sign" disabled={!scope || !loaded || gone || !ready || clear.isPending}>
                  {clear.isPending ? "清除中…" : scope && loaded && !gone ? `清除 ${formatNumber(scope.records)} 筆紀錄` : "清除"}
                </Button>
              </>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
