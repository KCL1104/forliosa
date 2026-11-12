import { useQuery, useQueryClient, type Query, type QueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useEffect } from "react"
import { toast } from "sonner"
import { api } from "@/api"
import { sk } from "@/api/sharing-queries"
import { sameTarget, targetOf, useViewAs, useViewingAs, type ViewAsTarget } from "@/api/view-as"
import { ApiError, type Delegation } from "@/api/types"
import { useUi } from "./ui-store"

/** 查看範圍：全部帳戶，或列出授權的帳戶 */
export function scopeText(target: { scope: "all" | "accounts"; accounts: { name: string }[] }): string {
  return target.scope === "all" ? "全部帳戶" : target.accounts.map((a) => a.name).join("、") || "沒有帳戶"
}

/** 不讀使用者資料的查詢（行情、商品、自己的 /me）：切換查看對象時保留，其他全部丟掉重抓 */
const SHARED_KEYS = new Set(["me", "instrument", "quote", "history", "valuation", "revenue", "dividends", "search", "overview", "intraday", "chips", "financials", "news", "why", "meta", "auth"])
const userData = (q: Query) => !SHARED_KEYS.has(String(q.queryKey[0]))

/**
 * 進入或離開查看模式：先換標頭，再丟掉所有使用者資料的快取（兩個人的帳本不能混在同一個快取裡）。
 * 進行中的請求一併取消，舊身分的回應不會寫回快取。
 */
export function switchViewAs(qc: QueryClient, target: ViewAsTarget | null) {
  useViewAs.getState().set(target)
  useUi.getState().closeTradeForm()
  void qc.cancelQueries({ predicate: userData })
  qc.removeQueries({ predicate: userData })
}

/**
 * 查看中收到 403 `delegation_revoked`（授權被撤銷、不存在、或不是給我的）：退出查看模式、回到自己的帳本。
 * 回傳是否處理了（一次撤銷會讓好幾個請求同時失敗，只有第一個會通知）。
 */
export function exitOnRevoked(err: unknown, qc: QueryClient, goHome: () => void): boolean {
  if (!(err instanceof ApiError) || err.status !== 403 || err.code !== "delegation_revoked") return false
  const target = useViewAs.getState().target
  if (!target) return false
  switchViewAs(qc, null)
  goHome()
  toast(`${target.owner.display_name}的授權已經撤銷，已回到你的帳本`)
  return true
}

export function useViewAsControls() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  return {
    enter: (d: Delegation) => {
      switchViewAs(qc, targetOf(d))
      void navigate({ to: "/" })
    },
    exit: () => {
      switchViewAs(qc, null)
      void navigate({ to: "/" })
      toast("已回到你的帳本")
    },
  }
}

/**
 * 查看中：進入時存的是授權的快照，授權者之後可能改了範圍、刪了帳戶或改了名稱（伺服器的投影立即跟著變）。
 * 以查看者自己的身分讀 `GET /delegations`（不帶標頭，見 sendsViewAs），每分鐘一次，內容變了就更新橫幅。
 * 找不到這份授權（撤銷）時不在這裡處理：下一個帳本請求會收到 403 `delegation_revoked` 並退出查看模式。
 */
export function useSyncViewAsTarget() {
  const target = useViewingAs()
  const delegations = useQuery({
    enabled: target !== null,
    queryKey: sk.delegations,
    queryFn: () => api.listDelegations(),
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
  useEffect(() => {
    if (!target || !delegations.data) return
    const current = delegations.data.received.find((d) => d.id === target.delegation_id)
    if (!current) return
    const next = targetOf(current)
    if (!sameTarget(next, target)) useViewAs.getState().set(next)
  }, [target, delegations.data])
}
