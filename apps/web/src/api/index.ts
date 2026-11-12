import { createHttpAdapter } from "./http"
import { createMockAdapter, readMockScenario } from "./mock/adapter"
import { readMockPolicy } from "./mock/commercial"
import { MOCK_TODAY } from "./mock/market"
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

export const api: ForliosaApi = baseUrl ? createHttpAdapter(baseUrl) : createMockAdapter({ scenario: readMockScenario(), policy: readMockPolicy() })

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

/** 「今天」：示範資料固定在 MOCK_TODAY（截圖與測試穩定），真實後端用台北時區的今天 */
export function appToday(): string {
  return api.kind === "mock" ? MOCK_TODAY : todayInTaipei()
}

export * from "./types"
