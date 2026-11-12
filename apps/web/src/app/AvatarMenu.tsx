import { useNavigate } from "@tanstack/react-router"
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

/** 頭像選單：設定、帳戶、定期定額、資料來源與授權、外觀（主題與漲跌顏色）、登出 */
export function AvatarMenu() {
  const me = useMe()
  const navigate = useNavigate()
  const theme = usePrefs((s) => s.theme)
  const convention = usePrefs((s) => s.colorConvention)
  const setPref = usePrefSetter()
  const name = me.data?.display_name ?? "我"
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <button
            type="button"
            aria-label={`帳號選單（${name}）`}
            className="press grid size-11 place-items-center rounded-full lg:size-10"
          />
        }
      >
        <span aria-hidden className="grid size-9 place-items-center rounded-full bg-act text-base font-medium text-act-fg">
          {name.slice(0, 1)}
        </span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="flex flex-col gap-0.5 py-2">
            <span className="text-md font-medium text-ink">{name}</span>
            <span className="truncate text-xs font-normal text-ink-2">{me.data?.email}</span>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => void navigate({ to: "/settings" })}>
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
        <DropdownMenuItem onClick={() => void navigate({ to: "/data-sources" })}>
          <ScrollTextIcon aria-hidden />
          資料來源與授權
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuLabel className="text-xs text-ink-2">外觀</DropdownMenuLabel>
          <DropdownMenuRadioGroup value={theme} onValueChange={(v) => setPref({ theme: v as ThemePreference })}>
            <DropdownMenuRadioItem value="light">淺色（紙白）</DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="dark">深色（夜間筆記本）</DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="system">跟隨系統</DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuLabel className="text-xs text-ink-2">漲跌顏色</DropdownMenuLabel>
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
            <DropdownMenuItem onClick={() => void api.logout().then(() => window.location.reload())}>
              <LogOutIcon aria-hidden />
              登出
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
