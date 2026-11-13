import type { MarketSummary } from "@/api/types"
import { kaiSize } from "@/ai/kai-size"
import { KaiText } from "@/ai/kai-text"
import { CitedSources } from "@/components/cited-sources"
import { Section } from "@/components/section"
import { formatDateShort } from "@/lib/format"
import { cn } from "@/lib/utils"

/**
 * AI 整理的收盤重點：每個交易日一則、所有人看到同一則。模型寫的字是鉛筆（石墨灰楷體，`.ai-voice`＋`KaiText`，
 * 和對話裡的回答同一套排法）；每一點下面列出它依據的報導（媒體名稱，連到原文）。沒有就整塊不出現。
 */
export function SummaryBlock({ summary }: { summary: MarketSummary }) {
  return (
    <Section title="收盤重點" titleId="market-summary" aside={<span className="num">AI 整理・{formatDateShort(summary.date, false)}</span>} bodyClassName="max-w-[46rem]">
      {summary.headline && (
        <p className={cn("ai-voice pb-1", kaiSize.line)}>
          <KaiText text={summary.headline} />
        </p>
      )}
      <ul>
        {summary.points.map((p, n) => (
          <li key={n} className="border-b border-rule py-3">
            <p className={cn("ai-voice", kaiSize.page)}>
              <KaiText text={p.text} />
            </p>
            <CitedSources sources={p.sources} />
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-ink-2">AI 依這些報導整理，內容以原報導為準。</p>
    </Section>
  )
}

/** 這一點依據的報導：媒體名稱（同一家只列一次），13px 淡墨、常駐底線；連到原文、另開視窗 */
