import { useId, useRef, useState } from "react"
import { toast } from "sonner"
import { useMarketReportTrial, useMarketReportVariant, useVoteMarketReport } from "@/api/queries"
import { ApiError, type MarketReport, type MemberTrial, type ReportVariant, type WriterSetting } from "@/api/types"
import { useReadOnly } from "@/api/view-as"
import { RangeChips } from "@/components/segmented"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { writerText } from "@/pages/admin/report-labels"
import { ReportView } from "./ReportView"

const LABELS: ReportVariant[] = ["A", "B", "C"]
const errText = (err: unknown) => (err instanceof ApiError ? err.message : "請檢查網路後再試一次。")

/**
 * 盲測的一份（盲測開給所有登入的人時；產品負責人 2026-11-17「我讓我的朋友們一起選」）。市場頁「報告」分頁與
 * `/market/reports/<id>`（推播的投票連結）都用它，取代只有資料的那一版：
 * 1. 上下格線的一列：細框小字「盲測：三種寫法」＋一句說明；「A｜B｜C」（選取語法 (b)，看哪一種）＋右邊「你選了 B」。
 *    揭曉後多寫每一種是哪個設定、幾票，與這一種報告整個盲測的結果。
 * 2. 選的那一種的全文（`ReportView`，一般形式：沒有 refs、模型、花費）。
 * 3. 最後一列：簽名格「選 B」（已經選了別的是「改選 B」；選的就是這一種時只寫「你選了 B」）＋看另外兩種的文字動作。
 * 投票的按鈕只有一種（看哪一種用上面的選項）：兩組一樣的 A／B／C 方格會分不清哪一組是投票。
 * 揭曉前不寫模型、花費與票數；查看別人的資產時不能投票（伺服器回唯讀）。
 * 三種都還不能看（還在寫，或這一份都沒有寫成）：說明一句，下面放資料版（`report`），不讓整頁只剩「還在寫」。
 * 焦點：按了「選 B」，按鈕換成「你選了 B」，焦點移到那一行（讀屏會念出來）；按了「看 C」，焦點移到上面選取的 C。
 */
export function TrialEdition({ reportId, report }: { reportId: string; report?: MarketReport }) {
  const trial = useMarketReportTrial(reportId)
  const [picked, setPicked] = useState<ReportVariant | null>(null)
  const barRef = useRef<HTMLElement>(null)
  const t = trial.data
  if (trial.isError) {
    return trial.error instanceof ApiError && trial.error.status === 404 ? (
      <EmptyState title="找不到這份報告" />
    ) : (
      <ErrorState error={trial.error} onRetry={() => void trial.refetch()} />
    )
  }
  if (!t) return <SkeletonLines rows={10} />
  const state = (l: ReportVariant) => t.variants.find((v) => v.label === l)?.state ?? "none"
  const label: ReportVariant = picked ?? (t.my_vote && state(t.my_vote) === "ready" ? t.my_vote : (LABELS.find((l) => state(l) === "ready") ?? "A"))
  const show = (l: ReportVariant) => {
    setPicked(l)
    const bar = barRef.current
    bar?.scrollIntoView({ block: "start", behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" })
    // 按下的「看 C」會消失：焦點移到上面選取的那一格（重繪之後才是 C）
    requestAnimationFrame(() => bar?.querySelector<HTMLElement>('[role="radio"][aria-checked="true"]')?.focus({ preventScroll: true }))
  }
  if (!t.variants.some((v) => v.state === "ready")) {
    return (
      <div className="flex flex-col gap-8" data-trial-edition={reportId} data-trial-waiting="">
        <TrialBar ref={barRef} t={t} label={label} onPick={setPicked} waiting />
        {/* 資料版的狀態行講的是一般的 AI 版（「沒有 AI 段落」），盲測時由上面那一句說明 */}
        {report ? <ReportView report={{ ...report, status_line: null }} /> : <EmptyState title="三種寫法還沒好" />}
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-8" data-trial-edition={reportId}>
      <TrialBar ref={barRef} t={t} label={label} onPick={setPicked} />
      <Variant reportId={reportId} label={label} state={state(label)} />
      <VoteRow t={t} label={label} ready={state(label) === "ready"} others={LABELS.filter((l) => l !== label && state(l) === "ready")} onShow={show} />
    </div>
  )
}

function TrialBar({ t, label, onPick, ref, waiting = false }: { t: MemberTrial; label: ReportVariant; onPick: (l: ReportVariant) => void; ref: React.Ref<HTMLElement>; waiting?: boolean }) {
  const id = useId()
  const mine = t.my_vote
  // 三種都還不能看：還有在寫的是「還沒好」，都不會來了是「沒有寫成」；下面是資料版
  const lead = waiting
    ? t.variants.some((v) => v.state === "writing")
      ? "三種寫法還沒好，先看資料。寫好就可以選。"
      : "這一份沒有寫成三種寫法，下面是資料。"
    : t.revealed
      ? "已經揭曉每一種是誰寫的。"
      : "同一份資料寫了三次。看完選一個你覺得最好讀的。"
  return (
    <section ref={ref} aria-labelledby={id} className="flex max-w-[46rem] scroll-mt-32 flex-col gap-3 border-y border-rule py-3" data-trial-bar="">
      <p className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 text-base text-ink">
        <span id={id} className="demo-tag self-center">
          盲測：三種寫法
        </span>
        {lead}
      </p>
      {!waiting && (
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <RangeChips label="看哪一種寫法" value={label} onChange={onPick} options={LABELS.map((l) => ({ value: l, label: l }))} />
          <p className="text-md" data-my-vote={mine ?? ""}>
            {mine ? <span className="font-medium text-ink">你選了 {mine}</span> : <span className="text-ink-2">{t.revealed ? "你沒有投票" : "還沒選"}</span>}
          </p>
        </div>
      )}
      {t.revealed && <Revealed t={t} />}
    </section>
  )
}

/** 揭曉後：每一種是哪個設定、這一份幾票；這一種報告整個盲測裡最多人選的，與之後用哪個設定（後台存了才寫） */
function Revealed({ t }: { t: MemberTrial }) {
  const r = t.result
  const most = r?.top ?? []
  const votesOf = (w: WriterSetting) => r?.rows.find((x) => x.writer.model === w.model && x.writer.effort === w.effort)?.votes ?? 0
  return (
    <div className="flex flex-col gap-2 border-t border-rule pt-3" data-trial-reveal="">
      <ul aria-label="每一種是哪個設定" className="flex flex-col gap-0.5">
        {t.variants.map((v) => (
          <li key={v.label} className="num text-md">
            <span className="inline-block w-5 font-medium">{v.label}</span>
            {v.writer ? writerText(v.writer) : "沒有寫成"}
            {t.votes && <span className="text-ink-2">・{t.votes[v.label]} 票</span>}
          </li>
        ))}
      </ul>
      {r && (
        <p className="text-base text-ink">
          {most.length > 0 ? (
            <>
              整個盲測的{r.kind_label}，最多人選 <span className="num font-medium">{most.map(writerText).join("、")}</span>
              <span className="num">（{most.length > 1 ? "各 " : ""}{votesOf(most[0]!)} 票）</span>。
            </>
          ) : (
            "整個盲測沒有人投票。"
          )}
          {r.chosen && (
            <>
              {" "}之後的{r.kind_label}用 <span className="num font-medium">{writerText(r.chosen)}</span> 寫。
            </>
          )}
        </p>
      )}
    </div>
  )
}

function Variant({ reportId, label, state }: { reportId: string; label: ReportVariant; state: "ready" | "writing" | "none" }) {
  const q = useMarketReportVariant(reportId, label, state === "ready")
  if (state === "writing") return <EmptyState title={`${label} 還在寫`} />
  if (state === "none") return <EmptyState title={`${label} 這次沒有寫成`} />
  if (q.isError) {
    if (q.error instanceof ApiError && q.error.status === 409) return <EmptyState title={`${label} 還在寫`} />
    if (q.error instanceof ApiError && q.error.status === 404) return <EmptyState title={`${label} 這次沒有寫成`} />
    return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  }
  if (!q.data) return <SkeletonLines rows={10} />
  return <ReportView report={q.data} prefix={`${label.toLowerCase()}-`} />
}

/** 讀完這一種之後：選它（簽名格），或看另外兩種 */
function VoteRow({ t, label, ready, others, onShow }: { t: MemberTrial; label: ReportVariant; ready: boolean; others: ReportVariant[]; onShow: (l: ReportVariant) => void }) {
  const readOnly = useReadOnly()
  const vote = useVoteMarketReport(t.report_id)
  const id = useId()
  const mine = t.my_vote
  const canVote = t.can_vote && ready && !readOnly
  // 投票成功後按鈕換成「你選了 B」：那一行出現時把焦點移過去（不掉回頁首，讀屏也會念出來）；沒有成功就回到按鈕
  const focusPick = useRef(false)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const pickRef = (el: HTMLParagraphElement | null) => {
    if (!el || !focusPick.current) return
    focusPick.current = false
    el.focus({ preventScroll: true })
  }
  const submit = () => {
    focusPick.current = true
    vote.mutate(label, {
      onError: (err) => {
        focusPick.current = false
        requestAnimationFrame(() => buttonRef.current?.focus({ preventScroll: true }))
        toast.error("沒有投票成功", { description: errText(err) })
      },
    })
  }
  if (!canVote && others.length === 0 && !(ready && mine === label)) return null
  return (
    <section aria-labelledby={id} className="flex max-w-[46rem] flex-wrap items-center gap-x-6 gap-y-3 border-t border-rule pt-4" data-trial-vote="">
      <h3 id={id} className="sr-only">
        投票
      </h3>
      {ready && mine === label ? (
        <p ref={pickRef} tabIndex={-1} className="text-base font-medium text-ink outline-none" data-my-pick="">
          你選了 {label}
        </p>
      ) : (
        canVote && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <Button ref={buttonRef} variant="sign" disabled={vote.isPending} onClick={submit}>
              {mine ? `改選 ${label}` : `選 ${label}`}
            </Button>
            {mine && <span className="text-md text-ink-2">你選了 {mine}</span>}
          </div>
        )
      )}
      {others.length > 0 && (
        <p className={cn("flex items-center gap-4", !(ready && mine === label) && !canVote ? "" : "sm:ml-auto")}>
          {others.map((l) => (
            <button key={l} type="button" className={textAction} onClick={() => onShow(l)}>
              看 {l}
            </button>
          ))}
        </p>
      )}
    </section>
  )
}
