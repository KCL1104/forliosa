import { HistoryList } from "@/ai/HistoryList"
import { useAskAi } from "@/ai/use-ask"
import { useReadOnly } from "@/api/view-as"
import { ViewAsBlocked } from "@/app/ViewAsBanner"
import { PageHeader } from "@/components/section"

/**
 * 紀錄：發起新對話、過去的對話、AI 任務（手機分頁；桌面在 AI 面板的紀錄圖示也看得到）。
 * 查看別人的資產時不能用：這裡是查看者自己的 AI 紀錄，AI 也不讀被查看者的資料（和群組、設定一樣擋下）。
 */
export function HistoryPage() {
  const readOnly = useReadOnly()
  if (readOnly) return <ViewAsBlocked title="紀錄" />
  return <History />
}

function History() {
  const ask = useAskAi()
  return (
    <div className="mx-auto w-full max-w-[760px] px-5 pt-2 pb-10 md:px-8 lg:pt-10">
      <PageHeader title="紀錄" className="max-lg:sr-only" />
      <HistoryList onOpen={ask.reveal} onReplay={(t) => ask.submit(t)} />
    </div>
  )
}
