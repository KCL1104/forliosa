import { useEffect } from "react"

const SITE = "Forliosa"

/** 分頁標題的字：「台積電 2330｜Forliosa」；沒有頁名時只有「Forliosa」 */
export const pageTitle = (title?: string | null) => (title ? `${title}｜${SITE}` : SITE)

/**
 * 這一頁的分頁標題（`document.title`）：頁名在前、站名在後——開好幾個分頁、看瀏覽紀錄或書籤時分得出哪一頁，
 * 公開主題的連結貼到聊天軟體時顯示的也是主題的標題。
 * 名稱還沒載入時傳暫時的字（「個股」「主題」），載入後換成真的名字。離開這一頁時不用還原：下一頁會自己設定。
 */
export function usePageTitle(title?: string | null) {
  useEffect(() => {
    document.title = pageTitle(title)
  }, [title])
}
