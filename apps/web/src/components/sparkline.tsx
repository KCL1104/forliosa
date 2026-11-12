import { cn } from "@/lib/utils"

/**
 * 迷你走勢（觀察列、總資產旁）：一條 1.5px 線＋可選的虛線基準（昨收或期初）。
 * 顏色：漲跌用 rise／fall（價格）；資產走勢用墨色。
 */
export function Sparkline({
  values,
  baseline,
  tone = "ink",
  width = 128,
  height = 32,
  label,
  dot,
  className,
}: {
  values: number[]
  baseline?: number | null
  tone?: "up" | "down" | "flat" | "ink"
  width?: number
  height?: number
  label: string
  dot?: boolean
  className?: string
}) {
  if (values.length < 2) {
    return <span className={cn("inline-block text-xs text-ink-2", className)} style={{ width }}>—</span>
  }
  const all = baseline !== null && baseline !== undefined ? [...values, baseline] : values
  const min = Math.min(...all)
  const max = Math.max(...all)
  const span = max - min || 1
  const pad = 2
  const x = (i: number) => (i / (values.length - 1)) * width
  const y = (v: number) => pad + (1 - (v - min) / span) * (height - pad * 2)
  const d = values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join("")
  const color = tone === "up" ? "var(--rise)" : tone === "down" ? "var(--fall)" : tone === "flat" ? "var(--ink-2)" : "var(--ink)"
  return (
    <svg role="img" aria-label={label} viewBox={`0 0 ${width} ${height}`} width={width} height={height} className={cn("shrink-0 overflow-visible", className)}>
      {baseline !== null && baseline !== undefined && (
        <path d={`M0 ${y(baseline).toFixed(1)}H${width}`} stroke="var(--rule)" strokeDasharray="3 3" fill="none" />
      )}
      <path d={d} stroke={color} strokeWidth={1.5} fill="none" strokeLinejoin="round" strokeLinecap="round" />
      {dot && <circle cx={x(values.length - 1)} cy={y(values.at(-1)!)} r={3} fill={color} />}
    </svg>
  )
}
