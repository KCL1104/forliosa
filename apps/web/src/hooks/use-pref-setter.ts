import { toast } from "sonner"
import { useUpdatePreferences } from "@/api/queries"
import type { Preferences } from "@/api/types"
import { usePrefs, type PrefsState } from "@/stores/prefs"

export type PrefPatch = Partial<
  Pick<PrefsState, "colorConvention" | "theme" | "quantityUnit" | "privacyDefault" | "costMethod" | "benchmark" | "compactNumbers">
>

/** 本機立即生效，再以 `PATCH /me/preferences` 同步到伺服器；失敗時還原並通知 */
export function usePrefSetter() {
  const set = usePrefs((s) => s.set)
  const mutation = useUpdatePreferences()
  return (patch: PrefPatch) => {
    const before = Object.fromEntries(Object.keys(patch).map((k) => [k, usePrefs.getState()[k as keyof PrefPatch]])) as PrefPatch
    set(patch)
    const server: Partial<Preferences> = {}
    if (patch.colorConvention) server.color_convention = patch.colorConvention
    if (patch.theme) server.theme = patch.theme
    if (patch.quantityUnit) server.quantity_unit = patch.quantityUnit
    if (patch.privacyDefault !== undefined) server.privacy_mode = patch.privacyDefault
    if (patch.costMethod) server.cost_method = patch.costMethod
    if (patch.benchmark) server.benchmark = patch.benchmark
    if (Object.keys(server).length === 0) return
    mutation.mutate(server, {
      onError: (err) => {
        set(before)
        toast.error("設定沒有存到伺服器，已還原", { description: err instanceof Error ? err.message : "請檢查網路後再試一次。" })
      },
    })
  }
}
