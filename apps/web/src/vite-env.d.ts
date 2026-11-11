/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 後端 API 位址，例如 https://api.forliosa.app；未設定時使用 mock 示範資料 */
  readonly VITE_API_BASE_URL?: string
}
interface ImportMeta {
  readonly env: ImportMetaEnv
}
