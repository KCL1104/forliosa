import { create } from "zustand"
import { createJSONStorage, persist } from "zustand/middleware"
import type { Delegation, UserRef } from "./types"

/**
 * 以唯讀身分查看別人的資產（授權查看，docs/api-contract.md「分享（M5）」）。
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
 * 查看者自己的端點不帶標頭：自己的資料（`/me`、顯示偏好）、登入，以及讀自己收到的授權（`GET /delegations`：
 * 查看中用來更新橫幅的範圍，授權者可能改了範圍或刪了帳戶）。授權的寫入照樣帶標頭（伺服器回 read_only）。
 * 其他請求一律帶上，讓伺服器的白名單把關（預設拒絕；萬一畫面漏擋了寫入，伺服器回 read_only）。
 */
export function sendsViewAs(path: string, method = "GET"): boolean {
  if (method.toUpperCase() === "GET" && /^\/delegations(\?|$)/.test(path)) return false
  return !/^\/(me|me\/preferences|auth\/[^?]*)(\?|$)/.test(path)
}

/** 帳本主人的稱呼：自己的帳本照原本寫「你」／「我」，查看別人的資產時換成授權者的名稱（「爸爸的成本」「只看爸爸的」） */
export function useWho(self: "你" | "我"): string {
  return useViewAs((s) => s.target?.owner.display_name ?? self)
}

/** 兩個查看對象的內容是否相同（橫幅只在授權者改了範圍、帳戶或名稱時更新） */
export function sameTarget(a: ViewAsTarget, b: ViewAsTarget): boolean {
  return (
    a.delegation_id === b.delegation_id &&
    a.scope === b.scope &&
    a.owner.display_name === b.owner.display_name &&
    a.owner.avatar_url === b.owner.avatar_url &&
    a.accounts.length === b.accounts.length &&
    a.accounts.every((x, i) => x.id === b.accounts[i]!.id && x.name === b.accounts[i]!.name)
  )
}
