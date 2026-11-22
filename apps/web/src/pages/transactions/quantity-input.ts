/**
 * 記一筆與持股的輸入共用的數量規則：以「張」或「股」填（記一筆的欄位旁有「張｜股」，預設照偏好；美股一律股）。
 * 台股以張填時最多寫到小數第三位（1 股），換成股數時四捨五入到整數——2.006 × 1000 在浮點數是 2005.9999…，
 * 不取整會被說「不是整數」；以股填時要是整數。
 * 也可以直接寫單位（產品負責人 2026-11-22）：「500股」「1張500股」「2張」不看欄位的單位，照寫的換成股數。
 */

/**
 * 輸入框的數字文字：全形（注音輸入法全形模式打的「２０」「１，２３４」「１２．５」）先換成半形，再拿掉千分位逗號與空白
 */
export const numberText = (s: string): string => s.normalize("NFKC").replace(/[,\s]/g, "")

/** 輸入框的文字 → 數字（可以有千分位逗號與空白、可以是全形）；空白或不是數字時是 null */
export const parseNumber = (s: string): number | null => {
  const n = Number(numberText(s))
  return s.trim() === "" || Number.isNaN(n) ? null : n
}

/** 台股的數量太細：以張填時超過小數第三位，以股填時不是整數 */
export const tooFine = (text: string, inLots: boolean): boolean => {
  const t = numberText(text)
  return inLots ? /\.\d{4,}$/.test(t) : /\.\d*[1-9]\d*$/.test(t)
}

/** 寫了單位的數量：「1張500股」「1張500」「500股」「2張」 */
const WITH_UNITS = /^(?:(\d+(?:\.\d+)?)張)?(?:(\d+(?:\.\d+)?)股?)?$/

/** 文字裡有沒有寫「張」或「股」（有的話照寫的單位，不看欄位的單位） */
export const hasUnit = (text: string): boolean => /[張股]/.test(text)

/** 寫了單位的文字拆成張與股（「1張500股」→ 1、500）；沒寫單位是 undefined，寫了但看不懂（「股」「500股2張」）是 null */
function unitParts(text: string): { lots: string; shares: string } | null | undefined {
  if (!hasUnit(text)) return undefined
  const m = WITH_UNITS.exec(numberText(text))
  return m && (m[1] || m[2]) ? { lots: m[1] ?? "", shares: m[2] ?? "" } : null
}

/** 填的數量換成股數（以張填時 × 1000 再取整；寫了單位的照寫的算） */
export const toShares = (text: string, inLots: boolean): number | null => {
  const u = unitParts(text)
  if (u === null) return null
  if (u) return Math.round(Number(u.lots || 0) * 1000) + Number(u.shares || 0)
  const q = parseNumber(text)
  return q === null ? null : inLots ? Math.round(q * 1000) : q
}

/** 股數 → 輸入框的文字（以張填時 1,500 股寫成 1.5） */
export const sharesText = (shares: number, inLots: boolean): string => (inLots ? String(Math.round(shares) / 1000) : String(shares))

/** 數量的錯誤（照欄位的單位寫：「請輸入張數」；美股沒有「張」） */
export function quantityError(text: string, inLots: boolean, us: boolean): string | null {
  const s = toShares(text, inLots)
  const u = unitParts(text)
  if (!s || s <= 0 || (us && u?.lots)) return `請輸入${inLots ? "張數" : "股數"}`
  if (us) return null
  const [lots, shares] = u ? [u.lots, u.shares] : inLots ? [text, ""] : ["", text]
  if (tooFine(lots, true)) return "張數最多寫到小數第三位（1 股）"
  if (tooFine(shares, false)) return "台股股數必須是整數"
  return null
}

/** 欄位下面另一種單位的換算（「2,000 股」「2 張」）：只在有幫助的時候寫；寫了單位的一律換成股數（「1張500股」→「1,500 股」） */
export function otherUnit(shares: number | null, inLots: boolean, us: boolean, text = ""): string | null {
  if (!shares || us) return null
  if (inLots || hasUnit(text)) return `${new Intl.NumberFormat("zh-TW").format(shares)} 股`
  return shares >= 1000 && shares % 1000 === 0 ? `${shares / 1000} 張` : null
}
