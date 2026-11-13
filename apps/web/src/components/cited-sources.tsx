/**
 * AI 寫的一段重點下面的來源列（收盤簡報、市場頁的收盤重點共用）：
 * 一行 13px 淡墨的媒體名，同一家只列一次，連到原文（另開新視窗）。
 * 觸控時每個連結至少 44×44（2026-11-14 第六次評分：兩份複製的版本分岔了，抽成這一個）。
 */
export interface CitedSource {
  url: string
  title?: string | null
  outlet?: string | null
}

export function CitedSources({ sources }: { sources: CitedSource[] }) {
  const seen = new Set<string>()
  const unique = sources.filter((s) => {
    const key = s.outlet || hostOf(s.url)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
  if (unique.length === 0) return null
  return (
    <p className="mt-1 flex flex-wrap items-center gap-x-3 text-sm text-ink-2">
      {unique.map((s) => (
        <a
          key={s.url}
          href={s.url}
          target="_blank"
          rel="noopener noreferrer"
          title={s.title || undefined}
          className="inline-flex items-center underline decoration-ctl decoration-1 underline-offset-4 transition-[text-decoration-color,color] hover:text-ink hover:decoration-ink pointer-coarse:min-h-11 pointer-coarse:min-w-11"
        >
          {s.outlet || hostOf(s.url)}
          <span className="sr-only">：{s.title}（另開新視窗）</span>
        </a>
      ))}
    </p>
  )
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "")
  } catch {
    return "來源"
  }
}
