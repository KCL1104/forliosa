import { Outlet, useRouterState } from "@tanstack/react-router"
import { lazy, Suspense, useEffect } from "react"
import { isHomePath, isPublicPath, isPublicReadPath } from "@/lib/next-path"
import { RealtimeBridge } from "@/realtime/RealtimeBridge"
import { AdminGate } from "./AdminShell"
import { AppShell } from "./AppShell"
import { AuthGate } from "./AuthGate"
import { isAdminPath } from "./nav"
import { PublicShell } from "./PublicShell"

// 介紹頁只有沒登入的人看得到：另外載入，登入的人不用下載
const HomePage = lazy(() => import("@/pages/home/HomePage").then((m) => ({ default: m.HomePage })))

// 正式站沒登入的首頁轉到行銷網站（產品負責人 2026-11-20）。
// ponytail: 只看正式網址；開發、測試與 pages.dev 預覽仍顯示介紹頁，換網域時要改這裡
const LIVE_HOST = "forliosa.trade"
const MARKETING_HOME = "https://about.forliosa.trade/"

function ToMarketingHome() {
  useEffect(() => window.location.replace(MARKETING_HOME + window.location.search), [])
  return null
}

/**
 * 登入頁與邀請預覽不需要登入；其他頁面先經過登入閘門，再進外殼。沒登入時：
 * - 首頁（`/`）在正式站轉到行銷網站（about.forliosa.trade）；其他網址（開發、預覽）是介紹頁（`pages/home/HomePage.tsx`）。
 *   登入後同一個網址是帳本。
 * - 公開討論的清單與主題頁、服務條款、隱私權政策不用登入就能讀。
 * 這兩種都不導到登入頁，改用精簡的外殼（字標、討論、登入）；其他頁面照舊導到 `/login?next=…`。
 * `/admin*` 是管理後台：站方管理員用自己的外殼（`AdminShell`），其他人照一般的外殼（頁面是「找不到這個頁面」）。
 * 登入後（兩種外殼都是）掛上即時更新（`RealtimeBridge`）：別人或排程改了資料，畫面自己重新讀。
 */
export function RootLayout() {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  if (isPublicPath(pathname)) return <Outlet />
  const signedOut = isHomePath(pathname) ? (
    window.location.hostname === LIVE_HOST ? (
      <ToMarketingHome />
    ) : (
      <PublicShell home>
        <Suspense fallback={null}>
          <HomePage />
        </Suspense>
      </PublicShell>
    )
  ) : isPublicReadPath(pathname) ? (
    <PublicShell />
  ) : undefined
  return (
    <AuthGate signedOut={signedOut}>
      <RealtimeBridge />
      {isAdminPath(pathname) ? <AdminGate /> : <AppShell />}
    </AuthGate>
  )
}
