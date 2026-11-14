import { ApiError, type AdminDataset, type AdminOverview, type BlockDomainResult, type BlockedDomain } from "../types"
import { datasetRows } from "./attributions"
import { mockMediaUrls } from "./research"

/**
 * 管理後台的示範版（和後端 `services/admin.py` 同一套規則）：
 * - 總覽：使用者只有人數；金鑰槽只有狀態與本月用量（沒有金鑰）；資料集是最久沒有新資料的在前，落後 3 個交易日以上標 `stale`。
 * - 新聞下架：網域正規化（小寫、去掉 www.、從網址取主機）；封鎖會刪掉那個網域與子網域已存的標題（示範報導都在 example.com）；
 *   寫在伺服器設定的不能在這裡解除（409）。
 * 呼叫的人不是站方管理員 → 404（`requireAdmin` 由 adapter 給，和討論串的站方管理同一個判斷）。
 */
export interface AdminDeps {
  requireAdmin(): void
}

// 示範資料的「今天」是 2026-11-12（四）：每天的資料停在 11/11，兩個資料集比較舊
const FETCHED = "2026-11-12T06:10:00+08:00"
const LATE: Record<string, { data_date: string; days_behind: number; fetched_at?: string }> = {
  "tdcc-opendata/distribution": { data_date: "2026-11-06", days_behind: 6 },
  "twse-openapi/esg_products": { data_date: "2026-10-29", days_behind: 14, fetched_at: "2026-11-11T06:10:00+08:00" },
}

/** 寫在伺服器設定（NEWS_BLOCKED_DOMAINS）的示範網域 */
const ENV_BLOCKED = ["sample-wire.example"]

const DOMAIN_RE = /^[^\s./:@]+(\.[^\s./:@]+)+$/

/** 後端 `normalize_domain`：小寫、網址只取主機、去掉 www. 與頭尾的點 */
export function normalizeDomain(raw: string): string {
  let d = raw.trim().toLowerCase()
  if (d.includes("://")) {
    try {
      d = new URL(d).hostname
    } catch {
      d = ""
    }
  }
  return d.replace(/^www\./, "").replace(/^\.+|\.+$/g, "").split("/")[0]!
}

const hostOf = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, "")
  } catch {
    return ""
  }
}
/** 子網域也算（money.udn.com 在 udn.com 底下） */
const onDomain = (host: string, domain: string) => host === domain || host.endsWith(`.${domain}`)

function datasets(): AdminDataset[] {
  const rows: AdminDataset[] = datasetRows().map(([key, agency, name]) => {
    const late = LATE[key]
    return {
      key, name, agency,
      data_date: late?.data_date ?? "2026-11-11",
      fetched_at: late?.fetched_at ?? FETCHED,
      days_behind: late?.days_behind ?? 1,
      stale: !!late,
    }
  })
  rows.push({ key: "yahoo-history/price", name: "Yahoo Finance（歷史日線，非官方資料）", agency: null, data_date: "2026-11-11", fetched_at: FETCHED, days_behind: 1, stale: false })
  // 最久沒有新資料的在前（日期相同時依 key）
  return rows.sort((a, b) => (a.data_date ?? "").localeCompare(b.data_date ?? "") || a.key.localeCompare(b.key))
}

export function createAdminStore(deps: AdminDeps) {
  const stored = new Map<string, { reason: string | null; created_at: string }>([
    ["demo-press.example", { reason: "11/10 來信要求下架", created_at: "2026-11-10T15:20:00+08:00" }],
  ])
  /** 已經刪掉的示範報導（封鎖後不再出現在個股頁的新聞，再封鎖一次也不會再算一次） */
  const deleted = new Set<string>()
  const blocked = () => [...stored.keys(), ...ENV_BLOCKED]

  return {
    /** 個股頁的新聞：封鎖中的網域、封鎖時刪掉的報導不出現（解除封鎖也不會回來，和後端一樣） */
    hides(url: string): boolean {
      const host = hostOf(url)
      return deleted.has(url) || (!!host && blocked().some((d) => onDomain(host, d)))
    },

    overview(): AdminOverview {
      deps.requireAdmin()
      return {
        users: { total: 14, new_7d: 3 },
        ai: {
          month: "2026-11",
          slots: [
            { slot: 1, configured: true, state: "ok", retry_in_seconds: null, workspace_id: "wrkspc_01JD7Q2M4X8V", month_cost_usd: 3.8412, month_calls: 1284, monthly_budget_usd: 50, threads: 41, last_error: null },
            { slot: 2, configured: true, state: "cooling", retry_in_seconds: 38, workspace_id: "wrkspc_01JD7Q9K2B5N", month_cost_usd: 2.9077, month_calls: 966, monthly_budget_usd: 50, threads: 33, last_error: "429 rate_limit_error" },
            { slot: 3, configured: false, state: "not_configured", retry_in_seconds: null, workspace_id: null, month_cost_usd: 0, month_calls: 0, monthly_budget_usd: null, threads: 0, last_error: null },
          ],
        },
        datasets: datasets(),
        history_backfill: { enabled: true, rows: 1_843_220, pending: 12, symbols: { done: 1702, not_found: 37, mismatch: 9, no_overlap: 4, error: 0 } },
      }
    },

    list(): BlockedDomain[] {
      deps.requireAdmin()
      const rows = [...stored.entries()]
        .map(([domain, r]) => ({ domain, reason: r.reason, created_at: r.created_at, from_env: ENV_BLOCKED.includes(domain) }))
        .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.domain.localeCompare(a.domain))
      const env = ENV_BLOCKED.filter((d) => !stored.has(d)).sort().map((domain) => ({ domain, reason: null, created_at: null, from_env: true }))
      return [...rows, ...env]
    },

    block(body: { domain: string; reason?: string }, now: Date): BlockDomainResult {
      deps.requireAdmin()
      const domain = normalizeDomain(body.domain)
      if (!DOMAIN_RE.test(domain) || domain.length > 253) throw new ApiError(422, "validation_error", "請輸入網域，例如 example.com。")
      const reason = body.reason?.trim() || null
      if (reason && reason.length > 200) throw new ApiError(422, "validation_error", "原因最多 200 個字")
      const prev = stored.get(domain)
      if (!prev) stored.set(domain, { reason, created_at: taipeiIso(now) })
      else if (reason) prev.reason = reason
      const gone = mockMediaUrls().filter((url) => !deleted.has(url) && onDomain(hostOf(url), domain))
      for (const url of gone) deleted.add(url)
      return { domain, deleted_headlines: gone.length }
    },

    unblock(raw: string): void {
      deps.requireAdmin()
      const domain = normalizeDomain(raw)
      if (ENV_BLOCKED.includes(domain)) throw new ApiError(409, "set_in_environment", "這個網域寫在伺服器設定裡，這裡不能解除。")
      if (!stored.delete(domain)) throw new ApiError(404, "not_found", "封鎖清單裡沒有這個網域")
    },
  }
}

/** 台北時間的 ISO（+08:00，到秒），和後端 `iso_taipei` 相同 */
function taipeiIso(d: Date): string {
  return `${new Date(d.getTime() + 8 * 3_600_000).toISOString().slice(0, 19)}+08:00`
}
