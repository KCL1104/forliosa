import { useState } from "react"
import { useDeleteTransactionBatch } from "@/api/queries"
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
import { replacedText, runUndo, useImportUndo } from "./undo-store"

/**
 * 匯入的「復原」：整批刪掉這次寫入的買賣（`DELETE /transactions/batches/{id}`）。
 * 匯入庫存選了「換成券商」的，被換掉的舊紀錄回不來：按「復原」先問一次，照實說哪幾檔的幾筆不會回來、
 * 復原之後那幾檔在這個帳戶就沒有了（不假裝能還原）。
 * 確認框掛在 ImportHost（匯入的對話框關掉之後通知還在，按了才出現）。關掉時有 150ms 的淡出：內文照最後一次的內容畫，
 * 不會在淡出時閃成「0 筆買進」「舊紀錄（）」。
 */

export function UndoConfirm() {
  const pending = useImportUndo((s) => s.pending)
  const clear = useImportUndo((s) => s.clear)
  const undo = useDeleteTransactionBatch()
  const [shown, setShown] = useState(pending)
  if (pending !== null && pending !== shown) setShown(pending)
  const replaced = shown?.replaced ?? []
  const text = `會刪掉這次記的 ${shown?.count ?? 0} 筆買進。換成券商刪掉的舊紀錄（${replacedText(replaced)}）不會回來：復原之後，這個帳戶裡就沒有${replaced.map((r) => r.name).join("、")}了，要的話得自己再記。`
  return (
    <AlertDialog open={pending !== null} onOpenChange={(o) => !o && clear()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>復原這次匯入？</AlertDialogTitle>
          <AlertDialogDescription>{text}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>不復原</AlertDialogCancel>
          <AlertDialogAction
            onClick={() => {
              if (!pending) return
              clear()
              runUndo(undo.mutateAsync, pending.batchId)
            }}
          >
            復原
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
