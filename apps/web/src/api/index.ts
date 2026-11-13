import { createHttpAdapter } from "./http"
import { createMockAdapter, readMockDiscussion, readMockScenario, readMockSignedIn } from "./mock/adapter"
import { readMockPolicy } from "./mock/commercial"
import { mockMarketNow, mockToday, readMockMarket } from "./mock/market-status"
import { todayInTaipei } from "@/lib/format"
import type { ForliosaApi } from "./types"

/**
 * 資料來源邊界：
 * - 設定 `VITE_API_BASE_URL` → 連真實後端（FastAPI，cookie session）。正式環境填 `https://api.<網域>`。
 * - `pnpm dev:api`（vite --mode api）且沒有設定 → 同源 `/api/v1`，由 Vite dev proxy 轉給
 *   http://localhost:8000，cookie 是同源的，不需要 CORS。
 * - 其他情況 → 使用記憶體中的 mock adapter：預設模擬商用模式（和後端 `DATA_POLICY=commercial` 一樣沒有示範標記、
 *   存檔不足處回空＋notes）；`?policy=personal` 改回全部標示 is_demo 的示範資料
 * 頁面只透過 `api`（或 `./queries` 的 hooks）取資料，不直接 fetch。
 */
const configured = import.meta.env.VITE_API_BASE_URL?.trim()
const baseUrl = configured || (import.meta.env.MODE === "api" ? "/api/v1" : undefined)

const mockMarket = baseUrl ? undefined : readMockMarket()

export const api: ForliosaApi = baseUrl
  ? createHttpAdapter(baseUrl)
  : createMockAdapter({ scenario: readMockScenario(), policy: readMockPolicy(), signedIn: readMockSignedIn(), market: mockMarket, discussion: readMockDiscussion() })

/** 真實後端的 base URL（mock 模式為 undefined）；AI 對話的 SSE 串流直接用它 */
export const apiBaseUrl: string | undefined = baseUrl

/**
 * 開發登入（`POST /auth/dev-login`，後端只在 FORLIOSA_ENV=dev 開放）：
 * - `auto`：開發模式連真實後端時，沒有 session 就自動以示範使用者登入
 * - `form`：401 畫面是否顯示開發登入表單
 * TODO(auth): 正式登入（Email magic link、Google）完成後，401 畫面改成正式登入入口。
 */
export const DEV_LOGIN = {
  auto: api.kind === "http" && import.meta.env.DEV,
  form: api.kind === "http" && (import.meta.env.DEV || import.meta.env.VITE_ENABLE_DEV_LOGIN === "true"),
  email: import.meta.env.VITE_DEV_LOGIN_EMAIL?.trim() || "demo@forliosa.local",
} as const

/**
 * 「今天」：示範資料固定在 MOCK_TODAY（截圖與測試穩定），真實後端用台北時區的今天。
 * 示範資料的 `?market=open|pending` 是最後一個收盤日的下一個交易日（和 mock 的 `GET /meta/market-status` 同一天）。
 */
export function appToday(): string {
  return api.kind === "mock" ? mockToday(mockMarket) : todayInTaipei()
}

/**
 * 「現在」：示範資料固定在 MOCK_AS_OF（「N 小時前」在截圖與測試中穩定），真實後端用目前時間。
 * 示範資料跟著 `?market=` 的情境（`open` 是下一個交易日早上、`pending` 是那天下午）。
 */
export function appNow(): Date {
  return api.kind === "mock" ? mockMarketNow(mockMarket) : new Date()
}

/** 判斷「盤中／收盤後還沒公布」用的現在時間：和 `appNow` 同一個時鐘（示範資料與 mock 的 `GET /meta/market-status` 一致） */
export function marketNow(): Date {
  return appNow()
}

export * from "./types"
