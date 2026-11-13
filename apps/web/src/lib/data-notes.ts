/**
 * 後端 `notes` 裡說「資料從哪一天開始／還沒有資料」的那一類（狀態，不是算法）：
 * 「資料從 2026/06/01 開始」「淨值資料從 2026/11/10 開始」「還沒有資料」。
 * 舊版後端的寫法（「資料累積中：自 … 起存檔」）也算，前後端分開部署時不會漏掉。
 */
export function isCoverageNote(note: string): boolean {
  return /^(淨值)?資料從 /.test(note) || note.startsWith("還沒有") || note.startsWith("資料累積中")
}
