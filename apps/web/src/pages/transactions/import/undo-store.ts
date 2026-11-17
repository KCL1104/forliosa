import { toast } from "sonner"
import { create } from "zustand"

/** 匯入的「復原」：要先問一次的那一批（以券商為準換掉了舊紀錄），和整批刪掉之後的通知 */

export interface PendingUndo {
  batchId: string
  /** 這次寫入幾筆 */
  count: number
  /** 以券商為準換掉的：名稱與舊紀錄的筆數 */
  replaced: { name: string; deleted: number }[]
}

export const useImportUndo = create<{ pending: PendingUndo | null; ask: (p: PendingUndo) => void; clear: () => void }>((set) => ({
  pending: null,
  ask: (pending) => set({ pending }),
  clear: () => set({ pending: null }),
}))

/** 以券商為準要換掉的：「台積電 3 筆」（確認框掛在 AppShell 上，這裡不引用確認表的檔案，主程式不多載） */
export function replacedText(list: { name: string; deleted: number }[]): string {
  return list.map((r) => `${r.name} ${r.deleted} 筆`).join("、")
}

/** 整批刪掉，通知結果（之後的賣出用到這批買進時，照後端的句子說） */
export function runUndo(mutateAsync: (batchId: string) => Promise<unknown>, batchId: string): void {
  void mutateAsync(batchId).then(
    () => toast("已復原這次匯入"),
    (err) => toast.error("沒有復原成功。", { description: err instanceof Error ? err.message : undefined }),
  )
}
