import { CheckIcon, CopyIcon, MinusIcon } from "lucide-react"
import { toast } from "sonner"
import { useSummary } from "@/api/queries"
import { PageHeader, Section } from "@/components/section"
import { Button } from "@/components/ui/button"
import { direction, directionGlyph, formatDateShort, formatPercent, toneClass } from "@/lib/format"
import { appToday } from "@/api"
import { cn } from "@/lib/utils"

const RULES: { label: string; detail: string; on: boolean }[] = [
  { label: "報酬率（百分比）", detail: "今日、今年以來、總報酬。預設分享。", on: true },
  { label: "持股名稱與比重", detail: "預設不分享；你可以逐檔打開。", on: false },
  { label: "金額與股數", detail: "永遠不分享，除非你自己打開。", on: false },
  { label: "排行", detail: "群主可以關閉；不會顯示「誰沒有分享」。", on: true },
]

/** 群組（M5）：先把規則與分享卡做出來，群組本身在 M5 開放 */
export function GroupsPage() {
  const summary = useSummary()
  const s = summary.data
  const today = appToday()
  const line = s ? `我今天 ${glyphPct(s.day_change_pct)}，總報酬 ${glyphPct(s.total_return_pct)}（Forliosa ${formatDateShort(today, false)}）` : ""
  return (
    <div className="mx-auto w-full max-w-[880px] px-5 pt-2 pb-10 md:px-8 lg:pt-10">
      <PageHeader title="群組" description="和家人朋友比較報酬，只分享你允許的部分。" />
      <p className="border-y border-rule py-4 text-base">
        <span className="font-medium">群組在 M5 開放。</span>
        <span className="text-ink-2">現在可以先看規則，也可以複製分享卡貼到 LINE。</span>
      </p>

      <Section title="你可以控制分享什麼" titleId="g-rules" className="mt-10">
        <ul className="-mt-3">
          {RULES.map((r) => (
            <li key={r.label} className="flex items-start gap-3 border-b border-rule py-3.5">
              <span className={cn("mt-0.5 grid size-5 shrink-0 place-items-center rounded-xs border", r.on ? "border-ink bg-act text-act-fg" : "border-ctl text-ink-2")} aria-hidden>
                {r.on ? <CheckIcon className="size-3.5" /> : <MinusIcon className="size-3.5" />}
              </span>
              <span>
                <span className="block font-medium">{r.label}</span>
                <span className="block text-md text-ink-2">{r.detail}</span>
              </span>
              <span className="ml-auto shrink-0 text-sm text-ink-2">{r.on ? "預設分享" : "預設不分享"}</span>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="分享卡" titleId="g-card" aside="只有百分比，沒有金額" className="mt-10">
        <figure className="max-w-sm border border-rule bg-raised">
          <div className="flex items-baseline justify-between border-b border-rule px-5 py-3">
            <span className="text-lg font-bold">Forliosa</span>
            <span className="num text-sm text-ink-2">{formatDateShort(today)}</span>
          </div>
          <dl className="grid grid-cols-2">
            <div className="border-r border-rule px-5 py-4">
              <dt className="text-sm text-ink-2">今日</dt>
              <dd className={cn("num mt-1 text-3xl font-medium", toneClass(direction(s?.day_change_pct)))}>{s ? glyphPct(s.day_change_pct) : "—"}</dd>
            </div>
            <div className="px-5 py-4">
              <dt className="text-sm text-ink-2">總報酬（含股利）</dt>
              <dd className={cn("num mt-1 text-3xl font-medium", toneClass(direction(s?.total_return_pct)))}>{s ? glyphPct(s.total_return_pct) : "—"}</dd>
            </div>
          </dl>
        </figure>
        <Button
          variant="outline"
          className="mt-4"
          disabled={!s}
          onClick={() => {
            void navigator.clipboard?.writeText(line).then(
              () => toast.success("已複製，可以貼到 LINE"),
              () => toast.error("沒有複製成功", { description: line }),
            )
          }}
        >
          <CopyIcon />
          複製分享文字
        </Button>
        {s && <p className="mt-2 text-sm text-ink-2">「{line}」</p>}
      </Section>
    </div>
  )
}

function glyphPct(r: number | null): string {
  const d = direction(r)
  return `${directionGlyph(d)}${formatPercent(r === null ? null : Math.abs(r), { signed: false, decimals: Math.abs(r ?? 0) >= 0.1 ? 1 : 2 })}`
}
