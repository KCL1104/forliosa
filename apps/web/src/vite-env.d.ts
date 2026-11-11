/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * 後端 API 位址：根網址（https://api.example.com，會自動加 /api/v1）、完整的 …/api/v1，
   * 或同源路徑 /api/v1（`pnpm dev:api` 透過 Vite proxy 時的預設）。未設定且不是 api 模式時使用 mock 示範資料。
   */
  readonly VITE_API_BASE_URL?: string
  /** 非開發建置（例如 staging）也顯示「開發登入」表單；後端必須是 FORLIOSA_ENV=dev 才會成功 */
  readonly VITE_ENABLE_DEV_LOGIN?: string
  /** 開發模式自動登入用的 Email（預設 demo@forliosa.local，即 `python -m forliosa.seed` 建立的示範使用者） */
  readonly VITE_DEV_LOGIN_EMAIL?: string
}
interface ImportMeta {
  readonly env: ImportMetaEnv
}
