import { useMe } from "@/api/queries"
import { useReadOnly } from "@/api/view-as"

/**
 * 匯入（匯入庫存、匯入對帳單）的入口要不要出現：`/me` 的 `plan.statement_import` 明確是 true（後端的 IMPORT_STATEMENTS；
 * 2026-11-17 起預設所有登入的帳號都有，第一版只開給站方管理員；兩種匯入同一個開關），而且不是在查看別人的資產（查看中一律唯讀）。
 */
export function useCanImport(): boolean {
  const me = useMe()
  const readOnly = useReadOnly()
  return !readOnly && me.data?.plan?.statement_import === true
}
