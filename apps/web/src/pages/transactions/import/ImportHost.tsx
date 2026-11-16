import { lazy, Suspense, useState } from "react"
import { useUi } from "@/app/ui-store"

const ImportDialog = lazy(() => import("./ImportDialog").then((m) => ({ default: m.ImportDialog })))

/**
 * 掛在 AppShell：第一次打開「匯入對帳單」才下載這個畫面（pdf.js 更晚，選了 PDF 才載入）。
 * 打開過之後留著，關掉時對話框的動畫照常。
 */
export function ImportHost() {
  const open = useUi((s) => s.importOpen)
  const [mounted, setMounted] = useState(open)
  if (open && !mounted) setMounted(true)
  if (!mounted) return null
  return (
    <Suspense fallback={null}>
      <ImportDialog />
    </Suspense>
  )
}
