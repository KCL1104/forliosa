/**
 * 後端 `notes` 裡說「資料從哪一天開始／還沒有資料」的那一類（狀態，不是算法）：
 * 「資料從 2026/06/01 開始」「淨值資料從 2026/11/10 開始」「還沒有資料」。
 * 舊版後端的寫法（「資料累積中：自 … 起存檔」）也算，前後端分開部署時不會漏掉。
 */
export function isCoverageNote(note: string): boolean {
  return /^(淨值)?資料從 /.test(note) || note.startsWith("還沒有") || note.startsWith("資料累積中")
}

/**
 * 後端說「… 以前用 Yahoo 參考價計算，不是官方資料」的那一句：存檔開始以前的日子用 Yahoo 回補換算成當時成交價算
 * （績效、排行、AI 圖卡的 `notes`；產品負責人 2026-11-18）
 */
export function isReferenceNote(note: string): boolean {
  return /以前用 Yahoo 參考價計算/.test(note)
}

/**
 * 後端說「元大台灣50在 2026/11/11 以前只算價格，不含股利」的那一句：股票基準在存檔開始以前沒有除息資料，
 * 那段只算價格（2026-11-18 審查）。有這句時不寫「基準含股利」
 */
export function isPriceOnlyNote(note: string): boolean {
  return note.endsWith("以前只算價格，不含股利")
}
