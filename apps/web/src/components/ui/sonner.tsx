import { CircleCheckIcon, InfoIcon, Loader2Icon, OctagonXIcon, TriangleAlertIcon } from "lucide-react"
import { Toaster as Sonner, type ToasterProps } from "sonner"
import { useResolvedTheme } from "@/hooks/use-theme"

/** shadcn/ui 的 Sonner 包裝（改用本專案的主題狀態，不依賴 next-themes） */
function Toaster(props: ToasterProps) {
  const theme = useResolvedTheme()
  return (
    <Sonner
      theme={theme}
      className="toaster group"
      icons={{
        success: <CircleCheckIcon className="size-4" />,
        info: <InfoIcon className="size-4" />,
        warning: <TriangleAlertIcon className="size-4" />,
        error: <OctagonXIcon className="size-4" />,
        loading: <Loader2Icon className="size-4 animate-spin" />,
      }}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "6px",
          "--width": "min(360px, calc(100vw - 32px))",
        } as React.CSSProperties
      }
      toastOptions={{
        classNames: {
          toast: "font-sans text-md shadow-lift",
          description: "text-ink-2!",
          actionButton: "bg-act! text-act-fg! rounded-sm! h-8! px-3! text-sm! font-medium!",
        },
      }}
      {...props}
    />
  )
}

export { Toaster }
