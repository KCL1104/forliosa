import { useMutation } from "@tanstack/react-query"
import { useId, useState } from "react"
import { toast } from "sonner"
import { api, appToday } from "@/api"
import { ACCOUNT_DELETE_CONFIRMATION, ApiError } from "@/api/types"
import { useReadOnly } from "@/api/view-as"
import { FieldError } from "@/components/form-field"
import { Section } from "@/components/section"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { hardNavigate } from "@/lib/hard-nav"
import { clearLocalUserData } from "@/lib/local-data"
import { retryText } from "@/pages/discussions/labels"
import { LegalLinks } from "@/pages/legal/LegalLinks"

/** 把匯出的資料存成檔案（`forliosa-export-YYYYMMDD.json`）：在瀏覽器裡做一個暫時的下載連結按下去 */
function saveAsFile(data: unknown, filename: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }))
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  // 下載開始之後再釋放（馬上釋放的話有些瀏覽器會存到空檔）
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

function exportErrorText(err: unknown): string {
  if (!(err instanceof ApiError)) return "沒有匯出成功，請檢查網路後再試一次。"
  if (err.code === "rate_limited") {
    const seconds = typeof err.extra.retry_after_seconds === "number" ? err.extra.retry_after_seconds : null
    return seconds === null ? "匯出太頻繁，請稍後再試。" : `匯出太頻繁，${retryText(seconds)}可以再試。`
  }
  if (err.status === 401) return "登入已過期，請重新登入後再試一次。"
  return err.message
}

/**
 * 設定頁最下面的「帳號與資料」：匯出我的資料、服務條款與隱私權政策、刪除帳號。
 * 列的樣子和設定頁其他區塊相同（標題＋一句說明在左、動作在右）；這裡的動作都是外框按鈕——
 * 匯出只是下載一個檔，刪除要到對話框裡輸入一句話才會真的執行。查看別人的資產時不出現（這些是自己帳號的事）。
 */
export function AccountData() {
  const readOnly = useReadOnly()
  const [deleting, setDeleting] = useState(false)
  const exportMe = useMutation({
    mutationFn: () => api.exportMe(),
    onSuccess: (data) => {
      saveAsFile(data, `forliosa-export-${appToday().replaceAll("-", "")}.json`)
      toast.success("已下載匯出檔")
    },
  })
  if (readOnly) return null
  return (
    <Section id="account" title="帳號與資料" titleId="set-account" bodyClassName="pt-0" className="scroll-mt-20">
      <div className="flex flex-col divide-y divide-rule border-b border-rule">
        <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
          <div className="min-w-0">
            <p className="font-medium">匯出我的資料</p>
            <p className="mt-0.5 text-md text-ink-2">下載一個 JSON 檔：個人資料、券商帳戶與交易、定期定額、觀察清單、AI 對話，以及你在群組與討論裡寫的內容。</p>
            {exportMe.isError && <FieldError className="mt-1.5">{exportErrorText(exportMe.error)}</FieldError>}
          </div>
          <Button variant="outline" className="shrink-0 self-start sm:self-auto" disabled={exportMe.isPending} onClick={() => exportMe.mutate()}>
            {exportMe.isPending ? "準備中…" : "匯出"}
          </Button>
        </div>
        <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
          <div className="min-w-0">
            <p className="font-medium">條款與隱私</p>
            <p className="mt-0.5 text-md text-ink-2">我們怎麼處理你的資料，以及使用這個服務的約定。</p>
          </div>
          <p className="flex shrink-0 flex-wrap gap-x-5">
            <LegalLinks className={textAction} />
          </p>
        </div>
        <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
          <div className="min-w-0">
            <p className="font-medium">刪除帳號</p>
            <p className="mt-0.5 text-md text-ink-2">帳本、AI 對話與個人資料會全部刪除，不能復原。要留一份的話，先匯出。</p>
          </div>
          <Button variant="outline" className="shrink-0 self-start sm:self-auto" onClick={() => setDeleting(true)}>
            刪除帳號…
          </Button>
        </div>
      </div>
      {deleting && <DeleteAccountDialog onClose={() => setDeleting(false)} />}
    </Section>
  )
}

/**
 * 刪除帳號：說清楚刪掉什麼、留下什麼，要輸入「刪除我的帳號」才能按。成功後清掉這台瀏覽器上的對話與草稿，
 * 回到登入頁（那裡寫一句「帳號已刪除」）。失敗就地說明，什麼都沒刪。
 */
function DeleteAccountDialog({ onClose }: { onClose: () => void }) {
  const id = useId()
  const [typed, setTyped] = useState("")
  const remove = useMutation({
    mutationFn: () => api.deleteMe(ACCOUNT_DELETE_CONFIRMATION),
    onSuccess: () => {
      clearLocalUserData()
      // 整頁重新載入到登入頁：記憶體裡的資料（查詢快取）一併清掉
      hardNavigate("/login?deleted=1")
    },
  })
  const ready = typed.trim() === ACCOUNT_DELETE_CONFIRMATION
  return (
    <Dialog open onOpenChange={(open) => !open && !remove.isPending && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (ready && !remove.isPending) remove.mutate()
          }}
        >
          <DialogHeader>
            <DialogTitle>刪除帳號？</DialogTitle>
            <DialogDescription>刪除之後不能復原，同一個 Discord 帳號再登入會是全新的帳號。</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3 text-md">
            <div>
              <p className="font-medium">會刪除</p>
              <ul className="mt-1 flex list-disc flex-col gap-0.5 pl-5 text-ink-2 marker:text-ink-2">
                <li>個人資料、登入紀錄、公開暱稱</li>
                <li>所有券商帳戶與交易、定期定額、觀察清單</li>
                <li>AI 對話與草稿</li>
                <li>你在群組裡的成員身分與分享設定、你給別人和別人給你的授權</li>
              </ul>
            </div>
            <div>
              <p className="font-medium">會留下</p>
              <ul className="mt-1 flex list-disc flex-col gap-0.5 pl-5 text-ink-2 marker:text-ink-2">
                <li>你在群組寫的留言、在討論寫的主題與回覆——作者會顯示成「已刪除的帳號」。想拿掉的話，先自己刪除再刪帳號。</li>
                <li>你擁有的群組會轉給最早的管理員或成員；沒有其他成員的群組會一起刪除。</li>
              </ul>
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={id} className="text-sm font-medium">
              請輸入「{ACCOUNT_DELETE_CONFIRMATION}」
            </label>
            <Input
              id={id}
              value={typed}
              autoComplete="off"
              className="pointer-coarse:h-11"
              aria-invalid={remove.isError}
              aria-describedby={remove.isError ? `${id}-error` : undefined}
              onChange={(e) => setTyped(e.target.value)}
            />
            {remove.isError && (
              <FieldError id={`${id}-error`}>
                帳號沒有刪除，資料都還在。{remove.error instanceof ApiError ? remove.error.message : "請檢查網路後再試一次。"}
              </FieldError>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" disabled={remove.isPending} onClick={onClose}>
              取消
            </Button>
            <Button type="submit" variant="sign" disabled={!ready || remove.isPending}>
              {remove.isPending ? "刪除中…" : "永久刪除帳號"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
