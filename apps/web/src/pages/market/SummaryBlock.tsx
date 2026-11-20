import type { MarketSummary } from "@/api/types"
import { kaiSize } from "@/ai/kai-size"
import { KaiText } from "@/ai/kai-text"
import { CitedSources } from "@/components/cited-sources"
import { Disclaimer } from "@/components/disclaimer"
import { Tray, type TrayTint } from "@/components/tray"
import { formatDateShort } from "@/lib/format"
import { cn } from "@/lib/utils"

/**
 * AI 整理的收盤重點：每個交易日一則、所有人看到同一則。模型寫的字是鉛筆（黑體（墨色，`.ai-voice`），`.ai-voice`＋`KaiText`，
 * 和對話裡的回答同一套排法）；每一點下面列出它依據的報導（媒體名稱，連到原文），最後一句免責（`ai`）。沒有就整塊不出現。
 * 一盤（托盤），標題與標示照舊（「收盤重點」「AI 整理・11/12」）；寬的時候在類股的左邊，閱讀寬度最多 46rem。
 */
export function SummaryBlock({ summary, tint, className }: { summary: MarketSummary; tint?: TrayTint; className?: string }) {
  return (
    <Tray title="收盤重點" meta={`AI 整理・${formatDateShort(summary.date, false)}`} tint={tint} className={className} bodyClassName="max-w-[46rem]">
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
      <Disclaimer kind="ai" className="mt-3" />
    </Tray>
  )
}

/** 這一點依據的報導：媒體名稱（同一家只列一次），13px 淡墨、常駐底線；連到原文、另開視窗 */
