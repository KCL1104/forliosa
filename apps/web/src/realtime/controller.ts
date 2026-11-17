import type { QueryClient } from "@tanstack/react-query"
import { RealtimeClient, type RealtimeEvent, type Timers } from "./client"
import { markClosesEvent, setRealtimeStatus, type RealtimeStatus } from "./store"
import { enableTabHeader, tabId } from "./tab"
import { actionsFor, applyActions, BROADCAST_TOPICS, fallbackActions, resyncActions, type Action } from "./topics"

/**
 * 一個分頁的即時更新：連線（`client.ts`）＋把事件變成重新讀（`topics.ts`）＋前景／背景的規則。
 *
 * - 收到事件先收集 150 毫秒，同樣的重新讀只做一次（一批裡對到同一個查詢的也只讀一次，`applyActions`）；
 *   行情這種每個人都會收到的，先隨機等 0–1.5 秒；「全部重新讀」（`resync`：部署後、伺服器的 LISTEN 重連後，大家同時收到）
 *   先隨機等 0–3 秒，等的時候又來的 `resync` 併進同一次
 * - 自己這個分頁改的（事件的 `o` 是自己的分頁 id）略過：mutation 已經重新讀過了
 * - 分頁在前景：畫面上有的馬上重新讀；在背景：只標成過期，回到前景時一起讀
 * - 分頁在背景超過 2 分鐘：先關掉串流（保留最後的事件 id），回到前景時重連，伺服器補送錯過的（補不上就全部重新讀）
 * - 串流斷著（連不上、伺服器關掉即時更新）而分頁在前景：每 30 秒把「活的」資料重新讀一次（`fallbackActions`）
 */

export const DEBOUNCE_MS = 150
export const BROADCAST_SPREAD_MS = 1500
export const RESYNC_SPREAD_MS = 3000
export const HIDDEN_CLOSE_MS = 2 * 60_000
export const FALLBACK_MS = 30_000
const FALLBACK_TICK_MS = 5_000

/** 瀏覽器環境（測試換成假的） */
export interface RealtimeEnv {
  visible: () => boolean
  /** 註冊事件，回傳移除的函式；`doc` 是 document（visibilitychange），`win` 是 window（focus、online） */
  listen: (target: "doc" | "win", type: string, fn: () => void) => () => void
}

export const browserEnv: RealtimeEnv = {
  visible: () => typeof document === "undefined" || document.visibilityState !== "hidden",
  listen: (target, type, fn) => {
    const t: EventTarget | undefined = target === "doc" ? (typeof document === "undefined" ? undefined : document) : typeof window === "undefined" ? undefined : window
    t?.addEventListener(type, fn)
    return () => t?.removeEventListener(type, fn)
  },
}

export interface RealtimeControllerOptions {
  qc: QueryClient
  open: (last: string | null, signal: AbortSignal) => Promise<Response>
  /** 正在查看的授權 id（沒有在查看時 null） */
  viewAs: () => string | null
  env?: RealtimeEnv
  timers?: Timers
  random?: () => number
  /** 401／`bye{unauthorized}`：預設把畫面上的資料重新讀——session 真的沒了的話，那些請求的 401 會帶到登入頁（main.tsx） */
  onUnauthorized?: () => void
  /** 開發時印出收到的種類（不印內容） */
  debug?: (message: string) => void
}

const realTimers: Timers = {
  setTimeout: (fn, ms) => globalThis.setTimeout(fn, ms),
  clearTimeout: (h) => globalThis.clearTimeout(h as ReturnType<typeof setTimeout>),
  now: () => Date.now(),
}

export class RealtimeController {
  readonly client: RealtimeClient
  private readonly o: RealtimeControllerOptions
  private readonly env: RealtimeEnv
  private readonly t: Timers
  private readonly random: () => number
  private readonly pending = new Map<string, Action>()
  private flushTimer: unknown = null
  private readonly spreadTimers = new Set<unknown>()
  private hiddenTimer: unknown = null
  private tickTimer: unknown = null
  private notOpenSince: number | null = null
  private resyncPending = false
  private lastFallback = 0
  private unlisten: (() => void)[] = []
  private running = false

  constructor(options: RealtimeControllerOptions) {
    this.o = options
    this.env = options.env ?? browserEnv
    this.t = options.timers ?? realTimers
    this.random = options.random ?? Math.random
    this.client = new RealtimeClient({
      open: options.open,
      onEvent: (e) => this.onEvent(e),
      onResync: () => {
        this.o.debug?.("realtime: resync")
        // 已經有一次「全部重新讀」在等（重連時 `hello` 說 resync、接著又來一個 `resync`）：併成一次，不要每個都讀一輪
        if (this.resyncPending) return
        this.resyncPending = true
        this.spread(resyncActions(), RESYNC_SPREAD_MS, () => (this.resyncPending = false))
      },
      onStatus: (s) => this.onStatus(s),
      onUnauthorized: () => (this.o.onUnauthorized ? this.o.onUnauthorized() : this.queue(resyncActions())),
      onOpen: () => enableTabHeader(),
      timers: this.t,
      random: this.random,
    })
  }

  start(): void {
    if (this.running) return
    this.running = true
    this.notOpenSince = this.t.now()
    this.lastFallback = this.t.now()
    this.unlisten = [
      this.env.listen("doc", "visibilitychange", () => this.onVisibility()),
      this.env.listen("win", "focus", () => this.onFocus()),
      this.env.listen("win", "online", () => this.client.kick()),
    ]
    this.client.start()
    if (!this.env.visible()) this.scheduleHiddenClose()
    this.scheduleTick()
  }

  stop(): void {
    if (!this.running) return
    this.running = false
    for (const off of this.unlisten) off()
    this.unlisten = []
    this.client.stop()
    this.t.clearTimeout(this.flushTimer)
    this.flushTimer = null
    for (const h of this.spreadTimers) this.t.clearTimeout(h)
    this.spreadTimers.clear()
    this.resyncPending = false
    this.t.clearTimeout(this.hiddenTimer)
    this.t.clearTimeout(this.tickTimer)
    this.pending.clear()
    setRealtimeStatus("off")
  }

  // ── 事件 ───────────────────────────────────────────────
  private onEvent(e: RealtimeEvent): void {
    const { o, ...data } = e.data
    // 自己這個分頁送出的變更：送出的那個 mutation 已經讓同一組資料重新讀了
    if (typeof o === "string" && o === tabId) {
      this.o.debug?.(`realtime: ${e.topic} (this tab)`)
      return
    }
    this.o.debug?.(`realtime: ${e.topic}`)
    if (e.topic === "market.closes") markClosesEvent(this.t.now())
    const actions = actionsFor(e.topic, data, { viewAs: this.o.viewAs() })
    if (actions.length === 0) return
    // 公開討論的清單也是每個人都收到（一則公開主題的回覆只有開著那一則的人會重新讀，不必錯開）
    const broadcast = BROADCAST_TOPICS.has(e.topic) || (e.topic === "discussions.list" && data.scope === "public")
    if (broadcast) this.spread(actions)
    else this.queue(actions)
  }

  /** 每個人都收到的：先隨機等一下，大家不要同一秒一起讀 */
  private spread(actions: Action[], within = BROADCAST_SPREAD_MS, fired?: () => void): void {
    const h = this.t.setTimeout(() => {
      this.spreadTimers.delete(h)
      fired?.()
      this.queue(actions)
    }, this.random() * within)
    this.spreadTimers.add(h)
  }

  private queue(actions: Action[]): void {
    if (!this.running) return
    for (const a of actions) this.pending.set(a.id, a)
    if (this.flushTimer === null) this.flushTimer = this.t.setTimeout(() => this.flush(), DEBOUNCE_MS)
  }

  private flush(): void {
    this.flushTimer = null
    if (!this.running || this.pending.size === 0) return
    const actions = [...this.pending.values()]
    this.pending.clear()
    void applyActions(this.o.qc, actions, this.env.visible() ? "active" : "none")
  }

  // ── 狀態、前景／背景 ────────────────────────────────────
  private onStatus(s: RealtimeStatus): void {
    setRealtimeStatus(s)
    if (s === "open") this.notOpenSince = null
    else if (this.notOpenSince === null) this.notOpenSince = this.t.now()
  }

  private onVisibility(): void {
    if (!this.running) return
    if (!this.env.visible()) {
      this.scheduleHiddenClose()
      return
    }
    this.t.clearTimeout(this.hiddenTimer)
    this.hiddenTimer = null
    if (this.client.state === "paused") this.client.resume()
    // 斷著、在等下一次重試（可能要等到 30 秒）：回到前景就馬上試（伺服器說要等的 429／503／401 不算）；
    // 連著但很久沒有心跳（電腦睡過一覺）：馬上重連
    else this.client.kick()
    // 在背景時只標成過期的：現在一起重新讀
    void this.o.qc.refetchQueries({ type: "active", predicate: (q) => q.state.isInvalidated }, { throwOnError: false }).catch(() => undefined)
  }

  private onFocus(): void {
    if (this.running && this.client.replaced && this.env.visible()) this.client.resume()
  }

  private scheduleHiddenClose(): void {
    this.t.clearTimeout(this.hiddenTimer)
    this.hiddenTimer = this.t.setTimeout(() => {
      this.hiddenTimer = null
      if (!this.env.visible()) this.client.pause()
    }, HIDDEN_CLOSE_MS)
  }

  /** 串流斷著、分頁在前景：每 30 秒重新讀一次「活的」資料 */
  private scheduleTick(): void {
    this.tickTimer = this.t.setTimeout(() => {
      this.tickTimer = null
      if (!this.running) return
      const s = this.client.state
      const now = this.t.now()
      if (s !== "open" && s !== "off" && this.env.visible() && this.notOpenSince !== null && now - Math.max(this.notOpenSince, this.lastFallback) >= FALLBACK_MS) {
        this.lastFallback = now
        this.o.debug?.("realtime: fallback refetch")
        this.queue(fallbackActions())
      }
      this.scheduleTick()
    }, FALLBACK_TICK_MS)
  }
}
