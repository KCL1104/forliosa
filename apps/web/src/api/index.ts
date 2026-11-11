import { createHttpAdapter } from "./http"
import { createMockAdapter, readMockScenario } from "./mock/adapter"
import type { ForliosaApi } from "./types"

/**
 * 資料來源邊界：
 * - 設定 `VITE_API_BASE_URL` → 連真實後端（FastAPI，cookie session）
 * - 未設定 → 使用記憶體中的 mock adapter（全部標示 is_demo）
 * 頁面只透過 `api`（或 `./queries` 的 hooks）取資料，不直接 fetch。
 */
const baseUrl = import.meta.env.VITE_API_BASE_URL as string | undefined

export const api: ForliosaApi = baseUrl ? createHttpAdapter(baseUrl) : createMockAdapter({ scenario: readMockScenario() })

export * from "./types"
