import { PencilIcon, PlusIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import { useAccounts, useCreateAccount, useUpdateAccount } from "@/api/queries"
import type { Account } from "@/api/types"
import { BenchmarkSelect } from "@/components/benchmark-select"
import { usePrefSetter } from "@/hooks/use-pref-setter"
import { RangeChips } from "@/components/charts/chart-kit"
import { PageHeader } from "@/components/section"
import { RecurringPlans } from "./RecurringPlans"
import { Delegations } from "./Delegations"
import { Profile } from "./Profile"
import { useReadOnly } from "@/api/view-as"
import { PageFrame } from "@/app/PageFrame"
import { ViewAsBlocked } from "@/app/ViewAsBanner"
import { SourcesFooter } from "@/components/sources"
import { SkeletonLines } from "@/components/states"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { formatMoney } from "@/lib/format"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { FormField as Field } from "@/components/form-field"
import { Pct } from "@/components/finance"


export function SettingsPage() {
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
      <div className="flex max-w-[816px] flex-col gap-10">
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
        <Row label="開啟時預設隱私模式" description="遮蔽所有金額與股數，方便截圖分享；百分比照常顯示。隨時可用上方的眼睛圖示切換。" htmlFor="privacy-default">
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
          <BenchmarkSelect value={p.benchmark} onChange={(v) => setPref({ benchmark: v })} />
        </Row>
      </Group>

      <Accounts />

      <RecurringPlans />

      <Delegations />

      <Group title="之後會有的設定">
        <Row label="AI 額度與用量"><span className="text-sm text-ink-2">之後開放</span></Row>
        <Row label="通知"><span className="text-sm text-ink-2">之後開放</span></Row>
        <Row label="資料匯出與刪除帳號"><span className="text-sm text-ink-2">之後開放</span></Row>
      </Group>
      </div>
      {/* 資料來源：一頁一個頁尾（設定頁沒有自己的資料，就是連到完整顯名聲明） */}
      <SourcesFooter className="max-w-[816px]" />
    </PageFrame>
  )
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  const id = `set-${title}`
  return (
    <section aria-labelledby={id} className="flex flex-col gap-2">
      <h2 id={id} className="border-b border-rule pb-2 text-lg font-bold">{title}</h2>
      <div className="-mt-2 flex flex-col divide-y divide-rule border-b border-rule">{children}</div>
    </section>
  )
}

function Row({ label, description, htmlFor, children }: { label: string; description?: React.ReactNode; htmlFor?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
      <div className="min-w-0">
        {htmlFor ? <label htmlFor={htmlFor} className="font-medium">{label}</label> : <p className="font-medium">{label}</p>}
        {description && <div className="mt-0.5 text-md text-ink-2">{description}</div>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}

function discountText(d: number) {
  return d >= 1 ? "無折扣" : `${Math.round(d * 100) / 10} 折`
}

function Accounts() {
  const accounts = useAccounts()
  const [editing, setEditing] = useState<Account | null>(null)
  return (
    <section id="accounts" aria-labelledby="set-accounts" className="flex scroll-mt-20 flex-col gap-2">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h2 id="set-accounts" className="text-lg font-bold">券商帳戶</h2>
        <Button variant="outline" size="sm" onClick={() => setEditing(NEW_ACCOUNT)}>
          <PlusIcon />
          新增帳戶
        </Button>
      </div>
      {!accounts.data ? (
        <SkeletonLines rows={3} />
      ) : accounts.data.length === 0 ? (
        <p className="rounded-sm border border-dashed p-5 text-md text-ink-2">還沒有帳戶。先新增一個，例如「永豐－一般」，記交易時才會自動算手續費。</p>
      ) : (
        <ul className="flex flex-col divide-y divide-rule border-y border-rule">
          {accounts.data.map((a) => (
            <li key={a.id} className="flex items-start gap-4 py-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{a.name}</span>
                  <span className="demo-tag text-ink-2">{a.currency === "USD" ? "美元" : "新台幣"}</span>
                  <span className="demo-tag text-ink-2">{a.tracking_mode === "transactions" ? "逐筆交易" : "只記持股"}</span>
                </div>
                <dl className="num mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-sm text-ink-2">
                  <div className="flex gap-1"><dt>券商</dt><dd className="text-foreground">{a.broker}</dd></div>
                  <div className="flex gap-1"><dt>手續費</dt><dd className="text-foreground">{(a.fee_rate * 100).toFixed(4).replace(/0+$/, "")}% × {discountText(a.fee_discount)}</dd></div>
                  <div className="flex gap-1"><dt>最低</dt><dd className="text-foreground">{formatMoney(a.min_fee, { currency: a.currency, decimals: 0 })}{a.currency === "TWD" && `（零股 ${formatMoney(a.min_fee_odd_lot, { decimals: 0 })}）`}</dd></div>
                </dl>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setEditing(a)} aria-label={`編輯 ${a.name}`}>
                <PencilIcon />
                編輯
              </Button>
            </li>
          ))}
        </ul>
      )}
      {editing && <AccountDialog key={editing.id || "new"} account={editing} onClose={() => setEditing(null)} />}
    </section>
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
  tracking_mode: "transactions",
  created_at: "",
}

/** 新增或編輯帳戶（account.id 為空字串時為新增） */
function AccountDialog({ account, onClose }: { account: Account; onClose: () => void }) {
  const isNew = !account.id
  const update = useUpdateAccount()
  const create = useCreateAccount()
  const [name, setName] = useState(account.name)
  const [broker, setBroker] = useState(account.broker)
  const [currency, setCurrency] = useState(account.currency)
  const [mode, setMode] = useState(account.tracking_mode)
  const [discount, setDiscount] = useState(String(Math.round(account.fee_discount * 100) / 10))
  const [minFee, setMinFee] = useState(String(account.min_fee))
  const [minOdd, setMinOdd] = useState(String(account.min_fee_odd_lot))
  const [touched, setTouched] = useState(false)
  const d = Number(discount)
  const discountBad = Number.isNaN(d) || d <= 0 || d > 10
  const nameBad = !name.trim()
  const pending = update.isPending || create.isPending
  const save = () => {
    setTouched(true)
    if (nameBad || discountBad) return
    const editable = {
      name: name.trim(),
      broker: broker.trim(),
      fee_discount: d / 10,
      min_fee: Number(minFee) || 0,
      min_fee_odd_lot: Number(minOdd) || 0,
    }
    const done = {
      onSuccess: () => {
        toast.success(isNew ? `已新增「${editable.name}」` : `已更新「${editable.name}」`)
        onClose()
      },
      onError: (err: Error) =>
        toast.error(isNew ? "新增失敗，表單內容仍保留" : "更新失敗，表單內容仍保留", { description: err.message }),
    }
    // 編輯時不送幣別、追蹤方式與費率：已有交易的帳戶不能改幣別，也不要覆蓋自訂費率
    if (isNew) create.mutate({ ...editable, currency, tracking_mode: mode, fee_rate: currency === "USD" ? 0.001 : 0.001425 }, done)
    else update.mutate({ id: account.id, patch: editable }, done)
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-lg font-bold">{isNew ? "新增券商帳戶" : "編輯帳戶"}</DialogTitle>
          <DialogDescription>折扣用「幾折」輸入，例如 2.8 折就填 2.8；不知道的話先填 6，之後可以改。</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="帳戶名稱" htmlFor="acc-name" error={touched && nameBad ? "請填帳戶名稱，例如「永豐－一般」" : undefined}>
              <Input id="acc-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={40} placeholder="例如：永豐－一般" aria-invalid={touched && nameBad} />
            </Field>
            <Field label="券商" htmlFor="acc-broker">
              <Input id="acc-broker" value={broker} onChange={(e) => setBroker(e.target.value)} maxLength={40} placeholder="例如：永豐金證券" />
            </Field>
          </div>
          {isNew && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="幣別">
                <RangeChips label="幣別" value={currency} onChange={setCurrency} options={[{ value: "TWD", label: "新台幣" }, { value: "USD", label: "美元（複委託）" }]} />
              </Field>
              <Field label="追蹤方式">
                <RangeChips label="追蹤方式" value={mode} onChange={setMode} options={[{ value: "transactions", label: "逐筆交易" }, { value: "holdings", label: "只記持股" }]} />
              </Field>
            </div>
          )}
          <div className="grid grid-cols-3 gap-3">
            <Field label="手續費折扣（折）" htmlFor="acc-discount" error={touched && discountBad ? "請填 0.1 到 10" : undefined}>
              <Input id="acc-discount" inputMode="decimal" value={discount} onChange={(e) => setDiscount(e.target.value)} aria-invalid={touched && discountBad} />
            </Field>
            <Field label="最低手續費" htmlFor="acc-min"><Input id="acc-min" inputMode="decimal" value={minFee} onChange={(e) => setMinFee(e.target.value)} /></Field>
            <Field label="零股最低" htmlFor="acc-odd"><Input id="acc-odd" inputMode="decimal" value={minOdd} onChange={(e) => setMinOdd(e.target.value)} /></Field>
          </div>
        </div>
        <DialogFooter className={cn("gap-2")}>
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button variant="sign" onClick={save} disabled={pending}>{pending ? "儲存中…" : isNew ? "新增帳戶" : "儲存"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
