/** recharts 共用設定：細線、淡格線、等寬刻度 */
export const AXIS_TICK = { fontSize: 12, fill: "var(--muted-foreground)" } as const
export const GRID_STROKE = "var(--chart-grid)"

/** 月份刻度：2026-03 → 3月、跨年時 2026 */
export function monthTick(t: string): string {
  const [y, m] = t.split("-")
  return m === "01" ? `${y}` : `${Number(m)}月`
}
