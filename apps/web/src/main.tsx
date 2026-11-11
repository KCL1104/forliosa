import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { RouterProvider } from "@tanstack/react-router"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { ApiError } from "@/api/types"
import { qk } from "@/api/queries"
import { AuthGate } from "@/app/AuthGate"
import { PrefsBridge } from "@/app/PrefsBridge"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { createAppRouter } from "@/router"
import "@/styles/globals.css"

/** Session 過期或被登出：任何 401 都把 `me` 重設，AuthGate 會回到登入畫面 */
function onApiError(err: unknown, key?: readonly unknown[]) {
  if (err instanceof ApiError && err.status === 401 && key?.[0] !== qk.me[0]) {
    void queryClient.resetQueries({ queryKey: qk.me })
  }
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: (err, query) => onApiError(err, query.queryKey) }),
  mutationCache: new MutationCache({ onError: (err) => onApiError(err) }),
  defaultOptions: {
    queries: {
      // 4xx（找不到、未登入、參數錯誤）重試也不會變好；網路錯誤與 5xx 重試一次
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 1,
      refetchOnWindowFocus: false,
    },
  },
})
const router = createAppRouter(queryClient)

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delay={300}>
        <PrefsBridge />
        <AuthGate>
          <RouterProvider router={router} />
        </AuthGate>
        <Toaster position="top-center" offset={{ top: "calc(env(safe-area-inset-top, 0px) + 12px)" }} />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
)
