import { useState } from "react"
import { useAdminOverview } from "@/api/discussion-queries"
import type { AdminDataset, AdminKeySlot, AdminOverview, BackfillStatus } from "@/api/types"
import { Section, Stat } from "@/components/section"
import { ErrorState, SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import { formatDateShort, formatDateTime, formatMoney, formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"
import { AdminPage } from "./AdminPage"

/**
 * 管理後台的總覽（`/admin`）：使用者人數、AI 金鑰、各資料集的最新資料日期、歷史日線回補。
 * 只有數字與狀態：沒有 email、user id，金鑰只有槽號與 workspace id。不自動重抓——按「重新載入」。
 */
export function AdminOverviewPage() {
  return (
    <AdminPage title="總覽" actions={<Reload />}>
      <Overview />
    </AdminPage>
  )
}

function Reload() {
  const q = useAdminOverview()
  return (
    <Button variant="outline" size="sm" disabled={q.isFetching} onClick={() => void q.refetch()}>
      {q.isFetching && q.data ? "載入中…" : "重新載入"}
    </Button>
  )
}

function Overview() {
  const q = useAdminOverview()
  if (q.isError) return <ErrorState flush error={q.error} onRetry={() => void q.refetch()} />
  if (!q.data) return <SkeletonLines rows={8} />
  const o = q.data
  return (
    <>
      <Section title="使用者" titleId="admin-users">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
          <Stat label="帳號" value={formatNumber(o.users.total)} />
          <Stat label="過去 7 天新增" value={formatNumber(o.users.new_7d)} />
        </dl>
      </Section>
      <KeySlots ai={o.ai} />
      <Datasets rows={o.datasets} />
      <Backfill b={o.history_backfill} />
    </>
  )
}

const STATE_LABEL: Record<AdminKeySlot["state"], string> = {
  ok: "正常",
  cooling: "冷卻中",
  disabled: "停用（金鑰被拒）",
  exhausted: "額度用完",
  over_budget: "超過本月預算",
  not_configured: "沒有設定",
}
const usd = (n: number) => formatMoney(n, { currency: "USD" })

function stateText(s: AdminKeySlot): string {
  if (s.state === "cooling" && s.retry_in_seconds) return `冷卻中，${s.retry_in_seconds} 秒後再試`
  return STATE_LABEL[s.state]
}

function KeySlots({ ai }: { ai: AdminOverview["ai"] }) {
  const [y, m] = ai.month.split("-")
  return (
    <Section title="AI 金鑰" titleId="admin-keys" aside={`${y} 年 ${Number(m)} 月（UTC）`} bodyClassName="pt-0">
      <ul aria-label="AI 金鑰">
        {ai.slots.map((s) => (
          <li key={s.slot} className="flex flex-wrap items-baseline gap-x-4 gap-y-0.5 border-b border-rule py-3">
            <span className="font-medium">金鑰 {s.slot}</span>
            <span className={cn("text-md", s.state === "ok" || s.state === "not_configured" ? "text-ink-2" : "font-medium text-ink")}>{stateText(s)}</span>
            {s.configured && (
              <span className="num ml-auto text-ink">
                {usd(s.month_cost_usd)}
                {s.monthly_budget_usd !== null && <span className="text-ink-2">／預算 {usd(s.monthly_budget_usd)}</span>}
              </span>
            )}
            {s.configured && (
              <p className="num w-full text-sm text-ink-2">
                {formatNumber(s.month_calls)} 次呼叫・{formatNumber(s.threads)} 段對話{s.workspace_id && `・${s.workspace_id}`}
              </p>
            )}
            {s.last_error && <p className="num w-full text-sm text-ink">最近的錯誤：{s.last_error}</p>}
          </li>
        ))}
      </ul>
    </Section>
  )
}

/** 預設只列沒有更新的資料集（最久的在前），其他的收成一行；「全部 N 個」展開 */
function Datasets({ rows }: { rows: AdminDataset[] }) {
  const [all, setAll] = useState(false)
  const stale = rows.filter((r) => r.stale)
  const fresh = rows.length - stale.length
  const shown = all ? rows : stale
  return (
    <Section
      title="資料"
      titleId="admin-datasets"
      aside={rows.length > 0 ? (stale.length > 0 ? `${stale.length} 個沒有更新` : "都有更新") : undefined}
      action={
        fresh > 0 && (
          <button type="button" aria-expanded={all} onClick={() => setAll(!all)} className={textAction}>
            {all ? "只看沒有更新的" : `全部 ${rows.length} 個`}
          </button>
        )
      }
      bodyClassName="pt-0"
    >
      {rows.length === 0 ? (
        <p className="pt-3 text-base text-ink-2">還沒有存檔過。</p>
      ) : (
        <ul aria-label="資料集">
          {shown.map((r) => (
            <DatasetRow key={r.key} r={r} />
          ))}
          {!all && fresh > 0 && (
            <li className="border-b border-rule py-2.5 text-ink-2">
              {stale.length > 0 ? "其他" : "全部"} {fresh} 個最近 3 個交易日內都有新資料。
            </li>
          )}
        </ul>
      )}
    </Section>
  )
}

function DatasetRow({ r }: { r: AdminDataset }) {
  return (
    <li className="flex items-baseline gap-4 border-b border-rule py-2.5">
      <div className="min-w-0 flex-1">
        <p className="break-words">{r.name}</p>
        {r.agency && <p className="text-sm text-ink-2">{r.agency}</p>}
      </div>
      <div className="shrink-0 text-right">
        <p className={cn("num", r.stale && "font-medium")}>{r.data_date ? formatDateShort(r.data_date, false) : "沒有資料"}</p>
        <p className={cn("num text-sm", r.stale ? "text-ink" : "text-ink-2")}>
          {r.stale && r.days_behind !== null ? `${r.days_behind} 天沒有新資料` : r.fetched_at ? `存檔 ${formatDateTime(r.fetched_at)}` : ""}
        </p>
      </div>
    </li>
  )
}

const BACKFILL_LABEL: [BackfillStatus, string][] = [
  ["done", "完成"],
  ["not_found", "找不到"],
  ["mismatch", "和存檔對不上"],
  ["no_overlap", "沒有可比對的日期"],
  ["error", "出錯"],
]

function Backfill({ b }: { b: AdminOverview["history_backfill"] }) {
  return (
    <Section title="歷史日線回補" titleId="admin-backfill" aside="Yahoo Finance">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
        <Stat label="狀態" value={b.enabled ? "開著" : "關著"} />
        <Stat label="日線" value={`${formatNumber(b.rows)} 筆`} />
        <Stat label="還沒問過" value={`${formatNumber(b.pending)} 檔`} />
        {BACKFILL_LABEL.map(([k, label]) => (
          <Stat key={k} label={label} value={`${formatNumber(b.symbols[k] ?? 0)} 檔`} />
        ))}
      </dl>
    </Section>
  )
}
