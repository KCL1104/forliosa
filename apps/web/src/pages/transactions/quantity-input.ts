/**
 * 記一筆與持股的輸入共用的數量規則：照偏好以「張」或「股」填（美股一律股）。
 * 台股以張填時最多寫到小數第三位（1 股），換成股數時四捨五入到整數——2.006 × 1000 在浮點數是 2005.9999…，
 * 不取整會被說「不是整數」；以股填時要是整數。
 */

/** 輸入框的文字 → 數字（可以有千分位逗號與空白）；空白或不是數字時是 null */
export const parseNumber = (s: string): number | null => {
  const n = Number(s.replace(/[,\s]/g, ""))
  return s.trim() === "" || Number.isNaN(n) ? null : n
}

/** 台股的數量太細：以張填時超過小數第三位，以股填時不是整數 */
export const tooFine = (text: string, inLots: boolean): boolean => {
  const t = text.replace(/[,\s]/g, "")
  return inLots ? /\.\d{4,}$/.test(t) : /\.\d*[1-9]\d*$/.test(t)
}

/** 填的數量換成股數（以張填時 × 1000 再取整） */
export const toShares = (text: string, inLots: boolean): number | null => {
  const q = parseNumber(text)
  return q === null ? null : inLots ? Math.round(q * 1000) : q
}

/** 股數 → 輸入框的文字（以張填時 1,500 股寫成 1.5） */
export const sharesText = (shares: number, inLots: boolean): string => (inLots ? String(Math.round(shares) / 1000) : String(shares))

/** 數量的錯誤（照欄位的單位寫：「請輸入張數」） */
export function quantityError(text: string, inLots: boolean, us: boolean): string | null {
  const s = toShares(text, inLots)
  if (!s || s <= 0) return `請輸入${inLots ? "張數" : "股數"}`
  if (!us && tooFine(text, inLots)) return inLots ? "張數最多寫到小數第三位（1 股）" : "台股股數必須是整數"
  return null
}

/** 欄位下面另一種單位的換算（「2,000 股」「2 張」）：只在有幫助的時候寫 */
export function otherUnit(shares: number | null, inLots: boolean, us: boolean): string | null {
  if (!shares || us) return null
  if (inLots) return `${new Intl.NumberFormat("zh-TW").format(shares)} 股`
  return shares >= 1000 && shares % 1000 === 0 ? `${shares / 1000} 張` : null
}
