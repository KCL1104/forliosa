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

export const accumulatingNote = (since = ARCHIVE_START) => `資料累積中：自 ${since} 起存檔`
export const US_NOTE = "美股目前沒有可商用的行情來源，不提供價格資料"
export const INTRADAY_NOTE = "目前沒有授權的盤中行情來源（證交所即時／延遲行情需付費授權），不提供分時走勢"
export const TWSE_CHIPS_NOTE = "證交所 OpenAPI 沒有上市股票的個股三大法人（證交所以付費商品提供），目前不提供；外資持股只公布持股比率前 20 名；上櫃股票由櫃買中心 OpenAPI 每日存檔"
export const TOP20_NOTE = "證交所只公布外資持股比率前 20 名，本股只有名列前 20 名的日子才有外資持股比"
export const INDEX_NOTE = "發行量加權股價報酬指數目前沒有可商用的來源，暫時無法比較"

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
