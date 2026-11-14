import type { Instrument } from "@/api/types"

/**
 * 本機規則（記帳指令、畫圖、只輸入代號、mock 的深度搜尋）從搜尋結果挑出使用者說的那一檔。
 *
 * 1. 代號完全相同（不分大小寫；`BRK.B` 等於 SEC 寫法的 `BRK-B`）
 * 2. 名稱完全相同（不分大小寫：apple → Apple）
 * 3. 其餘取第一筆，但英文字只會落在台股：商品清單有 SEC 的一萬多檔美股（只有英文名），
 *    句子裡的英文縮寫不能因為名稱「部分相同」就變成某一檔美股。中文字搜不到 SEC 的美股（後端只用英文查它們），
 *    所以「輝達」照樣對到 NVDA。
 */
export function pickInstrument(target: string, results: Instrument[]): Instrument | null {
  const q = target.trim()
  const upper = q.toUpperCase()
  const dashed = upper.replace(/\./g, "-")
  const english = /^[\x20-\x7e]+$/.test(q)
  return (
    results.find((i) => [i.code.toUpperCase(), i.symbol.toUpperCase()].some((c) => c === upper || c === dashed)) ??
    results.find((i) => i.name === q || i.name.toUpperCase() === upper) ??
    results.find((i) => !english || i.market !== "US") ??
    null
  )
}
