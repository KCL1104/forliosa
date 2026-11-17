import { useId, useState } from "react"
import { toast } from "sonner"
import { useAddCorrection } from "@/api/discussion-queries"
import { ApiError, type MarketReport } from "@/api/types"
import { FieldError } from "@/components/form-field"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"

const NOTE_MAX = 200

/**
 * 站方管理員更正一份報告（`POST /admin/market-reports/<id>/corrections`）：報告最下面一個文字動作「更正這一份」，
 * 打開後寫更正說明（1–200 字），再勾要換掉的部分——AI 寫的標題與重點換回規則寫的版本，AI 段落拿掉（只留伺服器的圖表）。
 * 送出後頁面上方多一行「已更正（時間）：說明」。只有管理員看得到這個動作。
 */
export function ReportCorrection({ report }: { report: MarketReport }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="max-w-[46rem]">
      <button type="button" className={textAction} onClick={() => setOpen(true)}>
        更正這一份
      </button>
      {open && <CorrectionDialog report={report} onClose={() => setOpen(false)} />}
    </div>
  )
}

function CorrectionDialog({ report, onClose }: { report: MarketReport; onClose: () => void }) {
  const add = useAddCorrection()
  const id = useId()
  const [note, setNote] = useState("")
  const [picked, setPicked] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const parts = [
    ...(report.title_origin === "ai" ? [{ key: "title", label: "標題（換回規則寫的）" }] : []),
    ...(report.highlights_origin === "ai" ? [{ key: "highlights", label: "重點（換回規則寫的）" }] : []),
    ...report.sections.filter((s) => s.origin === "ai" && !s.dropped).map((s) => ({ key: s.key, label: `${s.title}（拿掉 AI 段落）` })),
  ]
  const submit = () => {
    if (add.isPending) return
    const text = note.trim()
    if (!text) return setError("請寫更正說明。")
    if (text.length > NOTE_MAX) return setError(`更正說明最多 ${NOTE_MAX} 字。`)
    setError(null)
    add.mutate(
      { id: report.id, note: text, drop_sections: picked },
      {
        onSuccess: () => {
          toast.success("已更正")
          onClose()
        },
        onError: (err) => setError(err instanceof ApiError ? err.message : "請檢查網路後再試一次。"),
      },
    )
  }
  return (
    <Dialog open onOpenChange={(o) => !o && !add.isPending && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>更正這一份報告</DialogTitle>
          <DialogDescription>
            {report.kind_label} {report.edition_label}。報告上方會多一行「已更正（時間）：說明」。
          </DialogDescription>
        </DialogHeader>
        <form
          id={`${id}-form`}
          className="flex flex-col gap-5"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${id}-note`} className="text-sm font-medium">
              更正說明
            </label>
            <Textarea
              id={`${id}-note`}
              value={note}
              rows={2}
              maxLength={NOTE_MAX}
              onChange={(e) => setNote(e.target.value)}
              className="min-h-16 resize-none border-ctl bg-raised text-base md:text-base"
            />
          </div>
          {parts.length > 0 && (
            <fieldset>
              <legend className="mb-1.5 text-sm font-medium">要換掉的部分（可以不選）</legend>
              <ul className="border-y border-rule">
                {parts.map((p) => (
                  <li key={p.key} className="border-b border-rule last:border-b-0">
                    <label className="flex min-h-11 cursor-pointer items-center gap-3 px-1 hover:bg-hov">
                      <input
                        type="checkbox"
                        value={p.key}
                        checked={picked.includes(p.key)}
                        onChange={(e) => setPicked((x) => (e.target.checked ? [...x, p.key] : x.filter((k) => k !== p.key)))}
                        className="size-4 accent-ink"
                      />
                      {p.label}
                    </label>
                  </li>
                ))}
              </ul>
            </fieldset>
          )}
          {error && <FieldError>{error}</FieldError>}
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={add.isPending}>
            取消
          </Button>
          <Button type="submit" variant="sign" form={`${id}-form`} disabled={add.isPending}>
            {add.isPending ? "送出中…" : "送出更正"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
