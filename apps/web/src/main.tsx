import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { RouterProvider } from "@tanstack/react-router"
import { StrictMode, useEffect } from "react"
import { createRoot } from "react-dom/client"
import { useMe } from "@/api/queries"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { useApplyDocumentPrefs } from "@/hooks/use-theme"
import { createAppRouter } from "@/router"
import { usePrefs } from "@/stores/prefs"
import "@/styles/globals.css"

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
})
const router = createAppRouter(queryClient)

/** 第一次開啟時，用伺服器上的偏好初始化本機顯示設定 */
function PrefsBridge() {
  useApplyDocumentPrefs()
  const me = useMe()
  const synced = usePrefs((s) => s.syncedFromServer)
  const applyServer = usePrefs((s) => s.applyServer)
  useEffect(() => {
    if (me.data && !synced) applyServer(me.data.preferences)
  }, [me.data, synced, applyServer])
  return null
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delay={300}>
        <PrefsBridge />
        <RouterProvider router={router} />
        <Toaster position="top-center" offset={{ top: "calc(env(safe-area-inset-top, 0px) + 12px)" }} />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
)
