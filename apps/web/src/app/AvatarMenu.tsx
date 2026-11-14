import { useNavigate, useRouterState } from "@tanstack/react-router"
import { CalendarSyncIcon, LogOutIcon, ScrollTextIcon, SettingsIcon, WalletIcon } from "lucide-react"
import { api } from "@/api"
import { useMe } from "@/api/queries"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { usePrefSetter } from "@/hooks/use-pref-setter"
import { usePrefs } from "@/stores/prefs"
import type { ColorConvention, ThemePreference } from "@/api/types"
import { isAccountRoute } from "./nav"
import { clearLocalUserData } from "@/lib/local-data"

/**
 * 頭像選單：設定、帳戶、定期定額、資料來源與授權、外觀（主題與漲跌顏色）、登出。
 * 管理後台不在這裡（2026-11-14 移出，產品負責人）：站方管理員從 ⌘K 的「管理後台」或直接打 `/admin` 進去。
 * 設定與資料來源頁沒有自己的導覽分頁，是從這個選單進去的：桌面在這些頁面時，頭像下面畫導覽的那條線
 * （選取語法 (a)，`data-active`——不是連結，所以不標 `aria-current`），選單裡對應的項目標 `aria-current="page"`。
 */
export function AvatarMenu() {
  const me = useMe()
  const navigate = useNavigate()
  const theme = usePrefs((s) => s.theme)
  const convention = usePrefs((s) => s.colorConvention)
  const setPref = usePrefSetter()
  const name = me.data?.display_name ?? "我"
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const here = (path: string) => (pathname === path ? ("page" as const) : undefined)
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <button
            type="button"
            aria-label={`帳號選單（${name}）`}
            data-active={isAccountRoute(pathname) ? "" : undefined}
            // 桌面：按鈕撐滿頂部列的高度，選取的 2px 墨色線壓在頂部列的格線上（和「帳本／群組」同一套）
            className="group/avatar grid size-11 place-items-center rounded-full lg:-mb-px lg:h-auto lg:w-10 lg:self-stretch lg:rounded-none lg:sel-tab"
          />
        }
      >
        <span aria-hidden className="grid size-9 place-items-center rounded-full bg-sel text-base font-medium text-ink transition-transform duration-150 ease-out group-active/avatar:scale-[0.97]">
          {name.slice(0, 1)}
        </span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="flex flex-col gap-0.5 py-2">
            <span className="text-md font-medium text-ink">{name}</span>
            <span className="truncate text-sm font-normal text-ink-2">{me.data?.email}</span>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem aria-current={here("/settings")} onClick={() => void navigate({ to: "/settings" })}>
          <SettingsIcon aria-hidden />
          設定
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => void navigate({ to: "/settings", hash: "accounts" })}>
          <WalletIcon aria-hidden />
          帳戶
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => void navigate({ to: "/settings", hash: "recurring" })}>
          <CalendarSyncIcon aria-hidden />
          定期定額
        </DropdownMenuItem>
        <DropdownMenuItem aria-current={here("/data-sources")} onClick={() => void navigate({ to: "/data-sources" })}>
          <ScrollTextIcon aria-hidden />
          資料來源與授權
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuLabel className="text-sm text-ink-2">外觀</DropdownMenuLabel>
          <DropdownMenuRadioGroup value={theme} onValueChange={(v) => setPref({ theme: v as ThemePreference })}>
            <DropdownMenuRadioItem value="light">淺色（紙白）</DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="dark">深色（夜間筆記本）</DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="system">跟隨系統</DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuLabel className="text-sm text-ink-2">漲跌顏色</DropdownMenuLabel>
          <DropdownMenuRadioGroup value={convention} onValueChange={(v) => setPref({ colorConvention: v as ColorConvention })}>
            <DropdownMenuRadioItem value="tw">
              紅漲綠跌 <span className="text-[var(--red)]">▲</span>
              <span className="text-[var(--green)]">▼</span>
            </DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="us">
              綠漲紅跌 <span className="text-[var(--green)]">▲</span>
              <span className="text-[var(--red)]">▼</span>
            </DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>
        {api.kind === "http" && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() =>
                void api.logout().then(() => {
                  // 這台瀏覽器上的 AI 對話與沒送出的草稿跟著登出清掉（下一個登入的人看不到）
                  clearLocalUserData()
                  window.location.reload()
                })
              }
            >
              <LogOutIcon aria-hidden />
              登出
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
