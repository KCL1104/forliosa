import { create } from "zustand"
import { createJSONStorage, persist } from "zustand/middleware"
import type { Delegation, UserRef } from "./types"

/**
 * 以唯讀身分查看別人的資產（授權查看，docs/m5-sharing-contract.md）。
 * 查看中 API client 在請求加上 `X-Forliosa-View-As: <delegation_id>`；伺服器以路由白名單決定能讀什麼，
 * 寫入一律 403 `read_only`，授權失效 403 `delegation_revoked`（前端退出查看模式，見 main.tsx）。
 *
 * 狀態存在 sessionStorage：重新整理還在查看，另開分頁、關掉分頁就回到自己的帳本。
 */
export const VIEW_AS_HEADER = "X-Forliosa-View-As"

export interface ViewAsTarget {
  delegation_id: string
  owner: UserRef
  scope: Delegation["scope"]
  accounts: Delegation["accounts"]
}

interface ViewAsState {
  target: ViewAsTarget | null
  set: (target: ViewAsTarget | null) => void
}

export const useViewAs = create<ViewAsState>()(
  persist((set) => ({ target: null, set: (target) => set({ target }) }), {
    name: "forliosa:view-as",
    version: 1,
    storage: createJSONStorage(() => sessionStorage),
    partialize: ({ target }) => ({ target }),
  }),
)

/** 目前查看中的對象（React hook）；沒有查看時為 null */
export const useViewingAs = () => useViewAs((s) => s.target)
/** 查看模式＝唯讀：隱藏記一筆、加入觀察、AI 等動作 */
export const useReadOnly = () => useViewAs((s) => s.target !== null)

/** 目前查看中的授權 id（沒有查看時為 null） */
export function viewAsId(): string | null {
  return useViewAs.getState().target?.delegation_id ?? null
}

export function targetOf(d: Delegation): ViewAsTarget {
  return { delegation_id: d.id, owner: d.owner, scope: d.scope, accounts: d.accounts }
}

/**
 * 查看者自己的端點不帶標頭：自己的資料（`/me`、顯示偏好）與登入。
 * 其他請求一律帶上，讓伺服器的白名單把關（預設拒絕；萬一畫面漏擋了寫入，伺服器回 read_only）。
 */
export function sendsViewAs(path: string): boolean {
  return !/^\/(me|me\/preferences|auth\/[^?]*)(\?|$)/.test(path)
}
