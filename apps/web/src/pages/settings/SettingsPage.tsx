import { PencilIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import { api } from "@/api"
import { useAccounts, useUpdateAccount, useUpdatePreferences } from "@/api/queries"
import type { Account, Preferences } from "@/api/types"
import { Chop, DemoChop, SoonChop } from "@/components/chop"
import { RangeChips } from "@/components/charts/chart-kit"
import { PageHeader } from "@/components/section"
import { SkeletonLines } from "@/components/states"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { formatMoney } from "@/lib/format"
import { cn } from "@/lib/utils"
import { usePrefs, type PrefsState } from "@/stores/prefs"
import { FormField as Field } from "@/components/form-field"

type PrefPatch = Partial<Pick<PrefsState, "colorConvention" | "theme" | "quantityUnit" | "privacyDefault" | "costMethod" | "benchmark" | "compactNumbers">>

/** 本機立即生效，再同步到伺服器；失敗時還原並通知 */
function usePrefSetter() {
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
      onError: () => {
        set(before)
        toast.error("設定沒有存到伺服器，已還原", { description: "請檢查網路後再試一次。" })
      },
    })
  }
}

export function SettingsPage() {
  const p = usePrefs()
  const setPref = usePrefSetter()
  return (
    <div className="flex max-w-3xl flex-col gap-8">
      <PageHeader title="設定" description="顯示設定會立即套用，並同步到你的帳號。" />

      <Group title="顯示">
        <Row
          label="漲跌顏色"
          description={
            <span className="inline-flex flex-wrap items-center gap-3">
              預覽：
              <span className="num text-rise">▲ +1.23%</span>
              <span className="num text-fall">▼ −0.85%</span>
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
        <Row label="主題" description="跟隨系統會依手機或電腦的深色模式切換。">
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
        <Row label="股數顯示" description={p.quantityUnit === "lot" ? "例如「1 張 500 股」（1 張 = 1,000 股）" : "例如「1,500 股」"}>
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
        <Row label="大數字縮寫" description="空間不夠時以萬、億顯示（例如 NT$328.45 萬）；明細頁仍顯示完整數字。" htmlFor="compact">
          <Switch id="compact" checked={p.compactNumbers} onCheckedChange={(v) => setPref({ compactNumbers: v })} />
        </Row>
      </Group>

      <Group title="隱私">
        <Row label="開啟時預設隱私模式" description="遮蔽所有金額與股數，方便截圖分享；百分比照常顯示。隨時可用上方的眼睛圖示切換。" htmlFor="privacy-default">
          <Switch id="privacy-default" checked={p.privacyDefault} onCheckedChange={(v) => setPref({ privacyDefault: v })} />
        </Row>
      </Group>

      <Group title="計算">
        <Row label="成本計算方式" description="台灣券商多用移動平均；FIFO 會讓先買的先賣出。改變後已實現損益會重新計算。">
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
        <Row label="績效比較基準" description="發行量加權股價報酬指數需要後端提供資料（待確認）。">
          <RangeChips
            label="績效比較基準"
            value={p.benchmark}
            onChange={(v) => setPref({ benchmark: v })}
            options={[
              { value: "0050.TW", label: "元大台灣50" },
              { value: "006208.TW", label: "富邦台50" },
              { value: "VOO", label: "S&P 500（VOO）" },
            ]}
          />
        </Row>
      </Group>

      <Accounts />

      <Group title="之後會有的設定">
        <Row label="AI 額度與用量" description="每日對話次數、每月深度報告次數。"><SoonChop milestone="M4" /></Row>
        <Row label="通知" description="到價、漲跌幅、除權息提醒；Telegram 與 Discord。"><SoonChop milestone="M4" /></Row>
        <Row label="資料匯出與刪除帳號" description="依個資法提供 CSV 匯出與刪除帳號。"><SoonChop milestone="M5" /></Row>
      </Group>

      <Group title="關於資料">
        <div className="flex flex-col gap-2 px-4 py-4 text-md text-muted-foreground sm:px-5">
          {api.kind === "mock" && (
            <p className="flex flex-wrap items-center gap-2">
              <DemoChop /> 目前沒有連到後端，所有數字都是示範資料。設定 <code className="rounded bg-muted px-1 text-sm">VITE_API_BASE_URL</code> 後改用真實資料。
            </p>
          )}
          <p>行情與公司資料來自臺灣證券交易所、櫃買中心 OpenAPI 與 shioaji-data（政府資料開放授權條款第 1 版）。盤中報價為延遲資料，僅供參考。</p>
          <p>K 線圖使用 TradingView Lightweight Charts™（Apache-2.0）。</p>
        </div>
      </Group>
    </div>
  )
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  const id = `set-${title}`
  return (
    <section aria-labelledby={id} className="flex flex-col gap-2">
      <h2 id={id} className="text-lg font-semibold">{title}</h2>
      <div className="flex flex-col divide-y divide-hairline rounded-xl border bg-card">{children}</div>
    </section>
  )
}

function Row({ label, description, htmlFor, children }: { label: string; description?: React.ReactNode; htmlFor?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6 sm:px-5">
      <div className="min-w-0">
        {htmlFor ? <label htmlFor={htmlFor} className="font-medium">{label}</label> : <p className="font-medium">{label}</p>}
        {description && <div className="mt-0.5 text-md text-muted-foreground">{description}</div>}
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
    <section aria-labelledby="set-accounts" className="flex flex-col gap-2">
      <h2 id="set-accounts" className="text-lg font-semibold">券商帳戶</h2>
      <p className="text-md text-muted-foreground">手續費折扣與最低手續費用來自動計算每筆交易的費用。</p>
      {!accounts.data ? (
        <SkeletonLines rows={3} />
      ) : accounts.data.length === 0 ? (
        <p className="rounded-xl border border-dashed p-5 text-md text-muted-foreground">還沒有帳戶。新增帳戶的功能會和登入一起上線（M1）。</p>
      ) : (
        <ul className="flex flex-col divide-y divide-hairline rounded-xl border bg-card">
          {accounts.data.map((a) => (
            <li key={a.id} className="flex items-start gap-4 px-4 py-4 sm:px-5">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{a.name}</span>
                  <Chop tone="muted">{a.currency === "USD" ? "美元" : "新台幣"}</Chop>
                  <Chop tone="muted">{a.tracking_mode === "transactions" ? "逐筆交易" : "只記持股"}</Chop>
                </div>
                <dl className="num mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-sm text-muted-foreground">
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
      {editing && <AccountDialog account={editing} onClose={() => setEditing(null)} />}
    </section>
  )
}

function AccountDialog({ account, onClose }: { account: Account; onClose: () => void }) {
  const update = useUpdateAccount()
  const [name, setName] = useState(account.name)
  const [discount, setDiscount] = useState(String(Math.round(account.fee_discount * 100) / 10))
  const [minFee, setMinFee] = useState(String(account.min_fee))
  const [minOdd, setMinOdd] = useState(String(account.min_fee_odd_lot))
  const d = Number(discount)
  const invalid = !name.trim() || Number.isNaN(d) || d <= 0 || d > 10
  const save = () => {
    if (invalid) return
    update.mutate(
      { id: account.id, patch: { name: name.trim(), fee_discount: d / 10, min_fee: Number(minFee) || 0, min_fee_odd_lot: Number(minOdd) || 0 } },
      {
        onSuccess: () => {
          toast.success(`已更新「${name.trim()}」`)
          onClose()
        },
        onError: () => toast.error("更新失敗，請稍後再試"),
      },
    )
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-lg font-semibold">編輯帳戶</DialogTitle>
          <DialogDescription>折扣用「幾折」輸入，例如 2.8 折就填 2.8。</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <Field label="帳戶名稱" htmlFor="acc-name"><Input id="acc-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={40} /></Field>
          <div className="grid grid-cols-3 gap-3">
            <Field label="手續費折扣（折）" htmlFor="acc-discount" error={invalid && name.trim() ? "請填 0.1 到 10" : undefined}>
              <Input id="acc-discount" inputMode="decimal" value={discount} onChange={(e) => setDiscount(e.target.value)} aria-invalid={invalid && !!name.trim()} />
            </Field>
            <Field label="最低手續費" htmlFor="acc-min"><Input id="acc-min" inputMode="decimal" value={minFee} onChange={(e) => setMinFee(e.target.value)} /></Field>
            <Field label="零股最低" htmlFor="acc-odd"><Input id="acc-odd" inputMode="decimal" value={minOdd} onChange={(e) => setMinOdd(e.target.value)} /></Field>
          </div>
        </div>
        <DialogFooter className={cn("gap-2")}>
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={save} disabled={invalid || update.isPending}>{update.isPending ? "儲存中…" : "儲存"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
