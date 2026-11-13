/**
 * mock 的資料政策（與後端 `DATA_POLICY` 對應）：
 * - `commercial`（預設，和後端一樣）：沒有示範標記（`is_demo: false`）；存檔不足的地方回空資料＋`notes`，
 *   文字與後端相同（apps/api/src/forliosa/services/coverage.py）。
 * - `personal`：舊的示範資料（全部標示 `is_demo`），網址 `?policy=personal` 切換。
 * mock 本身仍是瀏覽器裡產生的模擬數字；設定頁「關於資料」會說明。
 */
export type MockPolicy = "commercial" | "personal"

/** 示範的「自建存檔」從這天開始：之前的日線、本益比、籌碼與績效都沒有 */
export const ARCHIVE_START = "2026-06-01"

/** 和後端 `coverage.ymd` 一樣：說明裡的日期寫成 2026/06/01 */
export const ymd = (iso: string) => iso.replaceAll("-", "/")
export const accumulatingNote = (since = ARCHIVE_START) => `資料從 ${ymd(since)} 開始`
export const US_NOTE = "美股沒有報價"
export const INTRADAY_NOTE = "沒有盤中走勢，價格是收盤後公布的收盤價"
export const TWSE_CHIPS_NOTE = "上市股票沒有逐檔三大法人資料；外資持股只公布前 20 名"
/** 名列外資持股前 20 名的上市股票：同樣說明為什麼沒有三大法人，但不含外資持股那一句 */
export const TWSE_INST_NOTE = "上市股票沒有逐檔三大法人資料"
export const TOP20_NOTE = "外資持股只公布前 20 名，這檔只有名列前 20 名的日子才有外資持股比"
export const INDEX_NOTE = "沒有 發行量加權股價報酬指數 的資料，不能比較"

export function readMockPolicy(): MockPolicy {
  if (typeof window === "undefined") return "commercial"
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("policy")
    if (fromUrl === "commercial" || fromUrl === "personal") {
      window.sessionStorage.setItem("forliosa:policy", fromUrl)
      return fromUrl
    }
    if (window.sessionStorage.getItem("forliosa:policy") === "personal") return "personal"
  } catch {
    // sessionStorage 不可用：用預設
  }
  return "commercial"
}
