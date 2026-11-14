import { InfoIcon } from "lucide-react"
import type { PushTarget, ShareSettings } from "@/api/types"
import { Switch } from "@/components/ui/switch"
import { cn } from "@/lib/utils"
import { SHARE_COPY, SHARE_KEYS } from "./labels"

/**
 * 每人每群組的六個分享開關（接受邀請前與「我的分享」共用）。
 * - 附上成交價：交易動態打開才能改（關著時保存但沒有作用）
 * - 持股＋金額同時打開：旁邊提示別人可以推算大約股數
 * - 推播：列出群組推播到哪些頻道（邀請預覽時還不知道，寫成一般說明）；成員（不是擁有者）另外說明群組換頻道時會自動關掉
 *   （伺服器在擁有者換推播目的地時關掉其他人的推播；群組第一次設定頻道不影響，所以還沒有頻道時不說）
 */
export function ShareToggles({
  value,
  onChange,
  pushTargets,
  pushAutoOff,
  disabled,
  idPrefix = "share",
}: {
  value: ShareSettings
  onChange: (next: ShareSettings) => void
  /** undefined：還不知道（接受邀請前） */
  pushTargets?: PushTarget[]
  /** 成員（不是擁有者）：擁有者換推播頻道時，自己的推播會被關掉 */
  pushAutoOff?: boolean
  disabled?: boolean
  idPrefix?: string
}) {
  const set = (key: keyof ShareSettings, on: boolean) => onChange({ ...value, [key]: on })
  return (
    <ul className="flex flex-col border-t border-rule">
      {SHARE_KEYS.map((key) => {
        const nested = key === "trade_prices"
        const locked = nested && !value.trades
        const id = `${idPrefix}-${key}`
        const autoOff = key === "push" && pushAutoOff && !!pushTargets?.length
        return (
          <li key={key} className={cn("flex items-start gap-4 border-b border-rule py-3.5", nested && "pl-5")}>
            <div className="min-w-0 flex-1">
              <label htmlFor={id} className={cn("font-medium", locked && "text-ink-2")}>
                {SHARE_COPY[key].label}
              </label>
              <p className="text-base text-ink" id={`${id}-detail`}>
                {SHARE_COPY[key].detail}
                {locked && "要先打開交易動態才會附上。"}
              </p>
              {key === "amounts" && value.amounts && value.holdings && (
                <p className="mt-1.5 flex items-start gap-1.5 text-md text-ink" role="note">
                  <InfoIcon aria-hidden className="mt-0.5 size-4 shrink-0" />
                  同時分享持股權重與金額時，成員可以推算你大約持有幾股。
                </p>
              )}
              {key === "push" && <PushTargetsNote targets={pushTargets} autoOffId={autoOff ? `${id}-auto-off` : undefined} />}
            </div>
            <Switch
              id={id}
              aria-describedby={autoOff ? `${id}-detail ${id}-auto-off` : `${id}-detail`}
              checked={value[key]}
              disabled={disabled || locked}
              onCheckedChange={(on) => set(key, on)}
              className="mt-1"
            />
          </li>
        )
      })}
    </ul>
  )
}

function PushTargetsNote({ targets, autoOffId }: { targets?: PushTarget[]; autoOffId?: string }) {
  if (targets === undefined) return <p className="mt-1 text-base text-ink">群組有設定頻道才會送；只送你打開的項目。</p>
  if (targets.length === 0) return <p className="mt-1 text-base text-ink">這個群組還沒有設定頻道。</p>
  return (
    <>
      <p className="mt-1 text-sm text-ink-2">
        會送到：<span className="text-ink">{targets.map((t) => (t.kind === "telegram" ? `Telegram「${t.label}」` : t.label)).join("、")}</span>
      </p>
      {autoOffId && (
        <p id={autoOffId} className="mt-1 text-base text-ink">
          群組換頻道時會自動關掉。
        </p>
      )}
    </>
  )
}
