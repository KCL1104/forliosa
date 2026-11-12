/** 「11/12 13:30 收盤」或「10:42 盤中・延遲」 */
export function asOfLabel(iso: string | null | undefined): string {
  if (!iso) return ""
  const d = new Date(iso)
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("zh-TW", { timeZone: "Asia/Taipei", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, weekday: "short" })
      .formatToParts(d)
      .map((p) => [p.type, p.value]),
  )
  const minutes = Number(parts.hour) * 60 + Number(parts.minute)
  const open = minutes >= 9 * 60 && minutes < 13 * 60 + 30
  return open ? `${parts.hour}:${parts.minute} 盤中・延遲` : `${parts.month}/${parts.day} ${parts.hour}:${parts.minute} 收盤`
}

