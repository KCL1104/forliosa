import { HistoryList } from "@/ai/HistoryList"
import { useAskAi } from "@/ai/use-ask"
import { PageHeader } from "@/components/section"

/** 紀錄：發起新對話、過去的對話、AI 任務（手機分頁；桌面在 AI 面板的紀錄圖示也看得到） */
export function HistoryPage() {
  const ask = useAskAi()
  return (
    <div className="mx-auto w-full max-w-[760px] px-5 pt-2 pb-10 md:px-8 lg:pt-10">
      <PageHeader title="紀錄" description="問過的問題、AI 寫的草稿，和排定的 AI 任務。" className="max-lg:sr-only" />
      <HistoryList onOpen={ask.reveal} onReplay={(t) => ask.submit(t)} />
    </div>
  )
}
