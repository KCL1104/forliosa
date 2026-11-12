import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { api, appToday } from "@/api"
import { accountsQuery, holdingsQuery, qk } from "@/api/queries"
import type { Instrument, TransactionInput } from "@/api/types"
import { useUi } from "@/app/ui-store"
import { formatDateShort, formatPrice, formatQuantity } from "@/lib/format"
import { usePrefs } from "@/stores/prefs"
import { parseIntent, sharesOf } from "./intent"
import { newId, useAi } from "./store"
import { answerFor, classifyQuestion, fallbackAnswer, type AiContext } from "./suggestions"
import type { Answer, Draft, DraftInstrument, Suggestion } from "./types"

/** 常用動作（依頁面）：記一筆交易、匯入對帳單、股利入帳… */
export type AiAction = "trade" | "import" | "dividend" | "alert" | "checkup" | "form"

const DRAFT_SAYS = "我照你說的算好了稅費，\n簽名後才會入帳。"

function describe(d: Pick<Draft, "input" | "instrument">): string {
  const { input, instrument } = d
  if (input.type === "cash_dividend") return `${instrument.name} 股利入帳`
  const verb = input.type === "sell" ? "賣出" : "買進"
  const qty = input.quantity !== null ? formatQuantity(input.quantity, "lot", instrument.market) : ""
  return `${verb} ${instrument.name} ${qty}`
}

export function useAiRunner(ctx: AiContext) {
  const qc = useQueryClient()
  const push = useAi((s) => s.push)
  const upsertDraft = useAi((s) => s.upsertDraft)
  const patchDraft = useAi((s) => s.patchDraft)
  const seedComposer = useAi((s) => s.seedComposer)
  const openTradeForm = useUi((s) => s.openTradeForm)
  const privacy = usePrefs((s) => s.privacyMode)

  const say = (answer: Answer) => push({ role: "ai", answer })

  async function resolveInstrument(target: string): Promise<Instrument | null> {
    const q = target.trim()
    const results = await qc.fetchQuery({ queryKey: qk.search(q), queryFn: () => api.searchInstruments(q), staleTime: 5 * 60_000 })
    const upper = q.toUpperCase()
    return (
      results.find((i) => i.code.toUpperCase() === upper || i.symbol.toUpperCase() === upper) ??
      results.find((i) => i.name === q) ??
      results[0] ??
      null
    )
  }

  async function preview(draftId: string, input: TransactionInput) {
    try {
      const p = await api.previewTransaction(input)
      patchDraft(draftId, { preview: p, status: "pending", error: undefined })
    } catch (err) {
      patchDraft(draftId, { status: "error", error: err instanceof Error ? err.message : "稅費試算失敗" })
    }
  }

  async function draftFrom(text: string): Promise<boolean> {
    const today = appToday()
    const intent = parseIntent(text, today)
    if (intent.kind !== "trade" && intent.kind !== "dividend") return false
    const inst = await resolveInstrument(intent.target)
    if (!inst) {
      say({ text: `找不到「${intent.target}」。換個代號試試，例如 0050、2330 或 NVDA。` })
      return true
    }
    const accounts = await qc.fetchQuery(accountsQuery())
    const account = accounts.find((a) => a.currency === inst.currency) ?? accounts[0]
    if (!account) {
      say({ text: "還沒有券商帳戶，草稿不知道手續費怎麼算。先新增一個帳戶，再說一次就好。", links: [{ label: "新增券商帳戶", to: "/settings" }] })
      return true
    }
    const isUS = inst.market === "US"
    const notes: string[] = []
    const instrument: DraftInstrument = { symbol: inst.symbol, code: inst.code, name: inst.name, market: inst.market, currency: inst.currency }
    let input: TransactionInput
    if (intent.kind === "trade") {
      const shares = sharesOf(intent.quantity, intent.unit, isUS)
      let price = intent.price
      if (price === null) {
        const q = await qc.fetchQuery({ queryKey: qk.quote(inst.symbol), queryFn: () => api.getQuote(inst.symbol), staleTime: 15_000 })
        price = q.price
        notes.push(`沒有寫價格，先用最新價 ${formatPrice(q.price, inst.market)} 估算；簽名前可以改。`)
      }
      if (!isUS && intent.unit === null) notes.push(`沒有寫單位，當作 ${formatQuantity(shares, "lot", inst.market)}。`)
      if (intent.side === "sell") {
        const holdings = await qc.fetchQuery(holdingsQuery())
        const held = holdings.find((h) => h.symbol === inst.symbol)?.quantity ?? 0
        if (held < shares) notes.push(`你目前持有 ${formatQuantity(held, "lot", inst.market)}，賣出的股數比持股多，入帳時會被擋下。`)
      }
      input = { account_id: account.id, symbol: inst.symbol, type: intent.side, trade_date: intent.date ?? today, quantity: shares, price }
    } else {
      input = { account_id: account.id, symbol: inst.symbol, type: "cash_dividend", trade_date: intent.date ?? today, quantity: null, price: null, amount: intent.amount }
      notes.push("參與分配的股數由除息日前的持股自動帶入。")
    }
    const draft: Draft = { id: newId("dft"), status: "loading", input, instrument, notes, createdAt: new Date().toISOString() }
    upsertDraft(draft)
    push({ role: "ai", text: intent.kind === "dividend" ? "我照你說的整理好了，簽名後才會入帳。" : DRAFT_SAYS, draftId: draft.id })
    await preview(draft.id, input)
    return true
  }

  function answer(kind: Suggestion["kind"]): Answer | null {
    return answerFor(kind, { ctx, privacy, today: appToday() })
  }

  async function submit(raw: string) {
    const text = raw.trim()
    if (!text) return
    push({ role: "user", text }, { title: text })
    try {
      if (await draftFrom(text)) return
      const intent = parseIntent(text, appToday())
      if (intent.kind === "lookup") {
        const inst = await resolveInstrument(intent.target)
        if (inst) {
          say({ text: `${inst.name}（${inst.code}）在這裡。`, links: [{ label: `看${inst.name}`, to: "/stock/$symbol", params: { symbol: inst.symbol } }] })
          return
        }
      }
      const kind = classifyQuestion(text, ctx)
      const a = kind ? answer(kind) : null
      say(a ?? fallbackAnswer(text, ctx))
    } catch (err) {
      say({ text: `這次沒有處理好：${err instanceof Error ? err.message : "請再試一次"}。` })
    }
  }

  function ask(s: Suggestion) {
    push({ role: "user", text: s.text }, { title: s.text })
    say(answer(s.kind) ?? fallbackAnswer(s.text, ctx))
  }

  function action(kind: AiAction, opts: { code?: string } = {}) {
    switch (kind) {
      case "trade":
        push({ role: "user", text: opts.code ? `記一筆 ${opts.code}` : "記一筆交易" }, { title: "記一筆交易" })
        say({
          text: `說說看買賣了什麼，例如「${opts.code ? `買 ${opts.code} 1 張` : "買 0050 2 張 52.4"}」。我會先算好手續費和稅，寫成草稿給你簽名。`,
          links: [{ label: "改用表單填", to: "#trade-form" }],
        })
        seedComposer(opts.code ? `買 ${opts.code} ` : "買 ")
        return
      case "import":
        push({ role: "user", text: "匯入對帳單" }, { title: "匯入對帳單" })
        say({ text: "匯入對帳單在下一階段（M3）開放。現在可以把對帳單上的每一筆說給我，例如「買 2330 1 張 1085」，我會一筆一筆寫成草稿。" })
        return
      case "dividend": {
        push({ role: "user", text: "股利入帳" }, { title: "股利入帳" })
        const upcoming = qc.getQueryData<{ type: string; symbol: string | null; title: string; amount_estimate: number | null; date: string }[]>(qk.upcoming(7)) ?? []
        const follow = upcoming
          .filter((u) => u.type === "dividend_payment" && u.symbol && u.amount_estimate)
          .map((u) => `${u.title.split(" ")[0]} 配息 ${Math.round(u.amount_estimate!)}`)
        say({
          text: `哪一檔、領了多少？例如「${opts.code ?? "00878"} 配息 1,100」。金額照存摺上的實際入帳數字就好。`,
          followUps: follow.slice(0, 2),
        })
        seedComposer(opts.code ? `${opts.code} 配息 ` : "")
        return
      }
      case "alert":
        push({ role: "user", text: "設定到價提醒" }, { title: "設定到價提醒" })
        say({ text: "到價提醒在下一階段（M4）開放，會和盤後報告一起推播。現在可以先把它加入觀察，帳本上會看到今天的走勢。" })
        return
      case "checkup":
        push({ role: "user", text: "排定持倉健檢" }, { title: "排定持倉健檢" })
        say({ text: "定期健檢在下一階段（M4）開放。排好之後會出現在「紀錄」裡的 AI 任務。" })
        return
      case "form":
        openTradeForm(opts.code ? { symbol: opts.code } : undefined)
        return
    }
  }

  async function sign(id: string) {
    const d = useAi.getState().drafts[id]
    if (!d || d.status !== "pending") return
    try {
      const txn = await api.createTransaction({ ...d.input, source: "ai_draft" })
      patchDraft(id, { status: "signed", txnId: txn.id, signedAt: new Date().toISOString() })
      void qc.invalidateQueries({ queryKey: ["portfolio"] })
      void qc.invalidateQueries({ queryKey: ["transactions"] })
      toast.success(`已入帳：${describe(d)}`, {
        description: `${formatDateShort(d.input.trade_date)}・由 AI 草稿建立，你已簽名`,
        action: { label: "復原", onClick: () => void undo(id) },
      })
    } catch (err) {
      patchDraft(id, { status: "error", error: err instanceof Error ? err.message : "入帳失敗" })
      toast.error("沒有入帳", { description: err instanceof Error ? err.message : "請再試一次" })
    }
  }

  async function undo(id: string) {
    const d = useAi.getState().drafts[id]
    if (!d?.txnId) return
    try {
      await api.deleteTransaction(d.txnId)
      patchDraft(id, { status: "pending", txnId: undefined, signedAt: undefined })
      void qc.invalidateQueries({ queryKey: ["portfolio"] })
      void qc.invalidateQueries({ queryKey: ["transactions"] })
      toast("已復原，草稿還在等你簽名")
    } catch (err) {
      toast.error("復原失敗", { description: err instanceof Error ? err.message : "請到交易紀錄手動刪除" })
    }
  }

  async function revise(id: string, patch: Partial<TransactionInput>) {
    const d = useAi.getState().drafts[id]
    if (!d) return
    const input = { ...d.input, ...patch }
    patchDraft(id, { input, status: "loading", notes: d.notes.filter((n) => !n.startsWith("沒有寫")) })
    await preview(id, input)
  }

  function discard(id: string) {
    patchDraft(id, { status: "discarded" })
  }

  return { submit, ask, action, sign, undo, revise, discard }
}
