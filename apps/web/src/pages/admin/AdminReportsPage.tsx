import { useState } from "react"
import { toast } from "sonner"
import { useAdminReportsOverview, usePutReportsConfig } from "@/api/discussion-queries"
import {
  ApiError,
  REPORT_KIND_LABEL,
  type AdminReportRun,
  type AdminReportsOverview,
  type ReportKind,
  type ReportsMode,
  type ReportTier,
  type WriterSetting,
} from "@/api/types"
import { RangeChips } from "@/components/segmented"
import { Section } from "@/components/section"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { formatDateTime, formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"
import { AdminPage } from "./AdminPage"
import { ManualTables } from "./AdminReportsTables"
import { writerText } from "./report-labels"

const errText = (err: unknown) => (err instanceof ApiError ? err.message : "請檢查網路後再試一次。")
const usd = (v: number) => `US$${formatNumber(v, 2)}`
const KINDS: ReportKind[] = ["premarket", "close", "weekly"]

const MODE_TEXT: Record<ReportsMode, { label: string; detail: string }> = {
  public: { label: "對全站公開", detail: "所有登入的人都看得到新報告，並推播到有開的群組。" },
  paused: { label: "暫停", detail: "不產生新報告、不推播；已公開的照常可以讀。" },
}
const TIER_TEXT: Record<ReportTier, string> = { normal: "正常", medium: "已降為 medium", sonnet: "已改用 Sonnet", data_only: "只發資料版" }
const STATUS_TEXT: Record<string, string> = {
  running: "還在寫",
  ok: "完成",
  data_only: "只有資料",
  failed: "失敗",
  abandoned: "過了截止時間",
  skipped_budget: "預算不夠，沒有跑",
  pending: "還沒開始",
}

/**
 * 管理後台「市場報告」（`/admin/reports`；站方管理員）：
 * 狀態（模式、撰寫設定、本月花費與層級、專用金鑰）→ 最近的產生紀錄 → 美股休市表、總經行事曆、美股財報日（手動維護）。
 * 盲測（A／B／C、投票、揭曉）2026-11-18 拿掉了：每份報告寫一次、對所有登入的人公開。
 */
export function AdminReportsPage() {
  const overview = useAdminReportsOverview()
  return (
    <AdminPage
      title="市場報告"
      actions={
        <Button variant="outline" size="sm" disabled={overview.isFetching} onClick={() => void overview.refetch()}>
          重新載入
        </Button>
      }
    >
      {overview.isError ? (
        <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />
      ) : !overview.data ? (
        <SkeletonLines rows={8} />
      ) : !overview.data.enabled ? (
        <EmptyState title="市場報告沒有開" description="伺服器沒有開市場報告：不會產生報告，也不會推播。" />
      ) : (
        <>
          <Status o={overview.data} />
          <Runs runs={overview.data.runs} />
          <ManualTables manual={overview.data.manual} />
        </>
      )}
    </AdminPage>
  )
}

// ── 狀態 ────────────────────────────────────────────
function Status({ o }: { o: AdminReportsOverview }) {
  const [editing, setEditing] = useState<"mode" | ReportKind | null>(null)
  return (
    <Section title="狀態" titleId="mr-status" bodyClassName="pt-0">
      <dl className="flex flex-col">
        <Row label="模式" action={<Button variant="outline" size="sm" onClick={() => setEditing("mode")}>切換</Button>}>
          <span className="font-medium">{(MODE_TEXT[o.mode] ?? MODE_TEXT.public).label}</span>
          <span className="block text-sm text-ink-2">{(MODE_TEXT[o.mode] ?? MODE_TEXT.public).detail}</span>
        </Row>
        {KINDS.map((k) => {
          const w = o.writers[k]
          return (
            <Row
              key={k}
              label={REPORT_KIND_LABEL[k]}
              action={
                w && (
                  <button type="button" className={textAction} onClick={() => setEditing(k)} aria-label={`改${REPORT_KIND_LABEL[k]}的撰寫設定`}>
                    改
                  </button>
                )
              }
            >
              {w ? (
                <>
                  <span className="num">{writerText(w)}</span>
                  {w.source === "default" && <span className="text-sm text-ink-2">（預設）</span>}
                </>
              ) : (
                <span className="text-ink-2">—</span>
              )}
            </Row>
          )
        })}
        <Row label="本月花費">
          <span className="num">
            {usd(o.month.spend_usd)}
            <span className="text-ink-2">／上限 {usd(o.month.budget_usd)}</span>
          </span>
          <span className={cn("block text-sm", o.month.tier === "normal" ? "text-ink-2" : "font-medium text-ink")}>{TIER_TEXT[o.month.tier]}</span>
        </Row>
        <Row label="專用金鑰">
          {o.key.slot === null ? (
            <span>沒有專用的金鑰，用一般的金鑰</span>
          ) : (
            <span className="num">
              金鑰 {o.key.slot}・{o.key.status === "ok" ? "正常" : o.key.status === "cooldown" ? "冷卻中" : o.key.status === "disabled" ? "停用" : "額度用完"}
              {o.key.note && <span className="block text-sm text-ink-2">{o.key.note}</span>}
            </span>
          )}
        </Row>
      </dl>
      {editing === "mode" && <ModeDialog current={o.mode} onClose={() => setEditing(null)} />}
      {editing && editing !== "mode" && o.writers[editing] && <WriterDialog kind={editing} current={o.writers[editing]!} onClose={() => setEditing(null)} />}
    </Section>
  )
}

function Row({ label, children, action }: { label: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="grid min-h-12 grid-cols-[6.5rem_minmax(0,1fr)_auto] items-center gap-x-4 border-b border-rule py-2.5">
      <dt className="text-md text-ink-2">{label}</dt>
      <dd className="min-w-0 text-base">{children}</dd>
      <dd className="justify-self-end">{action}</dd>
    </div>
  )
}

/** 切換模式：兩個選項；切到「對全站公開」要再確認一次 */
function ModeDialog({ current: given, onClose }: { current: ReportsMode; onClose: () => void }) {
  // 舊的 API（部署交接時）還可能回 trial：當成對全站公開
  const current: ReportsMode = given in MODE_TEXT ? given : "public"
  const put = usePutReportsConfig()
  const [mode, setMode] = useState<ReportsMode>(current)
  const [confirming, setConfirming] = useState(false)
  const save = () =>
    put.mutate(
      { mode },
      {
        onSuccess: (r) => {
          toast.success(`市場報告：${(MODE_TEXT[r.mode] ?? MODE_TEXT.public).label}`, r.notice ? { description: r.notice } : undefined)
          onClose()
        },
        onError: (err) => toast.error("沒有切換", { description: errText(err) }),
      },
    )
  if (confirming) {
    return (
      <AlertDialog open onOpenChange={(o) => !o && onClose()}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>對全站公開？</AlertDialogTitle>
            <AlertDialogDescription>之後的新報告會對所有登入的人公開，並推播到有開的群組。</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction disabled={put.isPending} onClick={save}>
              對全站公開
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    )
  }
  return (
    <Dialog open onOpenChange={(o) => !o && !put.isPending && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>市場報告的模式</DialogTitle>
          <DialogDescription>現在是「{MODE_TEXT[current].label}」。</DialogDescription>
        </DialogHeader>
        <div role="radiogroup" aria-label="模式" className="flex flex-col border-t border-rule">
          {(["public", "paused"] as const).map((m) => (
            <label key={m} className="flex min-h-14 cursor-pointer items-start gap-3 border-b border-rule py-3">
              <input type="radio" name="mr-mode" value={m} checked={mode === m} onChange={() => setMode(m)} className="mt-1 size-4 accent-[var(--ink)]" />
              <span>
                <span className="block font-medium">{MODE_TEXT[m].label}</span>
                <span className="block text-base text-ink">{MODE_TEXT[m].detail}</span>
              </span>
            </label>
          ))}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button variant="sign" disabled={mode === current || put.isPending} onClick={() => (mode === "public" ? setConfirming(true) : save())}>
            切換
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** 改一種報告的撰寫設定（模型只能 Opus 5.5／Sonnet 5.5，effort low 到 xhigh） */
function WriterDialog({ kind, current, onClose }: { kind: ReportKind; current: WriterSetting; onClose: () => void }) {
  const put = usePutReportsConfig()
  const [model, setModel] = useState(current.model)
  const [effort, setEffort] = useState<WriterSetting["effort"]>(current.effort)
  return (
    <Dialog open onOpenChange={(o) => !o && !put.isPending && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{REPORT_KIND_LABEL[kind]}的撰寫設定</DialogTitle>
          <DialogDescription>月花費到 70% 以後會自動往下降一級。</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">模型</span>
            <RangeChips label="模型" value={model} onChange={setModel} options={[{ value: "claude-opus-5-5", label: "Opus 5.5" }, { value: "claude-sonnet-5-5", label: "Sonnet 5.5" }]} />
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">effort</span>
            <RangeChips label="effort" value={effort} onChange={setEffort} options={(["low", "medium", "high", "xhigh"] as const).map((e) => ({ value: e, label: e }))} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button
            variant="sign"
            disabled={put.isPending || (model === current.model && effort === current.effort)}
            onClick={() =>
              put.mutate(
                { writers: { [kind]: { model, effort } } },
                {
                  onSuccess: () => {
                    toast.success(`${REPORT_KIND_LABEL[kind]}改用 ${writerText({ model, effort })}`)
                    onClose()
                  },
                  onError: (err) => toast.error("沒有改成功", { description: errText(err) }),
                },
              )
            }
          >
            儲存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── 最近的產生紀錄 ───────────────────────────────────────
function Runs({ runs }: { runs: AdminReportRun[] }) {
  return (
    <Section title="最近的產生紀錄" titleId="mr-runs" bodyClassName="pt-0" aside={<span className="num">{runs.length} 筆</span>}>
      {runs.length === 0 ? (
        <EmptyState flush title="還沒有產生紀錄" />
      ) : (
        <ul aria-label="最近的產生紀錄">
          {runs.map((r) => {
            const facts = [
              `第 ${r.attempt} 次`,
              r.seconds !== null ? `${r.seconds} 秒` : null,
              r.stop_reason,
              r.fallback_used ? "用了備援" : null,
              r.problems > 0 ? `問題 ${r.problems} 個` : null,
              r.cost_usd !== null ? usd(r.cost_usd) : null,
              r.model ? writerText({ model: r.model, effort: r.effort ?? "" }) : null,
            ].filter(Boolean)
            return (
              <li key={r.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b border-rule py-2.5">
                <span className="num font-medium">
                  {REPORT_KIND_LABEL[r.kind]} {r.edition_label}
                  {r.variant && `・${r.variant}`}
                </span>
                <span className={cn("text-md", r.status === "ok" || r.status === "running" ? "text-ink-2" : "font-medium text-ink")}>{STATUS_TEXT[r.status] ?? r.status}</span>
                <span className="num ml-auto text-sm text-ink-2">{formatDateTime(r.started_at)}</span>
                <p className="num w-full text-sm text-ink-2">{facts.join("・")}</p>
              </li>
            )
          })}
        </ul>
      )}
    </Section>
  )
}
