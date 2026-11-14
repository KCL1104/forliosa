import { Outlet, useRouterState } from "@tanstack/react-router"
import { lazy, Suspense } from "react"
import { isHomePath, isPublicPath, isPublicReadPath } from "@/lib/next-path"
import { AdminGate } from "./AdminShell"
import { AppShell } from "./AppShell"
import { AuthGate } from "./AuthGate"
import { isAdminPath } from "./nav"
import { PublicShell } from "./PublicShell"

// 介紹頁只有沒登入的人看得到：另外載入，登入的人不用下載
const HomePage = lazy(() => import("@/pages/home/HomePage").then((m) => ({ default: m.HomePage })))

/**
 * 登入頁與邀請預覽不需要登入；其他頁面先經過登入閘門，再進外殼。沒登入時：
 * - 首頁（`/`）是介紹頁（`pages/home/HomePage.tsx`），不是登入頁；登入後同一個網址是帳本。
 * - 公開討論的清單與主題頁、服務條款、隱私權政策不用登入就能讀。
 * 這兩種都不導到登入頁，改用精簡的外殼（字標、討論、登入）；其他頁面照舊導到 `/login?next=…`。
 * `/admin*` 是管理後台：站方管理員用自己的外殼（`AdminShell`），其他人照一般的外殼（頁面是「找不到這個頁面」）。
 */
export function RootLayout() {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  if (isPublicPath(pathname)) return <Outlet />
  const signedOut = isHomePath(pathname) ? (
    <PublicShell home>
      <Suspense fallback={null}>
        <HomePage />
      </Suspense>
    </PublicShell>
  ) : isPublicReadPath(pathname) ? (
    <PublicShell />
  ) : undefined
  return (
    <AuthGate signedOut={signedOut}>
      {isAdminPath(pathname) ? <AdminGate /> : <AppShell />}
    </AuthGate>
  )
}
