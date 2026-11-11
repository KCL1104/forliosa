import { useEffect } from "react"
import { useMe } from "@/api/queries"
import { useApplyDocumentPrefs } from "@/hooks/use-theme"
import { usePrefs } from "@/stores/prefs"

/** 套用主題與漲跌慣例；第一次開啟時用伺服器上的偏好初始化本機顯示設定 */
export function PrefsBridge() {
  useApplyDocumentPrefs()
  const me = useMe()
  const synced = usePrefs((s) => s.syncedFromServer)
  const applyServer = usePrefs((s) => s.applyServer)
  useEffect(() => {
    if (me.data && !synced) applyServer(me.data.preferences)
  }, [me.data, synced, applyServer])
  return null
}
