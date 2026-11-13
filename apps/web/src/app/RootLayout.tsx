import { Outlet, useRouterState } from "@tanstack/react-router"
import { isPublicPath, isPublicReadPath } from "@/lib/next-path"
import { AppShell } from "./AppShell"
import { AuthGate } from "./AuthGate"
import { PublicShell } from "./PublicShell"

/**
 * 登入頁與邀請預覽不需要登入；其他頁面先經過登入閘門，再進外殼。
 * 公開討論的清單與主題頁不用登入就能讀：沒登入時不導到登入頁，改用精簡的外殼（字標＋登入）。
 */
export function RootLayout() {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  if (isPublicPath(pathname)) return <Outlet />
  return (
    <AuthGate signedOut={isPublicReadPath(pathname) ? <PublicShell /> : undefined}>
      <AppShell />
    </AuthGate>
  )
}
