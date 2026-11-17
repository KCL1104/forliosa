import { useState } from "react"
import { toast } from "sonner"
import { useChannels, useDeleteChannel, useLinkTelegram, usePatchChannel, usePutDiscord } from "@/api/sharing-queries"
import { ApiError, type ChannelNotify, type Group, type TelegramLinkCode } from "@/api/types"
import { Section } from "@/components/section"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import { FieldError } from "@/components/form-field"

const errText = (err: unknown) => (err instanceof ApiError ? err.message : "請檢查網路後再試一次。")

/**
 * 頻道：群組的 Discord（webhook）與 Telegram（bot）。每位成員都看得到推播到哪裡；只有擁有者可以設定。
 * 只會送出開了「推播」的成員所分享的內容。webhook 網址不顯示，只有最後 4 碼。
 * 「日報」開關只在加值的群組出現（預設關，擁有者決定；群組加值包第一階段）；到期後已經打開的照樣列出，方便關掉。
 * 市場報告（2026-11-17）對全站公開時，每個頻道多三個開關（所有群組都能開）：盤前重點、盤後重點（預設關）、市場週報（預設開）。
 */
export function ChannelsTab({ group }: { group: Group }) {
  const [linking, setLinking] = useState<TelegramLinkCode | null>(null)
  const channels = useChannels(group.id, { poll: !!linking })
  const owner = group.my_role === "owner"
  const boosted = group.plan?.tier === "boosted"
  if (channels.isError) return <ErrorState error={channels.error} onRetry={() => void channels.refetch()} />
  if (!channels.data) return <SkeletonLines rows={6} />
  const c = channels.data
  // 這次連結完成＝頻道變成使用中（不能用 configured：停用的頻道也是 configured，重新連結時碼會被藏起來）
  const linked = !!linking && c.telegram.status === "active"
  return (
    <div className="flex max-w-2xl flex-col gap-12">
      <p className="text-base text-ink">
        成員自己打開「推播」，他分享的內容才會送到頻道。{owner ? "" : "頻道由擁有者設定。"}
      </p>

      <Section title="Discord" titleId="gc-discord" aside={<Status configured={c.discord.configured} status={c.discord.status} />}>
        {c.discord.status === "disabled" && <Disabled reason={c.discord.disabled_reason} owner={owner} />}
        {c.discord.configured ? (
          <>
            {owner && c.discord.webhook_hint && <p className="num text-md text-ink-2">Webhook 網址結尾 {c.discord.webhook_hint}</p>}
            <NotifyToggles groupId={group.id} kind="discord" value={c.discord} editable={owner} daily={boosted || !!c.discord.notify_daily} reports={!!c.market_reports_available} trial={!!c.market_reports_trial} />
            {owner && (
              // 「換一個 webhook」和「解除 Discord」同一列、中間留 24px（原本兩個行內元素直接貼在一起；2026-11-15 產品負責人回報）。
              // 展開成表單時表單佔滿一列，「解除」換到下一列
              <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-3">
                <DiscordForm groupId={group.id} replacing daily={boosted} />
                <Unlink groupId={group.id} kind="discord" className="" />
              </div>
            )}
          </>
        ) : owner ? (
          <DiscordForm groupId={group.id} daily={boosted} />
        ) : (
          <EmptyState flush title="還沒有設定" />
        )}
      </Section>

      <Section title="Telegram" titleId="gc-telegram" aside={<Status configured={c.telegram.configured} status={c.telegram.status} />}>
        {!c.telegram_available ? (
          <EmptyState flush title="暫時不能連結" description="伺服器還沒有設定 Telegram bot。" />
        ) : (
          <>
            {c.telegram.status === "disabled" && <Disabled reason={c.telegram.disabled_reason} owner={owner} />}
            {c.telegram.configured && c.telegram.chat_title && (
              <p className="text-base">
                已連結：<b className="font-medium">{c.telegram.chat_title}</b>
                {linked && <span className="ml-2 text-md text-ink-2">連結完成</span>}
              </p>
            )}
            {c.telegram.configured && (
              <NotifyToggles groupId={group.id} kind="telegram" value={c.telegram} editable={owner} daily={boosted || !!c.telegram.notify_daily} reports={!!c.market_reports_available} trial={!!c.market_reports_trial} />
            )}
            {owner && (!c.telegram.configured || c.telegram.status === "disabled") && (
              <TelegramLink groupId={group.id} code={linked ? null : linking} onCode={setLinking} />
            )}
            {owner && c.telegram.configured && <Unlink groupId={group.id} kind="telegram" />}
            {!owner && !c.telegram.configured && <EmptyState flush title="還沒有連結" />}
          </>
        )}
      </Section>
    </div>
  )
}

function Status({ configured, status }: { configured: boolean; status: "active" | "disabled" | null }) {
  if (!configured) return <span>未設定</span>
  return <span className={status === "disabled" ? "font-medium text-ink" : undefined}>{status === "disabled" ? "已停用" : "使用中"}</span>
}

function Disabled({ reason, owner }: { reason: string | null; owner: boolean }) {
  return (
    <p role="status" className="mb-3 border-y border-rule py-2.5 text-base">
      這個頻道已停用{reason ? `：${reason}` : ""}。{owner ? "重新設定後恢復推播。" : "擁有者重新設定後恢復推播。"}
    </p>
  )
}

function NotifyToggles({
  groupId,
  kind,
  value,
  editable,
  daily,
  reports,
  trial = false,
}: {
  groupId: string
  kind: "discord" | "telegram"
  value: ChannelNotify & { notify_trades: boolean; notify_digest: boolean }
  editable: boolean
  /** 有沒有「日報」這一列（加值群組，或已經打開的） */
  daily: boolean
  /** 市場報告對全站公開時才有三個報告的開關（所有群組都能開；盤前、盤後預設關，週報預設開） */
  reports: boolean
  /**
   * 盲測開給所有人（試跑中）：也有三個開關，每份推一則投票連結（2026-11-17）。
   * 這時不併群組的日報、週報（`reports` 是 false），日報、週報的說明照平常寫。
   */
  trial?: boolean
}) {
  const patch = usePatchChannel(groupId, kind)
  const row = (key: keyof ChannelNotify, label: string, detail: string | null, fallback = false) => {
    const id = `${kind}-${key}`
    return (
      <div className="flex min-h-12 items-start justify-between gap-6 border-b border-rule py-3">
        <div>
          <label htmlFor={id} className="font-medium">
            {label}
          </label>
          {detail && <p className="text-base text-ink">{detail}</p>}
        </div>
        <Switch
          id={id}
          checked={value[key] ?? fallback}
          disabled={!editable || patch.isPending}
          onCheckedChange={(on) => patch.mutate({ [key]: on }, { onError: (err) => toast.error("沒有改成功", { description: errText(err) }) })}
        />
      </div>
    )
  }
  // 報告對全站公開時，群組的週報、日報會併進市場報告的推播（後端 push.digest_hold／daily_hold）：說明照實際的送法寫
  const weeklyMerged = reports && (value.notify_weekly ?? true)
  const dailyMerged = reports && (value.notify_premarket ?? false)
  return (
    <div className="mt-2 border-t border-rule">
      {row("notify_trades", "交易動態", "成員的買賣，交易建立 15 分鐘後送出。")}
      {row(
        "notify_digest",
        "週報",
        weeklyMerged ? "群組 AI 週報併在週日 18:00 的市場週報裡送；那天沒有市場週報時，21:30 單獨送。" : "每週六晚上的群組 AI 週報。",
      )}
      {daily &&
        row(
          "notify_daily",
          "日報",
          dailyMerged
            ? "每個交易日收盤後的群組 AI 日報。晚上 11 點到早上 7:30 之間寫好的，併在交易日 7:30 的盤前重點裡送。"
            : "每個交易日收盤後的群組 AI 日報。晚上 11 點到早上 7:30 之間寫好的，早上 7:30 再送。",
        )}
      {(reports || trial) && (
        <div data-report-toggles="">
          <p className="pt-4 pb-1 text-sm text-ink-2">{trial ? "盲測期間每份報告推一則投票連結：三種寫法，看完選一個。" : "推到頻道的是文字與連結，報告本文人人相同。"}</p>
          {row("notify_premarket", "盤前重點（交易日 7:30）", null)}
          {row("notify_close", "盤後重點（交易日 16:00）", null)}
          {row("notify_weekly", "市場週報（週日 18:00）", null, true)}
        </div>
      )}
    </div>
  )
}

/** 貼上 Discord 頻道的 webhook 網址；儲存前伺服器先送一則測試訊息。日報（加值群組）預設不送 */
function DiscordForm({ groupId, replacing, daily = false }: { groupId: string; replacing?: boolean; daily?: boolean }) {
  const put = usePutDiscord(groupId)
  const [open, setOpen] = useState(!replacing)
  const [url, setUrl] = useState("")
  const [trades, setTrades] = useState(true)
  const [digest, setDigest] = useState(true)
  const [dailyOn, setDailyOn] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (!open) {
    return (
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        換一個 webhook
      </Button>
    )
  }
  const looksRight = /^https:\/\/(discord|discordapp)\.com\/api\/webhooks\/\d+\/[\w-]+$/.test(url.trim())
  return (
    <form
      className="mt-2 flex basis-full flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (!looksRight) {
          setError("請貼上 Discord 頻道設定裡「整合 → Webhook」複製的網址（https://discord.com/api/webhooks/…）。")
          return
        }
        setError(null)
        put.mutate(
          { webhook_url: url.trim(), notify_trades: trades, notify_digest: digest, ...(daily ? { notify_daily: dailyOn } : {}) },
          {
            onSuccess: () => {
              setUrl("")
              if (replacing) setOpen(false)
              toast.success("已設定 Discord 頻道，測試訊息送出了")
            },
            onError: (err) =>
              setError(err instanceof ApiError && err.code === "webhook_failed" ? "測試訊息送不出去：請確認這個 webhook 還存在，或重新複製一次網址。" : errText(err)),
          },
        )
      }}
    >
      <div className="flex flex-col gap-1.5">
        <label htmlFor="discord-webhook" className="text-sm font-medium">
          Webhook 網址
        </label>
        <Input
          id="discord-webhook"
          className="pointer-coarse:h-11"
          type="url"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          value={url}
          placeholder="https://discord.com/api/webhooks/…"
          aria-invalid={!!error}
          aria-describedby="discord-webhook-help"
          onChange={(e) => setUrl(e.target.value)}
        />
        <p id="discord-webhook-help" className="text-sm text-ink-2">
          Discord 頻道設定 → 整合 → Webhook → 複製網址。網址只用來送訊息，存起來後不會再顯示。
        </p>
        {error && (
          <FieldError>{error}</FieldError>
        )}
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        <label className="flex items-center gap-2.5">
          <Switch checked={trades} onCheckedChange={setTrades} />
          送交易動態
        </label>
        <label className="flex items-center gap-2.5">
          <Switch checked={digest} onCheckedChange={setDigest} />
          送週報
        </label>
        {daily && (
          <label className="flex items-center gap-2.5">
            <Switch checked={dailyOn} onCheckedChange={setDailyOn} />
            送日報
          </label>
        )}
      </div>
      <div className="flex gap-2">
        <Button type="submit" variant="sign" disabled={put.isPending || !url.trim()}>
          {put.isPending ? "傳送測試訊息…" : "儲存並送測試訊息"}
        </Button>
        {replacing && (
          <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
            取消
          </Button>
        )}
      </div>
    </form>
  )
}

/** Telegram：產生連結碼 → 把 bot 加進群組、在群組裡傳 /link 碼；連結後這裡顯示群組名稱 */
function TelegramLink({ groupId, code, onCode }: { groupId: string; code: TelegramLinkCode | null; onCode: (c: TelegramLinkCode | null) => void }) {
  const link = useLinkTelegram(groupId)
  if (code) {
    return (
      <div role="status" className="mt-2 flex flex-col gap-2 border border-ink p-4">
        <p className="font-medium">在 Telegram 完成連結</p>
        <ol className="list-decimal pl-5 text-base">
          <li>
            把 <b className="font-medium">@{code.bot_username}</b> 加進你們的 Telegram 群組。
          </li>
          <li>
            在群組裡傳 <code className="num rounded-xs bg-hov px-1.5 py-0.5 text-lg font-medium break-all">/link@{code.bot_username} {code.code}</code>
          </li>
        </ol>
        <p className="num text-sm text-ink-2">連結碼 {formatDateTime(code.expires_at)} 前有效，只能用一次。</p>
        <Button variant="ghost" size="sm" className="self-start" onClick={() => onCode(null)}>
          取消
        </Button>
      </div>
    )
  }
  return (
    <Button
      variant="outline"
      className="mt-4"
      disabled={link.isPending}
      onClick={() => link.mutate(undefined, { onSuccess: onCode, onError: (err) => toast.error("沒有產生連結碼", { description: errText(err) }) })}
    >
      產生連結碼
    </Button>
  )
}

function Unlink({ groupId, kind, className = "mt-4" }: { groupId: string; kind: "discord" | "telegram"; className?: string }) {
  const del = useDeleteChannel(groupId, kind)
  const [sure, setSure] = useState(false)
  return sure ? (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      <span className="text-md">解除後不會再送訊息到這個頻道。</span>
      <Button
        variant="outline"
        size="sm"
        disabled={del.isPending}
        onClick={() => del.mutate(undefined, { onSuccess: () => toast.success("已解除"), onError: (err) => toast.error("沒有解除", { description: errText(err) }) })}
      >
        解除
      </Button>
      <Button variant="ghost" size="sm" onClick={() => setSure(false)}>
        取消
      </Button>
    </div>
  ) : (
    // 文字動作（常駐底線），不是只有灰字
    <button type="button" className={cn(textAction, className)} onClick={() => setSure(true)}>
      解除{kind === "discord" ? " Discord" : " Telegram"}
    </button>
  )
}
