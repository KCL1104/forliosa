import { kaiSize } from "@/ai/kai-size"
import { KaiText } from "@/ai/kai-text"
import { useCompany } from "@/api/queries"
import type { CompanyAbout, InstrumentDetail } from "@/api/types"
import { Skeleton } from "@/components/ui/skeleton"
import { useSourceNote } from "@/hooks/use-source-note"
import { displayHost, fiscalYearEnd, formatCapital } from "@/lib/company"
import { formatDate, formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"
import { QuietSection } from "./tabs/kit"
import { sourceNotes } from "./text"

type Row = { label: string; value: React.ReactNode; title?: string }

/** `extra`：總覽的鍵值帶只剩一兩格時（美股沒有行情時的近四季 EPS）併進來的格子，排在公司資料後面、曾用名稱前面 */
function aboutRows(c: CompanyAbout | undefined, inst: InstrumentDetail, extra: Row[] = []): Row[] {
  if (!c) return extra
  const rows: Row[] = []
  const add = (label: string, value: React.ReactNode | null | undefined) => {
    if (value !== null && value !== undefined && value !== "") rows.push({ label, value })
  }
  if (c.market === "US") {
    add("產業", c.industry)
    add("總部", c.hq)
    add("交易所", c.exchanges?.join("、"))
    add("會計年度結束", c.fiscal_year_end ? fiscalYearEnd(c.fiscal_year_end) : null)
    rows.push(...extra)
    add("曾用名稱", c.former_names?.length ? c.former_names.map((f) => f.name).join("、") : null)
    return rows
  }
  if (c.type === "etf") {
    add("基金類型", c.fund?.fund_type)
    add("追蹤指數", c.fund?.index_name)
    add("成立日期", c.incorporated ? formatDate(c.incorporated) : null)
    add(`${c.listing ?? "上市"}日期`, c.listed_date ? formatDate(c.listed_date) : null)
    return [...rows, ...extra]
  }
  add("產業別", c.industry)
  add("成立日期", c.incorporated ? `${formatDate(c.incorporated)}・成立 ${c.years_since_incorporation ?? "—"} 年` : null)
  add(`${c.listing ?? "上市"}日期`, c.listed_date ? formatDate(c.listed_date) : null)
  if (c.registered_in) add("註冊地", c.registered_in)
  else add("總部", c.hq)
  add(
    "網站",
    c.website ? (
      <a href={c.website} target="_blank" rel="noopener noreferrer" className="break-all underline decoration-ctl underline-offset-3 after:absolute after:inset-0 hover:decoration-ink">
        {displayHost(c.website)}
        <span className="sr-only">（另開新視窗）</span>
      </a>
    ) : null,
  )
  add("實收資本額", c.paid_in_capital ? formatCapital(c.paid_in_capital) : null)
  add("董事長", c.chairman)
  add("總經理", c.president)
  add("簽證會計師事務所", c.auditor)
  add("股務代理", c.transfer_agent)
  add("發行股數", inst.shares_outstanding ? `${formatNumber(Math.round(inst.shares_outstanding / 1000))} 張` : null)
  if (inst.chain_stage) add("產業鏈", inst.chain_stage)
  if (inst.themes.length) add("題材", inst.themes.join("・"))
  return [...rows, ...extra]
}

/**
 * 關於〈公司〉（Google 財經的「資料」＋「關於」）：
 * - 簡介：中文維基百科節錄（原文、不改寫，標「節錄」並連到條目與 CC BY-SA 4.0——授權要求標在內容旁），
 *   沒有條目時是 AI 依官方資料寫的 2–3 句（模型寫的字：紫色楷體、標「AI 依公開資料整理」）。
 * - 緊湊的兩欄鍵值格：產業別、成立日期（成立 N 年）、上市／上櫃日期、總部、網站、實收資本額、董事長、總經理…
 * - 資料日期留在格子下面；資料來源登記到頁尾。
 * - `extra`：總覽第一層只剩一兩格時（美股沒有行情，只有近四季 EPS）併到這張鍵值格，不在分頁列下面單獨畫一條細帶。
 */
export function AboutCompany({ inst, extra }: { inst: InstrumentDetail; extra?: Row[] }) {
  const company = useCompany(inst.symbol)
  const c = company.data
  useSourceNote(sourceNotes(c?.sources.length ? c.sources : inst.data_sources))
  if (company.isLoading) return <Skeleton className="h-48 w-full rounded-sm" />
  const name = c?.short_name || inst.name
  const rows = aboutRows(c, inst, extra)
  const d = c?.description ?? null
  // 個人模式的 shioaji-data 研究摘要只在沒有維基百科／AI 簡介時顯示（commercial 為 null）
  const summary = d ? null : inst.summary
  if (!c && !summary) return null
  return (
    <QuietSection title={`關於「${name}」`} titleId="ov-company">
      {d && (
        <div className="max-w-prose pt-2">
          {d.kind === "ai" ? (
            // 模型寫的簡介：和對話裡的回答同一套排版（17px／手機 18px、行高 1.8、`KaiText`）
            <p className={cn("ai-voice", kaiSize.page)}>
              <KaiText text={d.text} />
            </p>
          ) : (
            <p className="text-base leading-relaxed text-ink">{d.text}</p>
          )}
          <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-2">
            <span className="demo-tag">{d.label}</span>
            {d.kind === "wikipedia" && d.url ? (
              <>
                <a href={d.url} target="_blank" rel="noopener noreferrer" className="underline decoration-ctl underline-offset-3 hover:text-ink hover:decoration-ink pointer-coarse:py-3">
                  維基百科「{d.title}」條目
                  <span className="sr-only">（另開新視窗）</span>
                </a>
                <span aria-hidden>・</span>
                <a href={d.license_url ?? undefined} target="_blank" rel="noopener noreferrer" className="underline decoration-ctl underline-offset-3 hover:text-ink hover:decoration-ink pointer-coarse:py-3">
                  {d.license}
                  <span className="sr-only">授權條款（另開新視窗）</span>
                </a>
              </>
            ) : null}
          </p>
        </div>
      )}
      {summary && <p className="max-w-prose pt-2 text-base">{summary}</p>}
      {rows.length > 0 && (
        // 兩欄（手機一欄）；單數格時最後一格撐滿兩欄，最後一列不留孤格、格線連成一條
        <dl className={cn("grid gap-x-8 sm:grid-cols-2", (d || summary) && "mt-4 border-t border-rule")}>
          {rows.map((r) => (
            <div key={r.label} title={r.title} className="relative flex min-h-11 items-baseline justify-between gap-4 border-b border-rule py-2.5 sm:last:odd:col-span-2">
              <dt className="shrink-0 text-md text-ink-2">{r.label}</dt>
              <dd className="min-w-0 text-right text-base break-words text-ink">{r.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {((c?.notes ?? []).length > 0 || c?.data_date) && (
        <div className="mt-2 flex flex-col gap-0.5 text-sm text-ink-2">
          {(c?.notes ?? []).map((n) => (
            <p key={n}>{n}</p>
          ))}
          {c?.data_date && <p className="num">資料日期：{formatDate(c.data_date)}</p>}
        </div>
      )}
    </QuietSection>
  )
}
