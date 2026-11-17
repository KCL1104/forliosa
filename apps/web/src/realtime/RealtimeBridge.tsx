import { useQueryClient } from "@tanstack/react-query"
import { useEffect } from "react"
import { api } from "@/api"
import { useMe } from "@/api/queries"
import { viewAsId } from "@/api/view-as"
import { RealtimeController } from "./controller"

/**
 * 即時更新（docs/api-contract.md「即時更新（2026-11-17）」）：登入後每個分頁和伺服器保持一條連線，
 * 別人、自己的另一台裝置或排程改了資料時，畫面上正在顯示的那幾份重新讀，不用重新整理。
 *
 * 掛在登入閘門裡面（帳本的外殼與管理後台都有；沒登入看公開討論的精簡外殼沒有）。換了登入的人就重連，登出時關掉。
 * mock 模式沒有串流（`api.openEvents` 不存在）：狀態一直是 `off`，各個查詢照原本的間隔重新讀。
 * 畫面上不顯示連線狀態（不加「即時」標示、不跳通知）。
 */
export function RealtimeBridge() {
  const qc = useQueryClient()
  const userId = useMe().data?.id
  useEffect(() => {
    const open = api.openEvents
    if (!open || !userId) return
    const controller = new RealtimeController({
      qc,
      open: (last, signal) => open(last, signal),
      viewAs: viewAsId,
      // 開發時只印出種類，不印內容
      debug: import.meta.env.DEV && import.meta.env.MODE !== "test" ? (m) => console.debug(m) : undefined,
    })
    controller.start()
    return () => controller.stop()
  }, [qc, userId])
  return null
}
