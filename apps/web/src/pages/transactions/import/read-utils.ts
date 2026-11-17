import { ApiError, type ImportPage } from "@/api/types"
import { useAiUsage } from "@/ai/remote-hooks"
import type { AiUsage } from "@/ai/remote"
import { ImageReadError } from "./prepare-image"

/** 匯入庫存與匯入對帳單共用的規則：選好的截圖、錯誤的一句話、今天還剩幾次 */

/** 選好的一張截圖：準備好的圖（切塊、轉 JPEG）或打不開的原因 */
export interface PickedImage {
  id: number
  file: File
  pages?: ImportPage[]
  error?: string
}

export const isAbort = (e: unknown) => e instanceof DOMException && e.name === "AbortError"

/** 截圖打不開的一句話（`pdf`：這裡收不收 PDF——匯入庫存不收，不能說「只收 PDF、…」） */
export function imageError(e: unknown, { pdf = true }: { pdf?: boolean } = {}): string {
  if (e instanceof ImageReadError) {
    if (e.reason === "heic") return "這張是 HEIC 格式，這個瀏覽器讀不了。請改存成 JPEG，或改用截圖。"
    if (e.reason === "unsupported") return pdf ? "只收 PDF、JPEG、PNG、WebP。" : "只收 JPEG、PNG、WebP 的截圖。"
  }
  return "這張圖打不開。"
}

/**
 * 讀檔失敗時的一句話（伺服器的句子照原文；沒有句子的照狀態碼說）。
 * `what`：匯入的是什麼（「對帳單」「庫存」）；`kept`：還留著的東西（「檔案」「截圖」「文字」）
 */
export function readError(e: unknown, what: "對帳單" | "庫存" = "對帳單", kept = "檔案"): string {
  if (e instanceof ApiError) {
    if (!e.code.startsWith("http_")) return e.message
    if (e.status === 413) return what === "庫存" ? "截圖太大。少選幾張再試。" : "檔案太大。PDF 分開匯入，或少選幾張截圖。"
    if (e.status === 403) return `這個帳號還不能匯入${what}。`
    if (e.status === 503) return "AI 暫時無法使用，等一下再試。"
    if (e.status === 429) return "今天的匯入次數用完了，明天再試。"
    return `沒有讀成功（${e.status}），${kept}還在，再試一次。`
  }
  return `沒有連上伺服器，${kept}還在，再試一次。`
}

/** 今天還可以匯入幾次（兩種匯入合計；後端沒說就是 null） */
export function useImportsLeft(): { left: number | null; limit: number | null } {
  const usage = useAiUsage().data as (AiUsage & { imports_today?: number; import_daily_limit?: number }) | undefined
  const limit = usage?.import_daily_limit ?? null
  const left = limit !== null && usage?.imports_today != null ? Math.max(limit - usage.imports_today, 0) : null
  return { left, limit }
}

/** 一張截圖的狀態：「1 張」「切成 3 張」「讀取中…」 */
export const imageStatus = (x: PickedImage) => (x.error ? null : x.pages ? (x.pages.length > 1 ? `切成 ${x.pages.length} 張` : "1 張") : "讀取中…")
