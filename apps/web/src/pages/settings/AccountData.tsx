import { useMutation } from "@tanstack/react-query"
import { useId, useState } from "react"
import { toast } from "sonner"
import { api } from "@/api"
import { ACCOUNT_DELETE_CONFIRMATION, ApiError } from "@/api/types"
import { useReadOnly } from "@/api/view-as"
import { useUi } from "@/app/ui-store"
import { FieldError } from "@/components/form-field"
import { Section } from "@/components/section"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { hardNavigate } from "@/lib/hard-nav"
import { clearLocalUserData } from "@/lib/local-data"
import { LegalLinks } from "@/pages/legal/LegalLinks"
import { exportErrorText, useExportMe } from "./export-me"

/**
 * 設定頁最下面的「帳號與資料」：匯出我的資料、服務條款與隱私權政策、清除所有持倉、刪除帳號。
 * 列的樣子和設定頁其他區塊相同（標題＋一句說明在左、動作在右）；這裡的動作都是外框按鈕——
 * 匯出只是下載一個檔，清除與刪除要到對話框裡輸入一句話才會真的執行。查看別人的資產時不出現（這些是自己帳號的事）。
 * 清除所有持倉（產品負責人 2026-11-17）的確認框掛在 AppShell（`ClearRecordsHost`）：帳本的「自訂」也打得開。
 */
export function AccountData() {
  const readOnly = useReadOnly()
  const [deleting, setDeleting] = useState(false)
  const openClear = useUi((s) => s.openClearRecords)
  const exportMe = useExportMe(() => toast.success("已下載匯出檔"))
  if (readOnly) return null
  return (
    <Section id="account" title="帳號與資料" titleId="set-account" bodyClassName="pt-0" className="scroll-mt-20">
      <div className="flex flex-col divide-y divide-rule border-b border-rule">
        <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
          <div className="min-w-0">
            <p className="font-medium">匯出我的資料</p>
            <p className="mt-0.5 text-base text-ink">下載一個 JSON 檔：個人資料、券商帳戶與交易、定期定額、觀察清單、AI 對話，以及你在群組與討論裡寫的內容。</p>
            {exportMe.isError && <FieldError className="mt-1.5">{exportErrorText(exportMe.error)}</FieldError>}
          </div>
          <Button variant="outline" className="shrink-0 self-start sm:self-auto" disabled={exportMe.isPending} onClick={() => exportMe.mutate()}>
            {exportMe.isPending ? "準備中…" : "匯出"}
          </Button>
        </div>
        <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
          <div className="min-w-0">
            <p className="font-medium">條款與隱私</p>
          </div>
          <p className="flex shrink-0 flex-wrap gap-x-5">
            <LegalLinks className={textAction} />
          </p>
        </div>
        <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
          <div className="min-w-0">
            <p className="font-medium">清除所有持倉</p>
            <p className="mt-0.5 text-base text-ink">刪掉一個帳戶或全部帳戶的每一筆紀錄，帳戶留著，可以重新記。</p>
          </div>
          <Button
            variant="outline"
            className="shrink-0 self-start sm:self-auto"
            onClick={(e) => {
              // 剛按過「匯出」的通知還在的話先收掉：不要蓋在對話框上
              toast.dismiss()
              openClear(e.currentTarget)
            }}
          >
            清除…
          </Button>
        </div>
        <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
          <div className="min-w-0">
            <p className="font-medium">刪除帳號</p>
            <p className="mt-0.5 text-base text-ink">帳本、AI 對話與個人資料會全部刪除，不能復原。要留一份的話，先匯出。</p>
          </div>
          <Button
            variant="outline"
            className="shrink-0 self-start sm:self-auto"
            onClick={() => {
              // 剛按過「匯出」的通知還在的話先收掉：不要蓋在對話框上
              toast.dismiss()
              setDeleting(true)
            }}
          >
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
            <DialogDescription>刪除之後不能復原，同一個 Google 或 Discord 帳號再登入會是全新的帳號。</DialogDescription>
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
                <li>你在群組寫的留言、在討論寫的主題與回覆，作者會顯示成「已刪除的帳號」。不想留的話，先刪掉它們再刪帳號。</li>
                <li>你擁有的群組會轉給最早的管理員或成員；沒有其他成員的群組會一起刪除。</li>
              </ul>
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={id} className="print-label text-sm">
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
