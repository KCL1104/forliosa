import { useEffect, useSyncExternalStore } from "react"
import { usePrefs } from "@/stores/prefs"

const DARK_QUERY = "(prefers-color-scheme: dark)"

function subscribeSystem(cb: () => void) {
  const mq = window.matchMedia(DARK_QUERY)
  mq.addEventListener("change", cb)
  return () => mq.removeEventListener("change", cb)
}
const systemIsDark = () => window.matchMedia(DARK_QUERY).matches

/** 實際生效的主題（system 依作業系統） */
export function useResolvedTheme(): "light" | "dark" {
  const theme = usePrefs((s) => s.theme)
  const sysDark = useSyncExternalStore(subscribeSystem, systemIsDark, () => false)
  return theme === "system" ? (sysDark ? "dark" : "light") : theme
}

/** 把主題與漲跌慣例套到 <html>，並同步 theme-color（手機狀態列） */
export function useApplyDocumentPrefs() {
  const resolved = useResolvedTheme()
  const convention = usePrefs((s) => s.colorConvention)
  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle("dark", resolved === "dark")
    root.style.colorScheme = resolved
    root.dataset.convention = convention
    const bg = getComputedStyle(root).getPropertyValue("--background").trim()
    document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute("content", bg || (resolved === "dark" ? "#14161c" : "#f3f5f5")))
  }, [resolved, convention])
}
