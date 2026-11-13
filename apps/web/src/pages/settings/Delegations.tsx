import { Link } from "@tanstack/react-router"
import { inText } from "@/lib/cjk"
import { useState } from "react"
import { toast } from "sonner"
import { useAccounts } from "@/api/queries"
import { useCreateDelegation, useDelegationCandidates, useDelegations, useDeleteDelegation, useUpdateDelegation } from "@/api/sharing-queries"
import { ApiError, type Delegation, type DelegationScope } from "@/api/types"
import { scopeText, useViewAsControls } from "@/app/view-as"
import { UserAvatar } from "@/components/avatar"
import { Section } from "@/components/section"
import { RangeChips } from "@/components/segmented"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
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
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { formatDateShort } from "@/lib/format"
import { cn } from "@/lib/utils"
import { FieldError } from "@/components/form-field"

const errText = (err: unknown) => (err instanceof ApiError ? err.message : "請檢查網路後再試一次。")

/**
 * 授權查看（一對一、唯讀）：
 * - 我授權的人：只能選同群組的成員；範圍是全部帳戶或指定帳戶；隨時修改或撤銷（立即生效）
 * - 授權給我的人：按「查看」進入唯讀的查看模式；也可以自己移除
 * 列上的動作全設定頁同一套：改內容的是文字動作（修改範圍）；拿掉這一列的（撤銷、移除，和定期定額的刪除一樣）是列尾的外框按鈕；
 * 「查看」每一列都有一顆，也是外框按鈕。
 */
export function Delegations() {
  const list = useDelegations()
  const [editing, setEditing] = useState<Delegation | "new" | null>(null)
  const [removing, setRemoving] = useState<{ d: Delegation; mine: boolean } | null>(null)
  const { enter } = useViewAsControls()
  return (
    <Section
      id="delegations"
      title="授權查看"
      titleId="set-delegations"
      className="scroll-mt-20"
      bodyClassName="flex flex-col gap-8"
      action={
        <Button variant="outline" size="sm" onClick={() => setEditing("new")}>
          授權給…
        </Button>
      }
    >
      {/* 授權是後果重大的選擇：說明留著（在標題的印刷線下面，不夾在標題和線中間） */}
      <p className="-mb-3 max-w-prose text-base text-ink">同群組的人可以看你的帳本，不能改。可以只開放部分帳戶。</p>
      {list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : !list.data ? (
        <SkeletonLines rows={3} />
      ) : (
        <>
          <div className="flex flex-col gap-2">
            <h3 className="text-base font-bold">你授權的人</h3>
            {list.data.granted.length === 0 ? (
              <EmptyState title="還沒有授權給任何人" className="py-4" />
            ) : (
              <ul className="border-t border-rule">
                {list.data.granted.map((d) => (
                  <Row key={d.id} who={d.viewer} d={d}>
                    <button type="button" onClick={() => setEditing(d)} className={cn(textAction, "mr-2")}>
                      修改範圍
                    </button>
                    <Button variant="outline" size="sm" onClick={() => setRemoving({ d, mine: true })}>
                      撤銷
                    </Button>
                  </Row>
                ))}
              </ul>
            )}
          </div>
          <div className="flex flex-col gap-2">
            <h3 className="text-base font-bold">授權給你的人</h3>
            {list.data.received.length === 0 ? (
              <EmptyState title="還沒有人授權給你" className="py-4" />
            ) : (
              <ul className="border-t border-rule">
                {list.data.received.map((d) => (
                  <Row key={d.id} who={d.owner} d={d}>
                    {/* 每一列都有一顆，所以是外框按鈕（一個畫面最多一顆墨色實心的主要按鈕） */}
                    <Button variant="outline" size="sm" onClick={() => enter(d)} aria-label={`查看${d.owner.display_name}的資產`}>
                      查看
                    </Button>
                    {/* 拿掉這一列的動作和「撤銷」「刪除」同一種寫法：列尾的外框按鈕（先確認） */}
                    <Button variant="outline" size="sm" onClick={() => setRemoving({ d, mine: false })} aria-label={`移除${d.owner.display_name}給你的授權`}>
                      移除
                    </Button>
                  </Row>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
      {editing && <GrantDialog key={editing === "new" ? "new" : editing.id} editing={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
      {removing && <RemoveDialog d={removing.d} mine={removing.mine} onClose={() => setRemoving(null)} />}
    </Section>
  )
}

function Row({ who, d, children }: { who: Delegation["owner"]; d: Delegation; children: React.ReactNode }) {
  return (
    <li className="flex min-h-16 flex-wrap items-center gap-x-3 gap-y-2 border-b border-rule py-2.5">
      <UserAvatar name={who.display_name} url={who.avatar_url} />
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">{who.display_name}</p>
        <p className="num truncate text-sm text-ink-2">
          {scopeText(d)}・{formatDateShort(d.created_at.slice(0, 10), false)} 起
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">{children}</div>
    </li>
  )
}

/** 新增授權（選人＋範圍）或修改範圍 */
function GrantDialog({ editing, onClose }: { editing: Delegation | null; onClose: () => void }) {
  const candidates = useDelegationCandidates(!editing)
  const accounts = useAccounts()
  const create = useCreateDelegation()
  const update = useUpdateDelegation()
  const [viewer, setViewer] = useState<string | null>(editing?.viewer.user_id ?? null)
  const [scope, setScope] = useState<DelegationScope>(editing?.scope ?? "all")
  const [picked, setPicked] = useState<string[]>(editing?.scope === "accounts" ? editing.accounts.map((a) => a.id) : [])
  const [error, setError] = useState<string | null>(null)
  const pending = create.isPending || update.isPending
  const submit = () => {
    if (!editing && !viewer) return setError("請選一位成員")
    if (scope === "accounts" && picked.length === 0) return setError("請至少選一個帳戶")
    setError(null)
    const body = { scope, account_ids: scope === "accounts" ? picked : [] }
    const done = {
      onSuccess: (d: Delegation) => {
        toast.success(editing ? `已更新${inText(d.viewer.display_name)}的查看範圍` : `已授權${inText(d.viewer.display_name)}查看`)
        onClose()
      },
      onError: (err: unknown) => setError(err instanceof ApiError && err.code === "already_member" ? "已經授權給這位成員了，請改用「修改範圍」。" : errText(err)),
    }
    if (editing) update.mutate({ id: editing.id, patch: body }, done)
    else create.mutate({ viewer_user_id: viewer!, ...body }, done)
  }
  const list = candidates.data ?? []
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? `${inText(editing.viewer.display_name, "start")}可以查看的範圍` : "授權查看"}</DialogTitle>
          <DialogDescription>對方只能看，不能記帳或修改；AI 不會讀你的資料給他。</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-5">
          {!editing && (
            <fieldset className="flex flex-col gap-1.5">
              <legend className="mb-1.5 text-sm font-medium">授權給誰</legend>
              {candidates.isLoading ? (
                <SkeletonLines rows={3} />
              ) : list.length === 0 ? (
                <p className="text-base text-ink">
                  只能授權給和你在同一個群組的人。先
                  <Link to="/groups" className="text-ink underline decoration-ctl underline-offset-3 hover:decoration-ink" onClick={onClose}>
                    建立或加入群組
                  </Link>
                  。
                </p>
              ) : (
                <ul className="max-h-64 overflow-y-auto border-y border-rule">
                  {list.map((c) => {
                    const granted = !!c.delegation_id
                    return (
                      <li key={c.user_id}>
                        <label className={cn("flex min-h-12 items-center gap-3 border-b border-rule px-1 last:border-b-0", granted ? "text-ink-2" : "cursor-pointer hover:bg-hov")}>
                          <input
                            type="radio"
                            name="delegate-viewer"
                            value={c.user_id}
                            disabled={granted}
                            checked={viewer === c.user_id}
                            onChange={() => setViewer(c.user_id)}
                            className="size-4 accent-ink"
                          />
                          <UserAvatar name={c.display_name} url={c.avatar_url} size="sm" />
                          <span className="flex-1">{c.display_name}</span>
                          {granted && <span className="text-sm">已授權</span>}
                        </label>
                      </li>
                    )
                  })}
                </ul>
              )}
            </fieldset>
          )}
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium">範圍</span>
            <RangeChips
              label="範圍"
              value={scope}
              onChange={setScope}
              options={[
                { value: "all", label: "全部帳戶" },
                { value: "accounts", label: "指定帳戶" },
              ]}
            />
            <p className="text-base text-ink">{scope === "all" ? "包含之後新增的帳戶。" : "只看得到勾選的帳戶，持股、績效與交易都只算這些帳戶。"}</p>
            {scope === "accounts" && (
              <ul className="border-y border-rule">
                {(accounts.data ?? []).map((a) => (
                  <li key={a.id}>
                    <label className="flex min-h-11 cursor-pointer items-center gap-3 border-b border-rule px-1 last:border-b-0 hover:bg-hov">
                      <input
                        type="checkbox"
                        checked={picked.includes(a.id)}
                        onChange={(e) => setPicked(e.target.checked ? [...picked, a.id] : picked.filter((x) => x !== a.id))}
                        className="size-4 accent-ink"
                      />
                      {a.name}
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </div>
          {error && (
            <FieldError>{error}</FieldError>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button variant="sign" onClick={submit} disabled={pending || (!editing && list.length === 0)}>
            {pending ? "儲存中…" : editing ? "儲存" : "授權"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function RemoveDialog({ d, mine, onClose }: { d: Delegation; mine: boolean; onClose: () => void }) {
  const del = useDeleteDelegation()
  const name = mine ? d.viewer.display_name : d.owner.display_name
  return (
    <AlertDialog open onOpenChange={(o) => !o && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{mine ? `撤銷${inText(name)}的查看授權？` : `移除${inText(name)}給你的授權？`}</AlertDialogTitle>
          <AlertDialogDescription>
            {mine ? `${name}會立刻看不到你的帳本；之後要再授權一次才能查看。` : `你會看不到${name}的帳本；要再查看，需要他重新授權。`}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction
            disabled={del.isPending}
            onClick={() =>
              del.mutate(d.id, {
                onSuccess: () => {
                  toast.success(mine ? `已撤銷${inText(name)}的授權` : `已移除${inText(name)}的授權`)
                  onClose()
                },
                onError: (err) => toast.error("沒有完成", { description: errText(err) }),
              })
            }
          >
            {mine ? "撤銷" : "移除"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
