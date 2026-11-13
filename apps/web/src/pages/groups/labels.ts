import type { GroupRole, LeaderboardPeriod, ShareSettings } from "@/api/types"

export const ROLE_LABEL: Record<GroupRole, string> = { owner: "擁有者", admin: "管理員", member: "成員" }

export const PERIOD_LABEL: Record<LeaderboardPeriod, string> = { day: "今日", month: "本月", year: "今年" }

/** 表情的念法（螢幕閱讀器與滑過說明）：和討論串共用 */
export { EMOJI_LABEL } from "@/lib/labels"

/** 接受邀請時的預設：只開報酬率（本人確認後才送出） */
export const DEFAULT_SHARE: ShareSettings = { returns: true, holdings: false, amounts: false, trades: false, trade_prices: false, push: false }

export const SHARE_KEYS =["returns", "holdings", "amounts", "trades", "trade_prices", "push"] as const satisfies readonly (keyof ShareSettings)[]

/** 分享開關的名稱與說明（接受邀請前與「我的分享」共用） */
export const SHARE_COPY: Record<keyof ShareSettings, { label: string; detail: string }> = {
  returns: { label: "報酬率", detail: "今日、本月、今年與總報酬率，只有百分比。" },
  holdings: { label: "持股與權重", detail: "持有哪些股票、各佔幾 %，不含股數與金額。" },
  amounts: { label: "金額與損益", detail: "市值、今日損益與總損益的金額。" },
  trades: { label: "交易動態", detail: "買進或賣出哪一檔。打開時，最近 90 天的買賣也會出現在動態裡。" },
  trade_prices: { label: "附上成交價", detail: "交易動態另外附上成交價（不含手續費與稅）。" },
  push: { label: "推播", detail: "把你分享的內容也送到群組的 Discord／Telegram 頻道。" },
}
