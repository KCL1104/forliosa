import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { api, appToday } from "@/api"
import { accountsQuery, holdingsQuery, qk } from "@/api/queries"
import { ApiError, type Instrument, type TransactionInput } from "@/api/types"
import { useUi } from "@/app/ui-store"
import { formatDateShort, formatMoney, formatPrice, formatQuantity } from "@/lib/format"
import { codeOf, marketOf } from "@/lib/tick"
import { usePrefs } from "@/stores/prefs"
import { parseIntent, sharesOf } from "./intent"
import { AI_UNAVAILABLE } from "./answer-text"
import { aiApi, aiRemote, applyChatEvent, draftFromServer, streamChat, type AiUsage, type ChatEvent } from "./remote"
import { aiKeys } from "./remote-hooks"
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
  const updateMessage = useAi((s) => s.updateMessage)
  const setRemoteId = useAi((s) => s.setRemoteId)
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

  /** 真實後端：`POST /ai/chat` 串流。文字片段每 40ms 合併寫入一次，避免每個字都重繪與寫入 localStorage */
  async function submitRemote(text: string) {
    push({ role: "user", text }, { title: text })
    const localThreadId = useAi.getState().threadId!
    const remoteId = useAi.getState().threads.find((t) => t.id === localThreadId)?.remoteId ?? null
    const aiId = push({ role: "ai", text: "", streaming: true })
    let buffered = ""
    let timer: ReturnType<typeof setTimeout> | null = null
    const flush = () => {
      if (timer !== null) clearTimeout(timer)
      timer = null
      if (!buffered) return
      const delta = buffered
      buffered = ""
      updateMessage(aiId, (m) => ({ ...m, text: (m.text ?? "") + delta }))
    }
    const onEvent = (e: ChatEvent) => {
      if (e.event === "text") {
        buffered += e.data.delta
        if (timer === null) timer = setTimeout(flush, 40)
        return
      }
      flush()
      if (e.event === "thread") {
        setRemoteId(localThreadId, e.data.id)
        return
      }
      if (e.event === "draft") upsertDraft(draftFromServer(e.data))
      updateMessage(aiId, (m) => applyChatEvent(m, e))
      if (e.event === "done") {
        void qc.invalidateQueries({ queryKey: aiKeys.usage })
        void qc.invalidateQueries({ queryKey: aiKeys.threads })
      }
    }
    const symbol = ctx.route === "stock" ? ctx.stock.symbol : null
    try {
      await streamChat({ thread_id: remoteId, message: text, page: { route: window.location.pathname, symbol }, privacy }, onEvent)
      flush()
      updateMessage(aiId, (m) => ({ ...m, streaming: false }))
    } catch (err) {
      flush()
      if (err instanceof ApiError && err.code === "ai_unavailable") {
        // 所有金鑰都不能用（或沒有設定）：安靜說明；記帳指令不需要模型，照樣寫成草稿
        updateMessage(aiId, (m) => ({ ...m, streaming: false, error: { code: "ai_unavailable", message: AI_UNAVAILABLE } }))
        void qc.invalidateQueries({ queryKey: aiKeys.usage })
        await draftFrom(text)
        return
      }
      const error = err instanceof ApiError ? { code: err.code, message: err.message } : { code: "network", message: "連不上伺服器，請稍後再試。" }
      updateMessage(aiId, (m) => ({ ...m, streaming: false, error }))
      if (err instanceof ApiError && err.status === 429) void qc.invalidateQueries({ queryKey: aiKeys.usage })
    }
  }

  async function submit(raw: string) {
    const text = raw.trim()
    if (!text) return
    const current = useAi.getState().threads.find((t) => t.id === useAi.getState().threadId)
    if (current?.messages.some((m) => m.streaming)) {
      toast("等這一則回答完再問下一題")
      return
    }
    if (aiRemote) {
      // 後端已經回報 AI 無法使用（/ai/usage 的 available=false）：不送出，說明一句；記帳指令照樣寫成草稿
      if (qc.getQueryData<AiUsage>(aiKeys.usage)?.available === false) {
        push({ role: "user", text }, { title: text })
        push({ role: "ai", error: { code: "ai_unavailable", message: AI_UNAVAILABLE } })
        await draftFrom(text)
        return
      }
      return submitRemote(text)
    }
    push({ role: "user", text }, { title: text })
    await answerLocally(text)
  }

  /** 本機規則版（mock 模式與後端沒有 AI 時）。`replaceId`：把回答寫進已經存在的 AI 訊息 */
  async function answerLocally(text: string, replaceId?: string) {
    const reply = (answer: Answer) => (replaceId ? updateMessage(replaceId, (m) => ({ ...m, answer })) : say(answer))
    try {
      if (!replaceId && (await draftFrom(text))) return
      const intent = parseIntent(text, appToday())
      if (intent.kind === "lookup") {
        const inst = await resolveInstrument(intent.target)
        if (inst) {
          reply({ text: `${inst.name}（${inst.code}）在這裡。`, links: [{ label: `看${inst.name}`, to: "/stock/$symbol", params: { symbol: inst.symbol } }] })
          return
        }
      }
      const kind = classifyQuestion(text, ctx)
      const a = kind ? answer(kind) : null
      reply(a ?? fallbackAnswer(text, ctx))
    } catch (err) {
      reply({ text: `這次沒有處理好：${err instanceof Error ? err.message : "請再試一次"}。` })
    }
  }

  /**
   * 定期定額：`POST /recurring/{id}/draft?date=<原本的扣款日>` 寫成草稿（不會建立交易），簽名後才 `POST /transactions`。
   * 扣款日當天，或補記最近 7 天漏記的一次（`missed`）。後端依 `date` 順延到交易日並把成交日設成那天；
   * 萬一回來的是別次扣款（後端沒有吃到 `date`），成交日改回這一次的扣款日。
   */
  async function draftRecurring(s: Suggestion) {
    const r = s.recurring
    if (!r) return
    push({ role: "user", text: s.text }, { title: s.text })
    try {
      const d = await api.draftRecurring(r.planId, r.scheduledDate)
      const symbol = d.transaction.symbol
      const tradeDate = d.scheduled_date === r.scheduledDate ? d.transaction.trade_date : r.date
      const estimate = `${formatMoney(d.amount)} 以 ${formatDateShort(d.price_as_of, false)} 收盤價 ${formatPrice(d.transaction.price, marketOf(symbol))} 估算股數（含零股），手續費另計`
      const draft: Draft = {
        id: newId("dft"),
        status: "pending",
        input: { ...d.transaction, trade_date: tradeDate, amount: null },
        instrument: { symbol, code: codeOf(symbol), name: d.name, market: marketOf(symbol), currency: "TWD" },
        preview: d.preview,
        notes: [
          r.missed
            ? `${estimate}；這是 ${formatDateShort(tradeDate, false)} 的扣款，請照券商對帳單改成實際成交的股數和價格再簽名。`
            : `${estimate}；實際成交以券商對帳單為準，簽名前可以改。`,
        ],
        createdAt: new Date().toISOString(),
        recurring: { planId: r.planId, date: r.date },
      }
      upsertDraft(draft)
      push({
        role: "ai",
        text: r.missed
          ? `${formatDateShort(tradeDate, false)} 是${d.name}定期定額的扣款日，帳本裡還沒有這一筆。\n我先照最近收盤價算好股數和手續費，你照對帳單改好再簽名，簽了才會入帳。`
          : `今天是${d.name}定期定額的扣款日。\n我照最近收盤價算好股數和手續費，簽名後才會入帳。`,
        draftId: draft.id,
      })
    } catch (err) {
      say({
        text: `這次的定期定額草稿沒有寫成：${err instanceof Error ? err.message : "請再試一次"}。`,
        links: [{ label: "查看定期定額", to: "/settings" }],
      })
    }
  }

  function ask(s: Suggestion) {
    if (s.kind === "recurring_draft") {
      void draftRecurring(s)
      return
    }
    if (aiRemote) {
      void submit(s.text)
      return
    }
    push({ role: "user", text: s.text }, { title: s.text })
    say(answer(s.kind) ?? fallbackAnswer(s.text, ctx))
  }

  /** 後端草稿的狀態同步（失敗不影響帳本：交易已經照使用者的簽名寫入或刪除） */
  function syncDraft(id: string, body: Parameters<typeof aiApi.patchDraft>[1]) {
    if (useAi.getState().drafts[id]?.remote) void aiApi.patchDraft(id, body).catch(() => undefined)
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
      syncDraft(id, { status: "signed", transaction_id: txn.id })
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
      syncDraft(id, { status: "pending" })
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
    syncDraft(id, { status: "discarded" })
  }

  return { submit, ask, action, sign, undo, revise, discard }
}
