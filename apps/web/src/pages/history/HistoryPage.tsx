import { HistoryList } from "@/ai/HistoryList"
import { useAskAi } from "@/ai/use-ask"
import { useReadOnly } from "@/api/view-as"
import { ViewAsBlocked } from "@/app/ViewAsBanner"
import { PageFrame } from "@/app/PageFrame"
import { PageHeader } from "@/components/section"
import { usePageTitle } from "@/app/page-title"

/**
 * 紀錄：發起新對話、過去的對話（手機從「問 AI」畫面的時鐘進來；桌面在 AI 面板的紀錄圖示也看得到）。
 * 手機的底部列沒有「紀錄」分頁，所以頁面標題在手機也看得到（不然不知道這是哪一頁）。
 * 查看別人的資產時不能用：這裡是查看者自己的 AI 紀錄，AI 也不讀被查看者的資料（和群組、設定一樣擋下）。
 */
export function HistoryPage() {
  usePageTitle("紀錄")
  const readOnly = useReadOnly()
  if (readOnly) return <ViewAsBlocked title="紀錄" />
  return <History />
}

function History() {
  const ask = useAskAi()
  return (
    <PageFrame>
      {/* 和設定、資料來源同一個欄寬（816px） */}
      <div className="max-w-measure">
        <PageHeader title="紀錄" />
        <HistoryList onOpen={ask.reveal} onReplay={(t) => ask.submit(t)} />
      </div>
    </PageFrame>
  )
}
