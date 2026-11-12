import { Link, useNavigate } from "@tanstack/react-router"
import { CopyIcon, EllipsisIcon, LinkIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import {
  useCreateInvite,
  useDeleteGroup,
  useInvites,
  useRemoveMember,
  useRevokeInvite,
  useSetMemberRole,
  useTransferGroup,
  useUpdateGroup,
} from "@/api/sharing-queries"
import { ApiError, type Group, type GroupInvite, type GroupMember } from "@/api/types"
import { UserAvatar } from "@/components/avatar"
import { Section } from "@/components/section"
import { RangeChips } from "@/components/segmented"
import { SkeletonLines } from "@/components/states"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button, buttonVariants } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { formatDateShort, formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import { ROLE_LABEL } from "../labels"

type Confirm =
  | { kind: "remove"; m: GroupMember }
  | { kind: "transfer"; m: GroupMember }
  | { kind: "leave" }
  | { kind: "delete" }

const errText = (err: unknown) => (err instanceof ApiError ? err.message : "請檢查網路後再試一次。")

/** 成員：角色、轉移擁有者、移除與離開；管理員另有邀請連結與群組設定 */
export function MembersTab({ group }: { group: Group }) {
  const [confirm, setConfirm] = useState<Confirm | null>(null)
  const isOwner = group.my_role === "owner"
  const isAdmin = group.my_role !== "member"
  return (
    <div className="flex flex-col gap-12">
      <Section title="成員" titleId="gm-members" aside={`${group.members.length} 位`}>
        <ul className="-mt-3">
          {group.members.map((m) => (
            <MemberRow key={m.user_id} m={m} group={group} onConfirm={setConfirm} />
          ))}
        </ul>
        {!isOwner && (
          <Button variant="outline" className="mt-4" onClick={() => setConfirm({ kind: "leave" })}>
            離開群組
          </Button>
        )}
      </Section>
      {isAdmin && <Invites group={group} />}
      {isAdmin && <GroupSettings group={group} onDelete={() => setConfirm({ kind: "delete" })} />}
      {confirm && <ConfirmDialog group={group} confirm={confirm} onClose={() => setConfirm(null)} />}
    </div>
  )
}

function MemberRow({ m, group, onConfirm }: { m: GroupMember; group: Group; onConfirm: (c: Confirm) => void }) {
  const setRole = useSetMemberRole(group.id)
  const isOwner = group.my_role === "owner"
  const canRemove = !m.is_me && m.role !== "owner" && (isOwner || (group.my_role === "admin" && m.role === "member"))
  const canRole = isOwner && !m.is_me
  return (
    <li className="flex min-h-[64px] items-center gap-3 border-b border-rule py-2">
      <UserAvatar name={m.display_name} url={m.avatar_url} />
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-2">
          <Link to="/groups/$groupId/members/$userId" params={{ groupId: group.id, userId: m.user_id }} className="truncate text-lg font-medium hover:underline">
            {m.display_name}
          </Link>
          {m.is_me && <span className="text-sm text-ink-2">（你）</span>}
          {m.role !== "member" && <span className="demo-tag text-ink-2">{ROLE_LABEL[m.role]}</span>}
        </p>
        <p className="num text-sm text-ink-2">{formatDateShort(m.joined_at.slice(0, 10), false)} 加入</p>
      </div>
      {(canRemove || canRole) && (
        <DropdownMenu>
          <DropdownMenuTrigger
            render={<button type="button" aria-label={`${m.display_name}的選項`} className="press grid size-10 place-items-center rounded-sm text-ink-2 hover:bg-hov hover:text-ink pointer-coarse:size-11" />}
          >
            <EllipsisIcon aria-hidden className="size-5" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-52">
            {canRole && (
              <>
                <DropdownMenuItem
                  onClick={() =>
                    setRole.mutate(
                      { userId: m.user_id, role: m.role === "admin" ? "member" : "admin" },
                      {
                        onSuccess: () => toast.success(m.role === "admin" ? `${m.display_name}改為成員` : `${m.display_name}成為管理員`),
                        onError: (err) => toast.error("沒有改成功", { description: errText(err) }),
                      },
                    )
                  }
                >
                  {m.role === "admin" ? "改為成員" : "設為管理員"}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => onConfirm({ kind: "transfer", m })}>把群組轉給{m.display_name}</DropdownMenuItem>
              </>
            )}
            {canRole && canRemove && <DropdownMenuSeparator />}
            {canRemove && <DropdownMenuItem onClick={() => onConfirm({ kind: "remove", m })}>移出群組</DropdownMenuItem>}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </li>
  )
}

function ConfirmDialog({ group, confirm, onClose }: { group: Group; confirm: Confirm; onClose: () => void }) {
  const navigate = useNavigate()
  const remove = useRemoveMember(group.id)
  const transfer = useTransferGroup(group.id)
  const del = useDeleteGroup(group.id)
  const me = group.members.find((m) => m.is_me)
  const pending = remove.isPending || transfer.isPending || del.isPending
  const copy = {
    remove: confirm.kind === "remove" && {
      title: `把${confirm.m.display_name}移出「${group.name}」？`,
      body: "他分享的內容會立刻從排行、動態與週報消失；之後要重新邀請才能加入。可以多人使用的邀請連結會一起撤回。",
      action: "移出群組",
    },
    transfer: confirm.kind === "transfer" && {
      title: `把「${group.name}」轉給${confirm.m.display_name}？`,
      body: `${confirm.m.display_name}會成為擁有者，你改為管理員。頻道設定與排名開關之後由他決定。`,
      action: "轉移",
    },
    leave: { title: `離開「${group.name}」？`, body: "你在這個群組的分享設定會刪除，你分享的內容立刻從排行、動態與週報消失。之後要重新被邀請才能加入。", action: "離開群組" },
    delete: { title: `刪除「${group.name}」？`, body: "群組、留言、週報與頻道設定都會刪除，所有成員都看不到。這個動作無法復原。", action: "刪除群組" },
  }[confirm.kind] as { title: string; body: string; action: string }
  const run = () => {
    const done = { onError: (err: unknown) => toast.error("沒有完成", { description: errText(err) }) }
    if (confirm.kind === "remove") {
      remove.mutate({ userId: confirm.m.user_id, self: false }, { ...done, onSuccess: () => (toast.success(`已把${confirm.m.display_name}移出群組`), onClose()) })
    } else if (confirm.kind === "transfer") {
      transfer.mutate(confirm.m.user_id, { ...done, onSuccess: () => (toast.success(`群組已轉給${confirm.m.display_name}`), onClose()) })
    } else if (confirm.kind === "leave" && me) {
      remove.mutate(
        { userId: me.user_id, self: true },
        { ...done, onSuccess: () => (toast.success(`已離開「${group.name}」`), onClose(), void navigate({ to: "/groups" })) },
      )
    } else if (confirm.kind === "delete") {
      del.mutate(undefined, { ...done, onSuccess: () => (toast.success(`已刪除「${group.name}」`), onClose(), void navigate({ to: "/groups" })) })
    }
  }
  return (
    <AlertDialog open onOpenChange={(o) => !o && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{copy.title}</AlertDialogTitle>
          <AlertDialogDescription>{copy.body}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction variant="destructive" disabled={pending} onClick={run}>
            {copy.action}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

/** 邀請連結：有效的邀請（期限、單次或多次、用了幾次、撤回）；新的連結只在產生時顯示一次 */
function Invites({ group }: { group: Group }) {
  const invites = useInvites(group.id, true)
  const create = useCreateInvite(group.id)
  const revoke = useRevokeInvite(group.id)
  const [expires, setExpires] = useState<"24h" | "7d">("7d")
  const [multi, setMulti] = useState(false)
  const [created, setCreated] = useState<GroupInvite | null>(null)
  return (
    <Section title="邀請連結" titleId="gm-invites">
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">有效期限</span>
            <RangeChips label="有效期限" value={expires} onChange={setExpires} options={[{ value: "24h", label: "24 小時" }, { value: "7d", label: "7 天" }]} />
          </div>
          <label className="flex h-10 items-center gap-2.5 text-base">
            <Switch checked={multi} onCheckedChange={setMulti} />
            可以多人使用
          </label>
          <Button
            variant="outline"
            disabled={create.isPending}
            onClick={() =>
              create.mutate(
                { expires, multi_use: multi },
                { onSuccess: (inv) => setCreated(inv), onError: (err) => toast.error("沒有產生邀請連結", { description: errText(err) }) },
              )
            }
          >
            <LinkIcon />
            產生邀請連結
          </Button>
        </div>
        {created?.url && <CreatedInvite invite={created} />}
        {!invites.data ? (
          <SkeletonLines rows={2} />
        ) : invites.data.length === 0 ? (
          <p className="text-md text-ink-2">目前沒有有效的邀請連結。</p>
        ) : (
          <ul aria-label="有效的邀請" className="border-t border-rule">
            {invites.data.map((inv) => (
              <li key={inv.id} className="flex min-h-14 items-center gap-3 border-b border-rule py-2">
                <div className="min-w-0 flex-1">
                  <p>{inv.multi_use ? "可以多人使用" : "單次使用"}</p>
                  <p className="num text-sm text-ink-2">
                    {formatDateTime(inv.expires_at)} 到期・已使用 {inv.uses} 次
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={revoke.isPending}
                  onClick={() =>
                    revoke.mutate(inv.id, {
                      onSuccess: () => toast.success("已撤回邀請連結"),
                      onError: (err) => toast.error("沒有撤回", { description: errText(err) }),
                    })
                  }
                >
                  撤回
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Section>
  )
}

function CreatedInvite({ invite }: { invite: GroupInvite }) {
  return (
    <div className="flex flex-col gap-2 border border-ink p-4" role="status">
      <p className="font-medium">新的邀請連結（只會顯示這一次）</p>
      <div className="flex gap-2">
        <Input readOnly value={invite.url} aria-label="邀請連結" onFocus={(e) => e.currentTarget.select()} className="num" />
        <Button
          variant="outline"
          onClick={() =>
            void navigator.clipboard?.writeText(invite.url!).then(
              () => toast.success("已複製邀請連結"),
              () => toast.error("沒有複製成功，請手動選取連結"),
            )
          }
        >
          <CopyIcon />
          複製
        </Button>
      </div>
      <p className="num text-sm text-ink-2">
        {invite.multi_use ? "可以多人使用" : "單次使用"}・{formatDateTime(invite.expires_at)} 到期。對方點開後會先選要分享什麼，再加入。
      </p>
    </div>
  )
}

/** 群組設定：名稱（管理員）、排名（只有擁有者）、刪除群組（只有擁有者） */
function GroupSettings({ group, onDelete }: { group: Group; onDelete: () => void }) {
  const update = useUpdateGroup(group.id)
  const [name, setName] = useState(group.name)
  const isOwner = group.my_role === "owner"
  const trimmed = name.trim()
  const bad = trimmed.length < 1 || trimmed.length > 40
  const dirty = trimmed !== group.name
  return (
    <Section title="群組設定" titleId="gm-settings">
      <div className="flex flex-col divide-y divide-rule border-b border-rule">
        <form
          className="grid gap-x-3 gap-y-1.5 py-4 sm:grid-cols-[minmax(0,1fr)_auto]"
          onSubmit={(e) => {
            e.preventDefault()
            if (bad || !dirty) return
            update.mutate({ name: trimmed }, { onSuccess: () => toast.success("已更新群組名稱"), onError: (err) => toast.error("名稱沒有更新", { description: errText(err) }) })
          }}
        >
          <label htmlFor="group-rename" className="text-sm font-medium">
            群組名稱
          </label>
          <Input id="group-rename" value={name} maxLength={40} onChange={(e) => setName(e.target.value)} aria-invalid={bad} className="pointer-coarse:h-11 sm:col-start-1 sm:row-start-2" />
          {/* 簽名格只在改了名稱時出現；沒改時桌面留同寬的看不見位置（輸入框不跳動），手機不放 */}
          {dirty ? (
            <Button type="submit" variant="sign" className="mt-2.5 justify-self-start sm:col-start-2 sm:row-start-2 sm:mt-0" disabled={bad || update.isPending}>
              儲存
            </Button>
          ) : (
            <span aria-hidden className={cn(buttonVariants({ variant: "sign" }), "invisible hidden sm:col-start-2 sm:row-start-2 sm:inline-flex")}>
              儲存
            </span>
          )}
        </form>
        <div className="flex items-start justify-between gap-6 py-4">
          <div>
            <label htmlFor="group-ranking" className="font-medium">
              排名次
            </label>
            <p className="text-md text-ink-2">{isOwner ? "關掉時排行只列出報酬率，依加入順序排列，沒有名次。" : "只有擁有者可以改。"}</p>
          </div>
          <Switch
            id="group-ranking"
            checked={group.ranking_enabled}
            disabled={!isOwner || update.isPending}
            onCheckedChange={(on) => update.mutate({ ranking_enabled: on }, { onError: (err) => toast.error("沒有改成功", { description: errText(err) }) })}
          />
        </div>
        {isOwner && (
          <div className="flex flex-col items-start gap-2 py-4">
            <p className="text-md text-ink-2">擁有者要先把群組轉給別人才能離開（成員右邊的選項）。</p>
            <Button variant="outline" onClick={onDelete}>
              刪除群組
            </Button>
          </div>
        )}
      </div>
    </Section>
  )
}
