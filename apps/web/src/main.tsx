import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { RouterProvider } from "@tanstack/react-router"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { PrefsBridge } from "@/app/PrefsBridge"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { createAppRouter } from "@/router"
import "@/styles/globals.css"

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
})
const router = createAppRouter(queryClient)

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
