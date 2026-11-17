import { useId, useState } from "react"
import { toast } from "sonner"
import {
  useAddMacroEvent,
  useAddUsEarning,
  useDeleteMacroEvent,
  useDeleteNyseHoliday,
  useDeleteUsEarning,
  useMacroEvents,
  useNyseHolidays,
  usePutNyseHoliday,
  useUsEarnings,
} from "@/api/discussion-queries"
import { ApiError, type AdminReportsOverview, type MacroEvent, type NyseHoliday, type UsEarning } from "@/api/types"
import { FieldError } from "@/components/form-field"
import { RangeChips } from "@/components/segmented"
import { Section } from "@/components/section"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
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
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { formatDateShort } from "@/lib/format"
import { cn } from "@/lib/utils"

const errText = (err: unknown) => (err instanceof ApiError ? err.message : "請檢查網路後再試一次。")
const NYSE_URL = "https://www.nyse.com/markets/hours-calendars"
type Errors = Record<string, string>

/** 伺服器的 422 寫在那一欄下面（`extra.field`）；認不得的欄位寫在 `fallback` 那一欄 */
function fieldError(err: unknown, fallback: string): Errors | null {
  if (!(err instanceof ApiError) || err.status !== 422) return null
  const field = typeof err.extra.field === "string" ? err.extra.field : fallback
  return { [field]: err.message }
}
/** 新增失敗：欄位不對就寫在那一欄下面，其他的（連不上、伺服器錯誤）跳通知 */
const failWith = (setErrors: (e: Errors) => void, fallback: string) => (err: unknown) => {
  const fe = fieldError(err, fallback)
  if (fe) setErrors(fe)
  else toast.error("沒有加入", { description: errText(err) })
}

/**
 * 三張手動維護的表（報告的行事曆用；每列連回官方頁面，不抓那些網站）：美股休市表、總經行事曆、美股財報日。
 * 每張表一個新增表單（必填欄位就地檢查，伺服器說不對的寫在那一欄下面）＋清單（每列右邊外框小按鈕「刪除」，先確認）。
 */
export function ManualTables({ manual }: { manual: AdminReportsOverview["manual"] }) {
  return (
    <>
      <NyseTable manual={manual} />
      <MacroTable />
      <EarningsTable />
    </>
  )
}

// ── 美股休市表 ────────────────────────────────────────
function NyseTable({ manual }: { manual: AdminReportsOverview["manual"] }) {
  const list = useNyseHolidays()
  const put = usePutNyseHoliday()
  const [deleting, setDeleting] = useState<NyseHoliday | null>(null)
  const del = useDeleteNyseHoliday()
  const id = useId()
  const [date, setDate] = useState("")
  const [name, setName] = useState("")
  const [kind, setKind] = useState<"closed" | "early_close">("closed")
  const [time, setTime] = useState("13:00")
  const [verified, setVerified] = useState(false)
  const [errors, setErrors] = useState<Errors>({})
  const unverified = manual.nyse_unverified
  const aside = [manual.nyse_next ? `下一個：${formatDateShort(manual.nyse_next.date)} ${manual.nyse_next.name}` : null, unverified > 0 ? `尚未核對 ${unverified} 列` : null].filter(Boolean).join("・")
  const submit = () => {
    const e: Errors = {}
    if (!date) e.date = "請選日期。"
    if (!name.trim()) e.name = "請寫休市的原因，例如「感恩節」。"
    if (kind === "early_close" && !/^\d{2}:\d{2}$/.test(time)) e.close_time_et = "請寫收盤時間（美東），例如 13:00。"
    setErrors(e)
    if (Object.keys(e).length) return
    put.mutate(
      { date, body: { name: name.trim(), kind, close_time_et: kind === "early_close" ? time : null, source_url: NYSE_URL, verified } },
      {
        onSuccess: (h) => {
          toast.success(`已加入 ${formatDateShort(h.date)} ${h.name}`)
          setDate("")
          setName("")
          setVerified(false)
        },
        onError: failWith(setErrors, "date"),
      },
    )
  }
  return (
    <Section title="美股休市表" titleId="mr-nyse" aside={aside ? <span className="num">{aside}</span> : undefined}>
      <form
        noValidate
        className="grid gap-4 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <Field id={`${id}-date`} label="日期（美東）" error={errors.date}>
          <Input id={`${id}-date`} type="date" value={date} aria-invalid={errors.date ? true : undefined} onChange={(e) => setDate(e.target.value)} className="w-auto self-start" />
        </Field>
        <Field id={`${id}-name`} label="原因" error={errors.name}>
          <Input id={`${id}-name`} value={name} maxLength={80} placeholder="感恩節" aria-invalid={errors.name ? true : undefined} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="種類">
          <RangeChips label="休市種類" value={kind} onChange={setKind} options={[{ value: "closed", label: "休市" }, { value: "early_close", label: "提早收盤" }]} />
        </Field>
        {kind === "early_close" && (
          <Field id={`${id}-time`} label="收盤時間（美東）" error={errors.close_time_et}>
            <Input id={`${id}-time`} value={time} inputMode="numeric" maxLength={5} aria-invalid={errors.close_time_et ? true : undefined} onChange={(e) => setTime(e.target.value)} className="w-28" />
          </Field>
        )}
        <label className="flex items-center gap-2.5 sm:col-span-2">
          <Switch checked={verified} onCheckedChange={setVerified} />
          已經在 NYSE 官方頁面核對過
        </label>
        {errors.source_url && <FieldError>{errors.source_url}</FieldError>}
        <Button type="submit" className="self-start justify-self-start" disabled={put.isPending}>
          新增
        </Button>
      </form>
      <List query={list} empty="休市表是空的" label="美股休市日">
        {(list.data ?? []).map((h) => (
          <li key={h.date} className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-rule py-3">
            <div className="min-w-0 flex-1">
              <p>
                <span className="num font-medium">{formatDateShort(h.date)}</span> {h.name}
                {!h.verified_at && <span className="ml-2 text-sm font-medium text-ink">未核對</span>}
              </p>
              <p className="num text-sm text-ink-2">
                {h.kind === "closed" ? "休市" : `提早收盤 ${h.close_time_et ?? ""}（美東）`}・
                <a href={h.source_url} target="_blank" rel="noopener noreferrer" className="underline decoration-ctl underline-offset-4 hover:text-ink">
                  官方頁面 ↗
                </a>
              </p>
            </div>
            {!h.verified_at && (
              <Button
                variant="outline"
                size="sm"
                disabled={put.isPending}
                onClick={() =>
                  put.mutate(
                    { date: h.date, body: { name: h.name, kind: h.kind, close_time_et: h.close_time_et, source_url: h.source_url, verified: true } },
                    { onSuccess: () => toast.success(`${formatDateShort(h.date)} 已核對`), onError: (err) => toast.error("沒有標記", { description: errText(err) }) },
                  )
                }
              >
                標記已核對
              </Button>
            )}
            <Button variant="outline" size="sm" aria-label={`刪除 ${formatDateShort(h.date)} ${h.name}`} onClick={() => setDeleting(h)}>
              刪除
            </Button>
          </li>
        ))}
      </List>
      {deleting && (
        <ConfirmDelete
          title={`刪除 ${formatDateShort(deleting.date)} ${deleting.name}？`}
          description="報告會把這一天當成美股照常交易。"
          pending={del.isPending}
          onClose={() => setDeleting(null)}
          onConfirm={() => del.mutate(deleting.date, { onSuccess: () => setDeleting(null), onError: (err) => toast.error("沒有刪除", { description: errText(err) }) })}
        />
      )}
    </Section>
  )
}

// ── 總經行事曆 ────────────────────────────────────────
const TZS = [
  { value: "America/New_York", label: "美東" },
  { value: "Asia/Taipei", label: "台北" },
  { value: "Europe/Berlin", label: "歐洲中部" },
  { value: "Asia/Tokyo", label: "東京" },
] as const
const tzLabel = (tz: string) => TZS.find((t) => t.value === tz)?.label ?? tz

function MacroTable() {
  const list = useMacroEvents()
  const add = useAddMacroEvent()
  const del = useDeleteMacroEvent()
  const [deleting, setDeleting] = useState<MacroEvent | null>(null)
  const id = useId()
  const blank = { event_date: "", local_time: "", tz: "America/New_York", country: "US", title: "", agency: "", official_url: "", sectors: "", note: "" }
  const [f, setF] = useState(blank)
  const [errors, setErrors] = useState<Errors>({})
  const set = (k: keyof typeof blank) => (e: React.ChangeEvent<HTMLInputElement>) => setF((x) => ({ ...x, [k]: e.target.value }))
  const submit = () => {
    const e: Errors = {}
    if (!f.event_date) e.event_date = "請選日期。"
    if (!f.title.trim()) e.title = "請寫數據名稱，例如「10 月消費者物價指數」。"
    if (!f.agency.trim()) e.agency = "請寫公布的機關。"
    if (!/^https:\/\//.test(f.official_url.trim())) e.official_url = "請貼官方頁面的網址（https:// 開頭）。"
    setErrors(e)
    if (Object.keys(e).length) return
    add.mutate(
      {
        event_date: f.event_date, local_time: f.local_time || null, tz: f.tz, country: f.tz === "Asia/Taipei" ? "TW" : f.tz === "Asia/Tokyo" ? "JP" : f.tz === "Europe/Berlin" ? "EU" : "US",
        title: f.title.trim(), agency: f.agency.trim(), official_url: f.official_url.trim(), sectors: splitList(f.sectors), note: f.note.trim(),
      },
      {
        onSuccess: (m) => {
          toast.success(`已加入 ${formatDateShort(m.event_date)} ${m.title}`)
          setF(blank)
        },
        onError: failWith(setErrors, "official_url"),
      },
    )
  }
  return (
    <Section title="總經行事曆" titleId="mr-macro" aside={<span className="num">{list.data ? `${list.data.length} 列` : ""}</span>}>
      <form
        noValidate
        className="grid gap-4 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <Field id={`${id}-date`} label="日期（當地）" error={errors.event_date}>
          <Input id={`${id}-date`} type="date" value={f.event_date} aria-invalid={errors.event_date ? true : undefined} onChange={set("event_date")} className="w-auto self-start" />
        </Field>
        <Field id={`${id}-time`} label="時間（當地，選填）">
          <Input id={`${id}-time`} value={f.local_time} placeholder="08:30" inputMode="numeric" maxLength={5} onChange={set("local_time")} className="w-28" />
        </Field>
        <Field label="時區" className="sm:col-span-2">
          <RangeChips label="時區" value={f.tz} onChange={(tz) => setF((x) => ({ ...x, tz }))} options={TZS} />
        </Field>
        <Field id={`${id}-title`} label="數據名稱" error={errors.title}>
          <Input id={`${id}-title`} value={f.title} maxLength={120} placeholder="10 月消費者物價指數" aria-invalid={errors.title ? true : undefined} onChange={set("title")} />
        </Field>
        <Field id={`${id}-agency`} label="公布機關" error={errors.agency}>
          <Input id={`${id}-agency`} value={f.agency} maxLength={80} placeholder="美國勞工統計局" aria-invalid={errors.agency ? true : undefined} onChange={set("agency")} />
        </Field>
        <Field id={`${id}-url`} label="官方頁面" error={errors.official_url} className="sm:col-span-2" hint="只能連到官方網站（例如 bls.gov、dgbas.gov.tw）。">
          <Input id={`${id}-url`} value={f.official_url} type="url" inputMode="url" spellCheck={false} placeholder="https://www.bls.gov/cpi/" aria-invalid={errors.official_url ? true : undefined} onChange={set("official_url")} />
        </Field>
        <Field id={`${id}-sectors`} label="相關類股（選填，用頓號分開）">
          <Input id={`${id}-sectors`} value={f.sectors} placeholder="金融保險、半導體" onChange={set("sectors")} />
        </Field>
        <Field id={`${id}-note`} label="備註（選填）">
          <Input id={`${id}-note`} value={f.note} maxLength={200} onChange={set("note")} />
        </Field>
        <Button type="submit" className="self-start justify-self-start" disabled={add.isPending}>
          新增
        </Button>
      </form>
      <List query={list} empty="還沒有總經數據" label="總經行事曆">
        {(list.data ?? []).map((m) => (
          <li key={m.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-rule py-3">
            <div className="min-w-0 flex-1">
              <p>
                <span className="num font-medium">{formatDateShort(m.event_date)}</span> {m.title}
              </p>
              <p className="num text-sm text-ink-2">
                {[m.local_time ? `${tzLabel(m.tz)} ${m.local_time}` : tzLabel(m.tz), m.agency, ...m.sectors].join("・")}・
                <a href={m.official_url} target="_blank" rel="noopener noreferrer" className="underline decoration-ctl underline-offset-4 hover:text-ink">
                  官方頁面 ↗
                </a>
              </p>
            </div>
            <Button variant="outline" size="sm" aria-label={`刪除 ${formatDateShort(m.event_date)} ${m.title}`} onClick={() => setDeleting(m)}>
              刪除
            </Button>
          </li>
        ))}
      </List>
      {deleting && (
        <ConfirmDelete
          title={`刪除 ${formatDateShort(deleting.event_date)} ${deleting.title}？`}
          description="之後的報告行事曆不會再列這一項。"
          pending={del.isPending}
          onClose={() => setDeleting(null)}
          onConfirm={() => del.mutate(deleting.id, { onSuccess: () => setDeleting(null), onError: (err) => toast.error("沒有刪除", { description: errText(err) }) })}
        />
      )}
    </Section>
  )
}

// ── 美股財報日 ────────────────────────────────────────
const TIMINGS = [
  { value: "amc", label: "盤後" },
  { value: "bmo", label: "盤前" },
  { value: "during", label: "盤中" },
  { value: "unknown", label: "不確定" },
] as const
const timingLabel = (t: UsEarning["timing"]) => TIMINGS.find((x) => x.value === t)?.label ?? t

function EarningsTable() {
  const list = useUsEarnings()
  const add = useAddUsEarning()
  const del = useDeleteUsEarning()
  const [deleting, setDeleting] = useState<UsEarning | null>(null)
  const id = useId()
  const blank = { symbol: "", company: "", report_date: "", timing: "amc" as UsEarning["timing"], time_et: "", official_url: "", sectors: "", note: "" }
  const [f, setF] = useState(blank)
  const [errors, setErrors] = useState<Errors>({})
  const set = (k: keyof typeof blank) => (e: React.ChangeEvent<HTMLInputElement>) => setF((x) => ({ ...x, [k]: e.target.value }))
  const submit = () => {
    const e: Errors = {}
    if (!f.symbol.trim()) e.symbol = "請寫美股代號，例如 NVDA。"
    if (!f.company.trim()) e.company = "請寫公司名稱。"
    if (!f.report_date) e.report_date = "請選日期（美東）。"
    if (f.official_url.trim() && !/^https:\/\//.test(f.official_url.trim())) e.official_url = "網址要用 https:// 開頭。"
    setErrors(e)
    if (Object.keys(e).length) return
    add.mutate(
      {
        symbol: f.symbol.trim().toUpperCase(), company: f.company.trim(), report_date: f.report_date, timing: f.timing, time_et: f.time_et || null,
        official_url: f.official_url.trim() || null, sectors: splitList(f.sectors), note: f.note.trim(),
      },
      {
        onSuccess: (x) => {
          toast.success(`已加入 ${x.company}（${x.symbol}）${formatDateShort(x.report_date)}`)
          setF(blank)
        },
        onError: failWith(setErrors, "symbol"),
      },
    )
  }
  return (
    <Section title="美股財報日" titleId="mr-earnings" aside={<span className="num">{list.data ? `${list.data.length} 列` : ""}</span>}>
      <form
        noValidate
        className="grid gap-4 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <Field id={`${id}-symbol`} label="代號" error={errors.symbol}>
          <Input id={`${id}-symbol`} value={f.symbol} maxLength={10} autoCapitalize="characters" placeholder="NVDA" aria-invalid={errors.symbol ? true : undefined} onChange={set("symbol")} className="w-32" />
        </Field>
        <Field id={`${id}-company`} label="公司" error={errors.company}>
          <Input id={`${id}-company`} value={f.company} maxLength={100} placeholder="輝達" aria-invalid={errors.company ? true : undefined} onChange={set("company")} />
        </Field>
        <Field id={`${id}-date`} label="財報日（美東）" error={errors.report_date}>
          <Input id={`${id}-date`} type="date" value={f.report_date} aria-invalid={errors.report_date ? true : undefined} onChange={set("report_date")} className="w-auto self-start" />
        </Field>
        <Field label="時段">
          <RangeChips label="財報時段" value={f.timing} onChange={(timing) => setF((x) => ({ ...x, timing }))} options={TIMINGS} />
        </Field>
        <Field id={`${id}-url`} label="官方頁面（選填）" error={errors.official_url} className="sm:col-span-2">
          <Input id={`${id}-url`} value={f.official_url} type="url" inputMode="url" spellCheck={false} placeholder="https://investor.example.com/" aria-invalid={errors.official_url ? true : undefined} onChange={set("official_url")} />
        </Field>
        <Field id={`${id}-sectors`} label="相關的台股類股（選填，用頓號分開）">
          <Input id={`${id}-sectors`} value={f.sectors} placeholder="半導體" onChange={set("sectors")} />
        </Field>
        <Field id={`${id}-note`} label="備註（選填）">
          <Input id={`${id}-note`} value={f.note} maxLength={200} onChange={set("note")} />
        </Field>
        <Button type="submit" className="self-start justify-self-start" disabled={add.isPending}>
          新增
        </Button>
      </form>
      <List query={list} empty="還沒有財報日" label="美股財報日">
        {(list.data ?? []).map((x) => (
          <li key={x.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-rule py-3">
            <div className="min-w-0 flex-1">
              <p>
                <span className="num font-medium">{formatDateShort(x.report_date)}</span> {x.company}（{x.symbol}）
              </p>
              <p className="num text-sm text-ink-2">{[`美東${timingLabel(x.timing)}`, ...x.sectors, x.note || null].filter(Boolean).join("・")}</p>
            </div>
            <Button variant="outline" size="sm" aria-label={`刪除 ${x.company} ${formatDateShort(x.report_date)}`} onClick={() => setDeleting(x)}>
              刪除
            </Button>
          </li>
        ))}
      </List>
      {deleting && (
        <ConfirmDelete
          title={`刪除 ${deleting.company} ${formatDateShort(deleting.report_date)}？`}
          description="之後的報告行事曆不會再列這一項。"
          pending={del.isPending}
          onClose={() => setDeleting(null)}
          onConfirm={() => del.mutate(deleting.id, { onSuccess: () => setDeleting(null), onError: (err) => toast.error("沒有刪除", { description: errText(err) }) })}
        />
      )}
    </Section>
  )
}

// ── 共用 ────────────────────────────────────────────
const splitList = (s: string) =>
  s
    .split(/[、,，]/)
    .map((x) => x.trim())
    .filter(Boolean)

function Field({ id, label, error, hint, className, children }: { id?: string; label: string; error?: string; hint?: string; className?: string; children: React.ReactNode }) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      {id ? (
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
      ) : (
        <span className="text-sm font-medium">{label}</span>
      )}
      {children}
      {hint && !error && <p className="text-sm text-ink-2">{hint}</p>}
      {error && <FieldError>{error}</FieldError>}
    </div>
  )
}

function List({ query, empty, label, children }: { query: { isError: boolean; error: unknown; data?: unknown[]; refetch: () => unknown }; empty: string; label: string; children: React.ReactNode }) {
  if (query.isError) return <ErrorState className="mt-4" error={query.error} onRetry={() => void query.refetch()} />
  if (!query.data) return <SkeletonLines rows={3} className="mt-4" />
  if (query.data.length === 0) return <EmptyState className="mt-6" title={empty} />
  return (
    <ul aria-label={label} className="mt-6 border-t border-rule">
      {children}
    </ul>
  )
}

function ConfirmDelete({ title, description, pending, onClose, onConfirm }: { title: string; description: string; pending: boolean; onClose: () => void; onConfirm: () => void }) {
  return (
    <AlertDialog open onOpenChange={(o) => !o && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction disabled={pending} onClick={onConfirm}>
            刪除
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
