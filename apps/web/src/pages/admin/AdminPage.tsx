import { useViewer } from "@/api/queries"
import { useReadOnly } from "@/api/view-as"
import { usePageTitle } from "@/app/page-title"
import { PageFrame } from "@/app/PageFrame"
import { ViewAsBlocked } from "@/app/ViewAsBanner"
import { PageHeader } from "@/components/section"
import { NotFoundPage } from "@/pages/NotFoundPage"

/**
 * 管理後台每一頁的外框：只有站方管理員；其他人是「找不到這個頁面」，查看別人的資產時是擋頁。
 * `children` 是這一頁的內容元件——不是管理員時不會掛上去，也就不會打任何 `/admin` 的請求。
 * 和設定、討論同一個欄寬（816px，靠左）。
 */
export function AdminPage({ title, actions, children }: { title: string; actions?: React.ReactNode; children: React.ReactNode }) {
  const readOnly = useReadOnly()
  const { user } = useViewer()
  usePageTitle(readOnly || user?.is_admin ? `${title}・管理後台` : "找不到這個頁面")
  if (readOnly) return <ViewAsBlocked title="管理後台" />
  if (!user?.is_admin) return <NotFoundPage />
  return (
    <PageFrame>
      <div className="flex max-w-measure flex-col gap-10">
        <PageHeader title={title} actions={actions} className="mb-0" />
        {children}
      </div>
    </PageFrame>
  )
}
