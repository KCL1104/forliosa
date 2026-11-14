import { useState } from "react"
import { toast } from "sonner"
import { useAccounts, useCreateAccount, useMe, useUpdateAccount, useUpdatePreferences } from "@/api/queries"
import type { Account } from "@/api/types"
import { BenchmarkSelect } from "@/components/benchmark-select"
import { usePrefSetter } from "@/hooks/use-pref-setter"
import { RangeChips } from "@/components/charts/chart-kit"
import { PageHeader, Section } from "@/components/section"
import { RecurringPlans } from "./RecurringPlans"
import { AccountData } from "./AccountData"
import { DeleteBrokerAccountDialog } from "./DeleteBrokerAccount"
import { useDeleteAllThreads } from "@/ai/threads"
import { Delegations } from "./Delegations"
import { Profile } from "./Profile"
import { useReadOnly } from "@/api/view-as"
import { PageFrame } from "@/app/PageFrame"
import { ViewAsBlocked } from "@/app/ViewAsBanner"
import { SourcesFooter } from "@/components/sources"
import { EmptyState, SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
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
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { FormField as Field } from "@/components/form-field"
import { Pct } from "@/components/finance"
import { usePageTitle } from "@/app/page-title"


export function SettingsPage() {
  usePageTitle("設定")
  // 查看別人的資產時，帳戶與定期定額會是對方的：結束查看後才能用（外觀與漲跌顏色在頭像選單）
  const readOnly = useReadOnly()
  if (readOnly) return <ViewAsBlocked title="設定" />
  return <Settings />
}

function Settings() {
  const p = usePrefs()
  const setPref = usePrefSetter()
  return (
    // 左緣和帳本相同；設定是一欄表單，寬度限制在 816px（標籤和開關不會離太遠）
    <PageFrame>
      <div className="flex max-w-measure flex-col gap-10">
      <PageHeader title="設定" className="mb-0" />

      <Profile />

      <Group title="顯示">
        <Row
          label="漲跌顏色"
          description={
            // 預覽和全站的漲跌幅寫法相同：▲▼ 跟著數字，不再加正負號
            <span className="inline-flex flex-wrap items-center gap-3">
              預覽
              <Pct value={0.0123} />
              <Pct value={-0.0085} />
            </span>
          }
        >
          <RangeChips
            label="漲跌顏色"
            value={p.colorConvention}
            onChange={(v) => setPref({ colorConvention: v })}
            options={[
              { value: "tw", label: "紅漲綠跌" },
              { value: "us", label: "綠漲紅跌" },
            ]}
          />
        </Row>
        <Row label="主題">
          <RangeChips
            label="主題"
            value={p.theme}
            onChange={(v) => setPref({ theme: v })}
            options={[
              { value: "light", label: "淺色" },
              { value: "dark", label: "深色" },
              { value: "system", label: "跟隨系統" },
            ]}
          />
        </Row>
        <Row label="股數顯示">
          <RangeChips
            label="股數顯示"
            value={p.quantityUnit}
            onChange={(v) => setPref({ quantityUnit: v })}
            options={[
              { value: "lot", label: "張＋股" },
              { value: "share", label: "股" },
            ]}
          />
        </Row>
        <Row label="大數字縮寫" htmlFor="compact">
          <Switch id="compact" checked={p.compactNumbers} onCheckedChange={(v) => setPref({ compactNumbers: v })} />
        </Row>
      </Group>

      <Group title="隱私">
        <Row label="開啟時預設隱私模式" description="遮蔽金額與股數，百分比照常顯示。" htmlFor="privacy-default">
          <Switch id="privacy-default" checked={p.privacyDefault} onCheckedChange={(v) => setPref({ privacyDefault: v })} />
        </Row>
      </Group>

      <Group title="計算">
        <Row label="成本計算方式" description="改了會重新計算已實現損益。">
          <RangeChips
            label="成本計算方式"
            value={p.costMethod}
            onChange={(v) => setPref({ costMethod: v })}
            options={[
              { value: "average", label: "移動平均" },
              { value: "fifo", label: "先進先出" },
            ]}
          />
        </Row>
        <Row label="績效比較基準">
          <BenchmarkSelect value={p.benchmark} onChange={(v) => setPref({ benchmark: v })} className="min-w-44 pointer-coarse:h-11!" />
        </Row>
      </Group>

      <AiSettings />

      <Accounts />

      <RecurringPlans />

      <Delegations />

      <AccountData />
      </div>
      {/* 資料來源：一頁一個頁尾（設定頁沒有自己的資料，就是連到完整顯名聲明） */}
      <SourcesFooter className="max-w-measure" />
    </PageFrame>
  )
}

/**
 * AI：每日收盤簡報的開關（預設關）。偏好存在伺服器上（worker 依它決定要不要寫），所以直接讀寫 `/me` 的偏好，
 * 不經過本機的顯示設定。下面是「刪除全部 AI 對話」（產品負責人 2026-11-14 決定 3-2）。
 */
function AiSettings() {
  const me = useMe()
  const update = useUpdatePreferences()
  const on = me.data?.preferences.daily_briefing ?? false
  const [confirming, setConfirming] = useState(false)
  return (
    <Group title="AI">
      <Row label="每日收盤簡報" description="收盤後依你的持股與觀察清單寫一則，在「問 AI」最上面。" htmlFor="daily-briefing">
        <Switch
          id="daily-briefing"
          checked={on}
          disabled={!me.data || update.isPending}
          onCheckedChange={(v) =>
            update.mutate(
              { daily_briefing: v },
              { onError: (err) => toast.error("設定沒有存到伺服器", { description: err instanceof Error ? err.message : "請檢查網路後再試一次。" }) },
            )
          }
        />
      </Row>
      <Row label="刪除全部 AI 對話">
        <Button
          variant="outline"
          aria-label="刪除全部 AI 對話"
          onClick={() => {
            toast.dismiss()
            setConfirming(true)
          }}
        >
          刪除…
        </Button>
      </Row>
      {confirming && <DeleteConversationsDialog onClose={() => setConfirming(false)} />}
    </Group>
  )
}

/**
 * 刪除全部 AI 對話：伺服器上的全部刪掉，這台瀏覽器上的對話與草稿也清掉（和登出一樣）。
 * 不能復原，所以先問一次、沒有「復原」；已簽名的草稿記下的交易留在帳本。
 */
function DeleteConversationsDialog({ onClose }: { onClose: () => void }) {
  const remove = useDeleteAllThreads()
  return (
    <AlertDialog open onOpenChange={(o) => !o && !remove.isPending && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>刪除全部 AI 對話？</AlertDialogTitle>
          <AlertDialogDescription>不能復原。已簽名的草稿記下的交易會留在帳本。</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={remove.isPending}>取消</AlertDialogCancel>
          <AlertDialogAction
            disabled={remove.isPending}
            onClick={() =>
              remove.mutate(undefined, {
                onSuccess: () => {
                  toast.success("已刪除全部 AI 對話")
                  onClose()
                },
                onError: (err) => toast.error("沒有刪除，對話都還在。", { description: err instanceof Error ? err.message : undefined }),
              })
            }
          >
            {remove.isPending ? "刪除中…" : "全部刪除"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

/** 設定的一組：區塊標題（和其他頁面同一級：20px、底下一條印刷線）＋一列一列的格線 */
function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Section title={title} titleId={`set-${title}`} bodyClassName="pt-0">
      <div className="flex flex-col divide-y divide-rule border-b border-rule">{children}</div>
    </Section>
  )
}

function Row({ label, description, htmlFor, children }: { label: string; description?: React.ReactNode; htmlFor?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
      <div className="min-w-0">
        {htmlFor ? <label htmlFor={htmlFor} className="font-medium">{label}</label> : <p className="font-medium">{label}</p>}
        {description && <div className="mt-0.5 text-base text-ink">{description}</div>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}

function Accounts() {
  const accounts = useAccounts()
  const [editing, setEditing] = useState<Account | null>(null)
  const [deleting, setDeleting] = useState<Account | null>(null)
  return (
    <Section
      id="accounts"
      title="券商帳戶"
      titleId="set-accounts"
      className="scroll-mt-20"
      bodyClassName="pt-0"
      action={
        <Button variant="outline" size="sm" onClick={() => setEditing(NEW_ACCOUNT)}>
          新增帳戶
        </Button>
      }
    >
      {!accounts.data ? (
        <SkeletonLines rows={3} className="pt-3" />
      ) : accounts.data.length === 0 ? (
        <EmptyState flush title="還沒有帳戶" description="先新增一個，例如「永豐・一般」。" />
      ) : (
        // 標題的印刷線就是清單上面那條線
        <ul className="flex flex-col divide-y divide-rule border-b border-rule">
          {accounts.data.map((a) => (
            <li key={a.id} className="flex items-start gap-4 py-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{a.name}</span>
                  <span className="demo-tag text-ink-2">{a.currency === "USD" ? "美元" : "新台幣"}</span>
                </div>
                {/* 不列手續費率：手續費不自動算（2026-11-14） */}
                {a.broker && <p className="mt-1 text-sm text-ink-2">{a.broker}</p>}
              </div>
              <button type="button" onClick={() => setEditing(a)} aria-label={`編輯 ${a.name}`} className={cn(textAction, "shrink-0")}>
                編輯
              </button>
            </li>
          ))}
        </ul>
      )}
      {editing && (
        <AccountDialog
          key={editing.id || "new"}
          account={editing}
          onClose={() => setEditing(null)}
          onDelete={() => {
            toast.dismiss()
            setDeleting(editing)
            setEditing(null)
          }}
        />
      )}
      {deleting && <DeleteBrokerAccountDialog key={deleting.id} account={deleting} onClose={() => setDeleting(null)} />}
    </Section>
  )
}

const NEW_ACCOUNT: Account = {
  id: "",
  name: "",
  broker: "",
  currency: "TWD",
  fee_rate: 0.001425,
  fee_discount: 0.6,
  min_fee: 20,
  min_fee_odd_lot: 1,
  created_at: "",
}

/** 新增或編輯帳戶（account.id 為空字串時為新增）；編輯時左下角有「刪除這個帳戶」（開輸入帳戶名稱的確認框） */
function AccountDialog({ account, onClose, onDelete }: { account: Account; onClose: () => void; onDelete: () => void }) {
  const isNew = !account.id
  const update = useUpdateAccount()
  const create = useCreateAccount()
  const [name, setName] = useState(account.name)
  const [broker, setBroker] = useState(account.broker)
  const [currency, setCurrency] = useState(account.currency)
  const [touched, setTouched] = useState(false)
  const nameBad = !name.trim()
  const pending = update.isPending || create.isPending
  const save = () => {
    setTouched(true)
    if (nameBad) return
    // 不問手續費（產品負責人 2026-11-14：不自動算手續費，填的價格就是成本；要精準的話記交易時自己填）
    const editable = { name: name.trim(), broker: broker.trim() }
    const done = {
      onSuccess: () => {
        toast.success(isNew ? `已新增「${editable.name}」` : `已更新「${editable.name}」`)
        onClose()
      },
      onError: (err: Error) =>
        toast.error("沒有存成功，內容還在。", { description: err.message }),
    }
    // 編輯時不送幣別：已有交易的帳戶不能改幣別
    if (isNew) create.mutate({ ...editable, currency }, done)
    else update.mutate({ id: account.id, patch: editable }, done)
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isNew ? "新增券商帳戶" : "編輯帳戶"}</DialogTitle>
          <DialogDescription className="sr-only">帳戶名稱與券商。</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 pointer-coarse:[&_input]:h-11">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="帳戶名稱" htmlFor="acc-name" error={touched && nameBad ? "請填帳戶名稱，例如「永豐・一般」" : undefined}>
              <Input id="acc-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={40} placeholder="例如：永豐・一般" aria-invalid={touched && nameBad} />
            </Field>
            <Field label="券商" htmlFor="acc-broker">
              <Input id="acc-broker" value={broker} onChange={(e) => setBroker(e.target.value)} maxLength={40} placeholder="例如：永豐金證券" />
            </Field>
          </div>
          {isNew && (
            <Field label="幣別">
              <RangeChips label="幣別" value={currency} onChange={setCurrency} options={[{ value: "TWD", label: "新台幣" }, { value: "USD", label: "美元（複委託）" }]} />
            </Field>
          )}
        </div>
        <DialogFooter>
          {!isNew && (
            <button type="button" onClick={onDelete} disabled={pending} className={cn(textAction, "mr-auto")}>
              刪除這個帳戶
            </button>
          )}
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button variant="sign" onClick={save} disabled={pending}>{pending ? "儲存中…" : isNew ? "新增帳戶" : "儲存"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
