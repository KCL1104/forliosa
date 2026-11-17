import { Link } from "@tanstack/react-router"
import { useId, useState } from "react"
import { toast } from "sonner"
import {
  useAdminReportsOverview,
  useAdminReportsTrial,
  usePutReportsConfig,
  useRevealTrial,
  useVoteReport,
} from "@/api/discussion-queries"
import {
  ApiError,
  REPORT_KIND_LABEL,
  type AdminReportRun,
  type AdminReportsOverview,
  type AdminTrial,
  type ReportKind,
  type ReportsMode,
  type ReportTier,
  type ReportVariant,
  type TrialAudience,
  type TrialReport,
  type TrialReveal,
  type TrialVoteCounts,
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
import { Input } from "@/components/ui/input"
import { formatDateTime, formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"
import { AdminPage } from "./AdminPage"
import { ManualTables } from "./AdminReportsTables"
import { writerText } from "./report-labels"

const errText = (err: unknown) => (err instanceof ApiError ? err.message : "請檢查網路後再試一次。")
const usd = (v: number) => `US$${formatNumber(v, 2)}`
const KINDS: ReportKind[] = ["premarket", "close", "weekly"]
const LABELS: ReportVariant[] = ["A", "B", "C"]

const MODE_TEXT: Record<ReportsMode, { label: string; detail: string }> = {
  trial: { label: "試跑", detail: "照常產生，只有站方管理員看得到，不推播。" },
  public: { label: "對全站公開", detail: "之後的新報告所有登入的人都看得到，並推播到有開的群組。" },
  paused: { label: "暫停", detail: "不產生新報告、不推播；已公開的照常可以讀。" },
}
/** 誰參加盲測（`MREPORT_TRIAL_AUDIENCE`，後台也可以切；2026-11-17） */
const AUDIENCE_TEXT: Record<TrialAudience, { label: string; detail: string }> = {
  admins: { label: "只有站方管理員", detail: "其他人看不到盲測的報告，不推播。" },
  all: { label: "所有登入的人", detail: "大家都能看 A、B、C 並投票；有開推播的群組收到投票連結。" },
}
/** 試跑時的說明：盲測開給所有人時，盲測的報告大家看得到 */
const modeDetail = (mode: ReportsMode, audience: TrialAudience | undefined) =>
  mode === "trial" && audience === "all" ? "照常產生。盲測的報告所有登入的人都能看、投票；其他的只有站方管理員看得到。" : MODE_TEXT[mode].detail
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
 * 狀態（模式、撰寫設定、本月花費與層級、試跑花費與進度、專用金鑰）→ 盲測（每份一列：A／B／C 的連結、狀態、問題數、我的票；
 * 做完後「揭曉」）→ 最近的產生紀錄 → 美股休市表、總經行事曆、美股財報日（手動維護）。
 * 揭曉前不顯示盲測用的是哪個模型、花了多少（A／B／C 只是標籤，每份重新打亂）。
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
          <Trial />
          <Runs runs={overview.data.runs} />
          <ManualTables manual={overview.data.manual} />
        </>
      )}
    </AdminPage>
  )
}

// ── 狀態 ────────────────────────────────────────────
function Status({ o }: { o: AdminReportsOverview }) {
  const [editing, setEditing] = useState<"mode" | "audience" | ReportKind | null>(null)
  const audience = o.trial_audience ?? "admins"
  const trialLine = `${usd(o.trial.spend_usd)}／${usd(o.trial.budget_usd)}・第 ${o.trial.days_done}／${o.trial.days_total} 個交易日・週報${o.trial.weekly_done ? "做了" : "未做"}`
  return (
    <Section title="狀態" titleId="mr-status" bodyClassName="pt-0">
      <dl className="flex flex-col">
        <Row label="模式" action={<Button variant="outline" size="sm" onClick={() => setEditing("mode")}>切換</Button>}>
          <span className="font-medium">{MODE_TEXT[o.mode].label}</span>
          <span className="block text-sm text-ink-2">{modeDetail(o.mode, o.trial_audience)}</span>
        </Row>
        {o.trial_audience && (
          <Row label="盲測對象" action={<Button variant="outline" size="sm" aria-label="切換盲測對象" onClick={() => setEditing("audience")}>切換</Button>}>
            <span className="font-medium">{AUDIENCE_TEXT[audience].label}</span>
            {o.trial_audience_source === "default" && <span className="text-sm text-ink-2">（預設）</span>}
            <span className="block text-sm text-ink-2">{AUDIENCE_TEXT[audience].detail}</span>
          </Row>
        )}
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
                <span>盲測中</span>
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
        <Row label="試跑">
          <span className="num">{o.trial.revealed_at ? `${usd(o.trial.spend_usd)}・${formatDateTime(o.trial.revealed_at)} 揭曉` : trialLine}</span>
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
      {editing === "audience" && <AudienceDialog current={audience} onClose={() => setEditing(null)} />}
      {editing && editing !== "mode" && editing !== "audience" && o.writers[editing] && <WriterDialog kind={editing} current={o.writers[editing]!} onClose={() => setEditing(null)} />}
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

/** 切換模式：三個選項；切到「對全站公開」要再確認一次 */
function ModeDialog({ current, onClose }: { current: ReportsMode; onClose: () => void }) {
  const put = usePutReportsConfig()
  const [mode, setMode] = useState<ReportsMode>(current)
  const [confirming, setConfirming] = useState(false)
  const save = () =>
    put.mutate(
      { mode },
      {
        onSuccess: (r) => {
          toast.success(`市場報告：${MODE_TEXT[r.mode].label}`, r.notice ? { description: r.notice } : undefined)
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
          {(["trial", "public", "paused"] as const).map((m) => (
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

/** 誰參加盲測：兩個選項；開給所有人時，盲測的報告大家都能看、投票，有開推播的群組收到投票連結 */
function AudienceDialog({ current, onClose }: { current: TrialAudience; onClose: () => void }) {
  const put = usePutReportsConfig()
  const [value, setValue] = useState<TrialAudience>(current)
  return (
    <Dialog open onOpenChange={(o) => !o && !put.isPending && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>誰參加盲測</DialogTitle>
          <DialogDescription>揭曉只有站方管理員能按。</DialogDescription>
        </DialogHeader>
        <div role="radiogroup" aria-label="誰參加盲測" className="flex flex-col border-t border-rule">
          {(["admins", "all"] as const).map((a) => (
            <label key={a} className="flex min-h-14 cursor-pointer items-start gap-3 border-b border-rule py-3">
              <input type="radio" name="mr-audience" value={a} checked={value === a} onChange={() => setValue(a)} className="mt-1 size-4 accent-[var(--ink)]" />
              <span>
                <span className="block font-medium">{AUDIENCE_TEXT[a].label}</span>
                <span className="block text-base text-ink">{AUDIENCE_TEXT[a].detail}</span>
              </span>
            </label>
          ))}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button
            variant="sign"
            disabled={value === current || put.isPending}
            onClick={() =>
              put.mutate(
                { trial_audience: value },
                {
                  onSuccess: (r) => {
                    toast.success(`盲測：${AUDIENCE_TEXT[r.trial_audience ?? value].label}`, r.notice ? { description: r.notice } : undefined)
                    onClose()
                  },
                  onError: (err) => toast.error("沒有切換", { description: errText(err) }),
                },
              )
            }
          >
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

// ── 盲測 ────────────────────────────────────────────
function Trial() {
  const trial = useAdminReportsTrial()
  const t = trial.data
  return (
    <Section
      title="盲測"
      titleId="mr-trial"
      bodyClassName="pt-0"
      aside={t && <span className="num">{t.reveal ? `${formatDateTime(t.reveal.revealed_at)} 揭曉` : `第 ${t.days_done}／${t.days_total} 個交易日・週報${t.weekly_done ? "做了" : "未做"}`}</span>}
    >
      {trial.isError ? (
        <ErrorState flush error={trial.error} onRetry={() => void trial.refetch()} />
      ) : !t ? (
        <SkeletonLines rows={4} className="pt-4" />
      ) : t.reports.length === 0 ? (
        <EmptyState flush title="還沒有盲測的報告" description="試跑開始後，前 5 個交易日的盤前與盤後、第一份週報，每份各寫 A、B、C 三個版本。" />
      ) : (
        <>
          {t.audience === "all" && t.voters && (
            <p className="num border-b border-rule py-2.5 text-md text-ink-2" data-trial-voters="">
              開給所有登入的人：會員 {t.voters.members} 人、管理員 {t.voters.admins} 人投過票。
            </p>
          )}
          <ul aria-label="盲測的報告">
            {t.reports.map((r) => (
              <TrialRow key={r.report_id} r={r} revealed={!!t.reveal} everyone={t.audience === "all"} />
            ))}
          </ul>
          {t.reveal ? <RevealSummary reveal={t.reveal} /> : <RevealButton t={t} />}
        </>
      )}
    </Section>
  )
}

/** `everyone`：盲測開給所有人（這時每份多寫大家的票；只給管理員時照舊只有「我的票」，除非已經有會員投過） */
function TrialRow({ r, revealed, everyone }: { r: TrialReport; revealed: boolean; everyone: boolean }) {
  const vote = useVoteReport()
  const [note, setNote] = useState(r.my_vote?.note ?? "")
  const id = useId()
  const cast = (preferred: ReportVariant, n = note) =>
    vote.mutate({ id: r.report_id, preferred, note: n.trim() || undefined }, { onError: (err) => toast.error("沒有投票成功", { description: errText(err) }) })
  return (
    <li className="flex flex-col gap-2 border-b border-rule py-3" data-trial-report={r.report_id}>
      <p className="num font-medium">
        {REPORT_KIND_LABEL[r.kind]} {r.edition_label}
      </p>
      <ul className="grid gap-x-6 gap-y-1 sm:grid-cols-3">
        {r.variants.map((v) => {
          const problems = v.metrics ? v.metrics.subject_mismatches + v.metrics.inferred_dates : null
          const facts = [
            STATUS_TEXT[v.status] ?? v.status,
            v.on_time === null ? null : v.on_time ? "準時" : "遲了",
            problems === null ? null : `問題 ${problems} 個`,
            v.metrics && v.metrics.dropped_sections > 0 ? `拿掉 ${v.metrics.dropped_sections} 段` : null,
          ].filter(Boolean)
          return (
            <li key={v.label} className="flex items-baseline gap-2 text-md">
              {/* 還在寫、還沒跑、或沒有 AI 版（只發了資料版、預算不夠沒跑）：沒有可以看的版本 */}
              {v.status === "running" || v.status === "pending" || v.published === false ? (
                <span className="num w-5 font-medium text-ink-2">{v.label}</span>
              ) : (
                <Link
                  to="/admin/reports/$reportId"
                  params={{ reportId: r.report_id }}
                  search={{ v: v.label }}
                  aria-label={`看 ${v.label} 版`}
                  className={cn(textAction, "num w-5 justify-center font-medium")}
                >
                  {v.label}
                </Link>
              )}
              <span className="num text-ink-2">
                {facts.join("・")}
                {revealed && v.writer && `・${writerText(v.writer)}`}
              </span>
            </li>
          )
        })}
      </ul>
      {r.votes && (everyone || LABELS.some((l) => r.votes!.members[l] > 0)) && <Votes votes={r.votes} />}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="text-md text-ink-2">我的票</span>
        <div role="group" aria-label={`${REPORT_KIND_LABEL[r.kind]} ${r.edition_label} 投給哪一個`} className="flex gap-1">
          {LABELS.map((l) => (
            <button
              key={l}
              type="button"
              aria-pressed={r.my_vote?.preferred === l}
              disabled={vote.isPending || revealed}
              onClick={() => cast(l)}
              className="press sel-chip num h-8 min-w-9 rounded-sm border border-ctl px-2.5 text-md text-ink-2 disabled:opacity-60 pointer-coarse:h-11 pointer-coarse:min-w-11"
            >
              {l}
            </button>
          ))}
        </div>
        <label htmlFor={`${id}-note`} className="sr-only">
          備註
        </label>
        <Input
          id={`${id}-note`}
          value={note}
          disabled={revealed}
          maxLength={200}
          placeholder="備註（選填）"
          onChange={(e) => setNote(e.target.value)}
          onBlur={() => r.my_vote && note.trim() !== (r.my_vote.note ?? "") && cast(r.my_vote.preferred, note)}
          className="h-8 max-w-xs min-w-0 flex-1 pointer-coarse:h-11"
        />
      </div>
    </li>
  )
}

/** 大家的票：合計一行，下面一行會員、管理員分開（管理員與會員的票一起算） */
function Votes({ votes }: { votes: { all: TrialVoteCounts; admins: TrialVoteCounts; members: TrialVoteCounts } }) {
  const line = (c: TrialVoteCounts) => LABELS.map((l) => `${l} ${c[l]}`).join("・")
  const total = LABELS.reduce((a, l) => a + votes.all[l], 0)
  return (
    <div className="num flex flex-col text-md" data-trial-votes="">
      <p>
        <span className="text-ink-2">大家的票</span> {total === 0 ? "還沒有人投" : line(votes.all)}
      </p>
      {total > 0 && (
        <p className="text-sm text-ink-2">
          會員 {line(votes.members)}；管理員 {line(votes.admins)}
        </p>
      )}
    </div>
  )
}

/** 全部做完：簽名色「揭曉」；還沒做完：外框「提前揭曉」（先確認） */
function RevealButton({ t }: { t: AdminTrial }) {
  const reveal = useRevealTrial()
  const [sure, setSure] = useState(false)
  const run = (force: boolean) =>
    reveal.mutate(force, {
      onSuccess: () => {
        toast.success("已揭曉")
        setSure(false)
      },
      onError: (err) => toast.error("沒有揭曉", { description: errText(err) }),
    })
  return (
    <div className="mt-4 flex flex-wrap items-center gap-3">
      {t.finished ? (
        <Button variant="sign" disabled={reveal.isPending} onClick={() => run(false)}>
          揭曉
        </Button>
      ) : (
        <Button variant="outline" onClick={() => setSure(true)}>
          提前揭曉
        </Button>
      )}
      <span className="text-sm text-ink-2">揭曉後才看得到每個版本的模型與花費。</span>
      {sure && (
        <AlertDialog open onOpenChange={(o) => !o && setSure(false)}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>盲測還沒做完，要提前揭曉？</AlertDialogTitle>
              <AlertDialogDescription>
                現在做了 {t.days_done}／{t.days_total} 個交易日、週報{t.weekly_done ? "做了" : "還沒做"}。揭曉後之後的投票不算進比較。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>取消</AlertDialogCancel>
              <AlertDialogAction disabled={reveal.isPending} onClick={() => run(true)}>
                提前揭曉
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </div>
  )
}

/** 揭曉後的彙總：每種報告 × 每組設定；「過關」照合約 §17.4；建議過關裡平均花費最低的，按一下改用 */
function RevealSummary({ reveal }: { reveal: TrialReveal }) {
  const put = usePutReportsConfig()
  return (
    <div className="mt-6 flex flex-col gap-8">
      {reveal.kinds.map((k) => (
        <div key={k.kind} className="flex flex-col gap-2">
          <h3 className="text-lg font-semibold">{k.kind_label}</h3>
          <div className="-mx-1 overflow-x-auto px-1">
            <table className="w-full min-w-[34rem] text-md">
              <thead className="form-head">
                <tr>
                  <th scope="col" className="h-9 pr-3 text-left font-normal">
                    設定
                  </th>
                  {["票數", "準時", "平均花費", "平均秒數", "問題", "拿掉的段", "資料政策", ""].map((h) => (
                    <th key={h || "pass"} scope="col" className="h-9 pl-3 text-right font-normal">
                      {h || <span className="sr-only">過關</span>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {k.rows.map((r) => (
                  <tr key={writerText(r.writer)} className="border-b border-rule">
                    <td className="num h-11 pr-3">{writerText(r.writer)}</td>
                    <td className="num pl-3 text-right whitespace-nowrap">
                      {r.votes}
                      {!!r.votes_members && <span className="block text-sm text-ink-2">會員 {r.votes_members}</span>}
                    </td>
                    <td className="num pl-3 text-right">{Math.round(r.on_time_rate * 100)}%</td>
                    <td className="num pl-3 text-right">{usd(r.avg_cost_usd)}</td>
                    <td className="num pl-3 text-right">{r.avg_seconds}</td>
                    <td className="num pl-3 text-right">{r.subject_mismatches + r.inferred_dates}</td>
                    <td className="num pl-3 text-right">{r.dropped_sections}</td>
                    <td className="num pl-3 text-right">{r.policy_violations}</td>
                    <td className={cn("pl-3 text-right whitespace-nowrap", r.passed ? "font-medium text-ink" : "text-ink-2")}>{r.passed ? "過關" : "沒過"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {k.suggested ? (
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-base">
              <span>
                建議：<span className="num font-medium">{writerText(k.suggested)}</span>（過關裡平均花費最低）
              </span>
              <button
                type="button"
                className={textAction}
                disabled={put.isPending}
                onClick={() =>
                  put.mutate(
                    { writers: { [k.kind]: k.suggested } },
                    { onSuccess: () => toast.success(`${k.kind_label}改用 ${writerText(k.suggested!)}`), onError: (err) => toast.error("沒有改成功", { description: errText(err) }) },
                  )
                }
              >
                用這個設定
              </button>
            </p>
          ) : (
            <p className="text-base">三組設定都沒有過關。</p>
          )}
        </div>
      ))}
    </div>
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
