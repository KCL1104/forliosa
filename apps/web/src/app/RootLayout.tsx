import { Outlet, useRouterState } from "@tanstack/react-router"
import { isPublicPath } from "@/lib/next-path"
import { AppShell } from "./AppShell"
import { AuthGate } from "./AuthGate"

/** 登入頁與邀請預覽不需要登入；其他頁面先經過登入閘門，再進外殼 */
export function RootLayout() {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  if (isPublicPath(pathname)) return <Outlet />
  return (
    <AuthGate>
      <AppShell />
    </AuthGate>
  )
}
