import { useId, useState } from "react"
import { toast } from "sonner"
import { useReportDiscussion } from "@/api/discussion-queries"
import { REPORT_NOTE_MAX, REPORT_REASONS, type DiscussionTarget, type ReportReason } from "@/api/types"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { bodyProblem, charCount } from "@/lib/discussion-text"
import { REASON_LABEL, reportErrorText } from "./labels"

/**
 * 檢舉一則公開內容（`POST /discussions/reports`）。獨立的元件：只需要合約的 `target` 字串
 * （`topic:<id>`、`reply:<id>`），不依賴它出現在哪一頁；`what` 是標題裡的稱呼（「主題」「回覆」）。
 * 只在 `can_report` 是 true 的內容上打開（公開範圍、已登入、不是自己的）。
 * 理由四選一＋選填的補充說明（最多 300 字）；送出後通知「已收到檢舉」。同一人對同一則重複檢舉只算一次。
 */
export function ReportDialog({ target, what = "內容", onClose }: { target: DiscussionTarget; what?: string; onClose: () => void }) {
  const report = useReportDiscussion()
  const [reason, setReason] = useState<ReportReason | null>(null)
  const [note, setNote] = useState("")
  const [error, setError] = useState<string | null>(null)
  const id = useId()
  const submit = () => {
    if (report.isPending) return
    if (!reason) return setError("請選一個理由。")
    const noteBad = note.trim() ? bodyProblem(note, REPORT_NOTE_MAX, "補充說明") : null
    if (noteBad) return setError(noteBad)
    setError(null)
    report.mutate(
      { target, reason, ...(note.trim() ? { note: note.trim() } : {}) },
      {
        onSuccess: () => {
          toast.success("已收到檢舉")
          onClose()
        },
        onError: (err) => setError(reportErrorText(err)),
      },
    )
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-lg font-bold">檢舉這則{what}</DialogTitle>
          <DialogDescription>送出後由站方管理員查看。</DialogDescription>
        </DialogHeader>
        <form
          id={`${id}-form`}
          className="flex flex-col gap-5"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <fieldset>
            <legend className="mb-1.5 text-sm font-medium">理由</legend>
            <ul className="border-y border-rule">
              {REPORT_REASONS.map((r) => (
                <li key={r} className="border-b border-rule last:border-b-0">
                  <label className="flex min-h-11 cursor-pointer items-center gap-3 px-1 hover:bg-hov">
                    <input
                      type="radio"
                      name={`${id}-reason`}
                      value={r}
                      checked={reason === r}
                      onChange={() => {
                        setReason(r)
                        setError(null)
                      }}
                      className="size-4 accent-ink"
                    />
                    {REASON_LABEL[r]}
                  </label>
                </li>
              ))}
            </ul>
          </fieldset>
          <div className="flex flex-col gap-1.5">
            <div className="flex items-baseline justify-between gap-2">
              <label htmlFor={`${id}-note`} className="text-sm font-medium">
                補充說明（選填）
              </label>
              {charCount(note) > REPORT_NOTE_MAX - 50 && <span className="num text-sm text-ink-2">{`${charCount(note)}/${REPORT_NOTE_MAX}`}</span>}
            </div>
            <Textarea
              id={`${id}-note`}
              value={note}
              rows={2}
              onChange={(e) => setNote(e.target.value)}
              className="min-h-16 resize-none border-ctl bg-raised text-base md:text-base"
            />
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" variant="sign" form={`${id}-form`} disabled={report.isPending}>
            {report.isPending ? "送出中…" : "送出檢舉"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
