import { useState } from "react"
import { useAdminOverview } from "@/api/discussion-queries"
import type { AdminDataset, AdminKeySlot, AdminNews, AdminNewsSource, AdminOverview, AdminUsPrices, BackfillStatus } from "@/api/types"
import { Section, Stat } from "@/components/section"
import { ErrorState, SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import { formatDate, formatDateShort, formatDateTime, formatMoney, formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"
import { AdminPage } from "./AdminPage"

/**
 * 管理後台的總覽（`/admin`）：使用者人數、AI 金鑰、各資料集的最新資料日期、新聞來源、美股收盤價、歷史日線回補。
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
      <NewsSources n={o.news} />
      {/* 舊版後端沒有這一塊 */}
      {o.us_prices && <UsPrices u={o.us_prices} />}
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

/** 新聞來源（2026-11-15）：每個來源照常、暫停（到什麼時候、為什麼）或沒有開，最近一次有回答、過去 24 小時存了幾則 */
function NewsSources({ n }: { n: AdminNews }) {
  const aside = n.enabled ? `每 ${n.refresh_minutes} 分鐘整理一次${n.last_run_at ? `・上次 ${formatDateTime(n.last_run_at)}` : ""}` : "沒有開"
  return (
    <Section title="新聞來源" titleId="admin-news" aside={aside} bodyClassName="pt-0">
      <ul aria-label="新聞來源">
        {n.sources.map((s) => (
          <li key={s.key} className="flex flex-wrap items-baseline gap-x-4 gap-y-0.5 border-b border-rule py-3">
            <span className="font-medium">{s.name}</span>
            <span className={cn("text-md", s.state === "paused" ? "font-medium text-ink" : "text-ink-2")}>{sourceState(s)}</span>
            {s.state !== "off" && <span className="num ml-auto text-ink">過去 24 小時 {formatNumber(s.new_24h)} 則</span>}
            {s.state !== "off" && <p className="num w-full text-sm text-ink-2">{sourceMeta(s, n)}</p>}
          </li>
        ))}
      </ul>
    </Section>
  )
}

const PAUSE_WORD: Record<"rate_limited" | "blocked" | "unreachable", string> = { rate_limited: "限流中", blocked: "被拒", unreachable: "連不上" }

function sourceState(s: AdminNewsSource): string {
  if (s.state === "off") return "沒有開"
  if (s.state === "ok") return "正常"
  if (s.reason === "budget") return "本月預算用完"
  const word = PAUSE_WORD[s.reason ?? "blocked"]
  return s.paused_until ? `${word}，${formatDateTime(s.paused_until)} 再試` : word
}

function sourceMeta(s: AdminNewsSource, n: AdminNews): string {
  const parts = [s.last_success_at ? `上次有回答 ${formatDateTime(s.last_success_at)}` : "還沒有回答過"]
  if (s.key === "ai_search") parts.push(`本月 ${usd(n.ai_month_cost_usd)}／預算 ${usd(n.ai_budget_usd)}`)
  if (s.key === "searxng" && n.paused_engines.length > 0)
    parts.push(`暫停的引擎：${n.paused_engines.map((e) => `${e.engine}（到 ${formatDateTime(e.until)}）`).join("、")}`)
  return parts.join("・")
}

/**
 * 美股收盤價（Databento EQUS.SUMMARY，2026-11-15）：開著沒有、存了幾筆、存到紐約的哪一天、還有幾檔沒回補，
 * 以及每一檔回補的結果。新追蹤的美股從 first_day（2024-07-01）回補。
 */
function UsPrices({ u }: { u: AdminUsPrices }) {
  return (
    <Section title="美股收盤價" titleId="admin-us-prices" aside={`Databento・${formatDate(u.first_day)} 起`}>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
        <Stat label="狀態" value={u.enabled ? "開著" : "關著"} />
        {/* 紐約的交易日（存檔是台北隔天清晨） */}
        <Stat label="存到" value={u.stored_through ? `${formatDateShort(u.stored_through, false)}（美東）` : "還沒有"} />
        <Stat label="日線" value={`${formatNumber(u.rows)} 筆`} />
        <Stat label="還沒回補" value={`${formatNumber(u.pending)} 檔`} />
        <Stat label="完成" value={`${formatNumber(u.symbols.done)} 檔`} />
        <Stat label="找不到" value={`${formatNumber(u.symbols.not_found)} 檔`} />
        <Stat label="出錯" value={`${formatNumber(u.symbols.error)} 檔`} />
      </dl>
    </Section>
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
