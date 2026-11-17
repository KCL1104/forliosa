import { createSseReader, type SseMessage } from "@/lib/sse"
import type { RealtimeStatus } from "./store"

/**
 * `GET /api/v1/events` 的連線（docs/api-contract.md「即時更新（2026-11-17）」）：一個分頁一條。
 *
 * 用 `fetch` 讀串流，不用 `EventSource`：要看得到 HTTP 狀態（401 停、429／503 照 `Retry-After` 等、403 停）、
 * 自己的退避（第一次 0–3 秒、之後加倍到 30 秒、完全隨機；部署後大家不會同一秒一起重連）、可以中斷（分頁在背景太久、登出）。
 * 429／503 要等多久：先看 `Retry-After` 標頭，跨網域讀不到時看回應的 `error.retry_after_seconds`；`realtime_off`（伺服器關掉即時更新）一律停 10 分鐘。
 * 登入靠 cookie（`credentials: "include"`）；`last` 用網址參數帶，請求仍是不用預檢的簡單請求。
 *
 * - `hello`：連上了。`replay` 是 `resync`（或第一次連上之前已經斷過）時通知重新讀全部（`onResync`）
 * - `resync`：伺服器說可能漏了事件
 * - `bye`：`rotate` 馬上帶 `last` 重連（補上錯過的）；`replaced` 暫停，等分頁回到前景（controller 呼叫 `resume`）；
 *   `unauthorized` 1–2 秒後再連一次：同一個瀏覽器重新登入時舊的 session 換掉了，但 cookie 已經是新的，連得上就照常；
 *   回 401 才是真的登出或過期（停 10 分鐘並通知）
 * - 心跳 `: ping` 每 20 秒：太久沒有任何資料（心跳的 2.5 倍）就當作斷線重連
 */

export interface RealtimeEvent {
  topic: string
  data: Record<string, unknown>
}

export type ReplayMode = "none" | "replayed" | "resync"

export interface Timers {
  setTimeout: (fn: () => void, ms: number) => unknown
  clearTimeout: (handle: unknown) => void
  now: () => number
}

export interface RealtimeClientOptions {
  /** 打開串流（`last`：上次收到的事件 id）；回傳的 Response 還沒讀 body */
  open: (last: string | null, signal: AbortSignal) => Promise<Response>
  onEvent: (e: RealtimeEvent) => void
  /** 可能漏了事件：畫面上的資料全部重新讀 */
  onResync: () => void
  onStatus: (s: RealtimeStatus) => void
  /** 401 或 `bye{unauthorized}`（登出、session 過期、帳號刪除） */
  onUnauthorized?: () => void
  /** 每次連上（收到 `hello`） */
  onOpen?: (hello: { boot: string; replay: ReplayMode }) => void
  timers?: Timers
  random?: () => number
}

export const BACKOFF_BASE_MS = 1000
export const BACKOFF_MAX_MS = 30_000
/** 斷線後第一次重連的範圍（0–3 秒）：部署、伺服器重啟時大家的重連與重新讀分散開 */
export const RECONNECT_SPREAD_MS = 3000
/** `bye{unauthorized}` 後再試一次之前等多久（再加 0–1 秒） */
export const UNAUTHORIZED_RECHECK_MS = 1000
/** 連上超過這麼久才把退避歸零（一連上就斷的伺服器不會被一直狂連） */
export const STABLE_MS = 30_000
/** 403、401、找不到（舊版後端）、`realtime_off`：先停這麼久 */
export const HOLD_MS = 10 * 60_000
const DEFAULT_HEARTBEAT_S = 20
/** 還沒收到 hello（連線中、等回應）時多久沒動靜就放棄 */
const CONNECT_TIMEOUT_MS = 30_000

const realTimers: Timers = {
  setTimeout: (fn, ms) => globalThis.setTimeout(fn, ms),
  clearTimeout: (h) => globalThis.clearTimeout(h as ReturnType<typeof setTimeout>),
  now: () => Date.now(),
}

export class RealtimeClient {
  private readonly o: RealtimeClientOptions
  private readonly t: Timers
  private readonly random: () => number
  private running = false
  private paused = false
  private ctrl: AbortController | null = null
  private status: RealtimeStatus = "off"
  private attempt = 0
  private holdUntil = 0
  private gap = false
  private heartbeatMs = DEFAULT_HEARTBEAT_S * 1000
  /** 最後一次收到任何資料（含心跳）的時間 */
  private lastByteAt = 0
  private retryTimer: unknown = null
  private watchdog: unknown = null
  private stableTimer: unknown = null
  /** 上次收到的事件 id（`<boot>.<seq>`）：重連時帶上，伺服器補送錯過的 */
  lastEventId: string | null = null
  /** 被同一個人更新的分頁取代（`bye{replaced}`）：等分頁回到前景才重連 */
  replaced = false

  constructor(options: RealtimeClientOptions) {
    this.o = options
    this.t = options.timers ?? realTimers
    this.random = options.random ?? Math.random
  }

  get state(): RealtimeStatus {
    return this.status
  }

  start(): void {
    if (this.running) return
    this.running = true
    this.paused = false
    this.connect()
  }

  /** 登出、離開：關掉，不再重連 */
  stop(): void {
    this.running = false
    this.paused = false
    this.closeStream()
    this.clearRetry()
    this.setStatus("off")
  }

  /** 分頁在背景太久：先關掉（保留 `lastEventId`，回來時補送） */
  pause(): void {
    if (!this.running || this.paused) return
    this.paused = true
    if (this.ctrl) this.gap = true
    this.closeStream()
    this.clearRetry()
    this.setStatus("paused")
  }

  /** 分頁回到前景、取得焦點：暫停中就重連 */
  resume(): void {
    if (!this.running || !this.paused) return
    this.paused = false
    this.replaced = false
    if (this.t.now() < this.holdUntil) {
      this.setStatus("down")
      this.retryAt(this.holdUntil - this.t.now())
      return
    }
    this.attempt = 0
    this.connect()
  }

  /**
   * 網路恢復（`online`）、分頁回到前景：在等重試的話現在就連（伺服器說要等的不算）；
   * 連著但已經超過 1.5 個心跳沒有任何資料（電腦睡過一覺，連線其實已經斷了）就現在重連，不等看門狗
   */
  kick(): void {
    if (!this.running || this.paused) return
    if (this.ctrl) {
      if (this.status === "open" && this.t.now() - this.lastByteAt > this.heartbeatMs * 1.5) this.ctrl.abort()
      return
    }
    if (this.t.now() < this.holdUntil) return
    this.attempt = 0
    this.connect()
  }

  // ── 連線 ───────────────────────────────────────────────
  private connect(): void {
    this.clearRetry()
    this.closeStream()
    const ctrl = new AbortController()
    this.ctrl = ctrl
    this.setStatus("connecting")
    this.arm(ctrl, CONNECT_TIMEOUT_MS)
    void this.run(ctrl)
  }

  private async run(ctrl: AbortController): Promise<void> {
    let res: Response
    try {
      res = await this.o.open(this.lastEventId, ctrl.signal)
    } catch {
      if (this.ctrl === ctrl) this.ended(ctrl)
      return
    }
    if (this.ctrl !== ctrl) {
      void res.body?.cancel().catch(() => undefined)
      return
    }
    if (!res.ok) {
      await this.refused(res, ctrl)
      return
    }
    if (!res.body) {
      this.ended(ctrl)
      return
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    const feed = createSseReader({ onMessage: (m) => this.message(m, ctrl) })
    try {
      for (;;) {
        const { done, value } = await reader.read()
        if (done || this.ctrl !== ctrl) break
        this.lastByteAt = this.t.now()
        this.arm(ctrl, this.heartbeatMs * 2.5)
        feed(decoder.decode(value, { stream: true }))
        if (this.ctrl !== ctrl) break
      }
    } catch {
      // 中斷（暫停、登出、心跳逾時）或網路斷了
    } finally {
      void reader.cancel().catch(() => undefined)
    }
    if (this.ctrl === ctrl) this.ended(ctrl)
  }

  private message(m: SseMessage, ctrl: AbortController): void {
    if (this.ctrl !== ctrl) return
    if (m.id) this.lastEventId = m.id
    let data: Record<string, unknown> = {}
    try {
      const parsed: unknown = JSON.parse(m.data)
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) data = parsed as Record<string, unknown>
    } catch {
      return
    }
    switch (m.event) {
      case "hello":
        this.hello(data)
        return
      case "resync":
        this.o.onResync()
        return
      case "bye":
        this.bye(String(data.reason ?? ""))
        return
      case "":
      case "message":
        return
      default:
        this.o.onEvent({ topic: m.event, data })
    }
  }

  private hello(data: Record<string, unknown>): void {
    const hb = Number(data.heartbeat)
    this.heartbeatMs = (Number.isFinite(hb) && hb > 0 ? hb : DEFAULT_HEARTBEAT_S) * 1000
    const replay: ReplayMode = data.replay === "replayed" || data.replay === "resync" ? data.replay : "none"
    const hadGap = this.gap
    this.gap = false
    this.setStatus("open")
    this.t.clearTimeout(this.stableTimer)
    this.stableTimer = this.t.setTimeout(() => {
      this.attempt = 0
    }, STABLE_MS)
    this.o.onOpen?.({ boot: String(data.boot ?? ""), replay })
    // 伺服器補不上（換了一台、太久了），或第一次連上之前已經斷過一陣子（沒有 id 可以補）：全部重新讀
    if (replay === "resync" || (replay === "none" && hadGap)) this.o.onResync()
  }

  private bye(reason: string): void {
    this.closeStream()
    this.gap = true
    if (reason === "replaced") {
      // 同一個人開了第 7 個分頁，這個最舊的被關掉：等使用者回到這個分頁再連
      this.replaced = true
      this.paused = true
      this.setStatus("paused")
      return
    }
    if (reason === "unauthorized") {
      // 這條連線的 session 沒了：登出、過期，或同一個瀏覽器重新登入（cookie 已經換成新的）。再連一次就知道：
      // 連得上照常（錯過的會補上），回 401 才停下來並通知（refused）
      this.setStatus("down")
      this.retryAt(UNAUTHORIZED_RECHECK_MS + this.random() * 1000)
      return
    }
    // rotate（定期換一條，或伺服器要關了）：0–1 秒內帶 last 重連，錯過的會補送
    this.setStatus("down")
    this.retryAt(this.random() * 1000)
  }

  private async refused(res: Response, ctrl: AbortController): Promise<void> {
    // 429／503 的回應內容（`error.code`、`error.retry_after_seconds`）：跨網域時瀏覽器不一定讓程式讀 `Retry-After`
    let err: Awaited<ReturnType<typeof errorOf>> = null
    if (res.status === 429 || res.status === 503) err = await errorOf(res)
    else void res.body?.cancel().catch(() => undefined)
    if (this.ctrl !== ctrl) return // 讀的時候已經停止或暫停
    this.ctrl = null
    this.t.clearTimeout(this.watchdog)
    this.gap = true
    if (res.status === 401) {
      this.hold(HOLD_MS)
      this.o.onUnauthorized?.()
    } else if (res.status === 403 || res.status === 404) {
      // 403：這個網站不被允許；404：還沒有即時更新的後端。先停 10 分鐘（期間 controller 定時重新讀）
      this.hold(HOLD_MS)
    } else if (res.status === 429 || res.status === 503) {
      // 伺服器關掉了即時更新：停 10 分鐘（期間 controller 定時重新讀）；其他照伺服器說的等
      const after = err?.code === "realtime_off" ? HOLD_MS : (retryAfterMs(res.headers.get("Retry-After")) ?? err?.retryAfterMs ?? 30_000)
      this.hold(after + this.random() * 1000)
    } else {
      this.setStatus("down")
      this.backoff()
    }
  }

  /** 串流意外結束（網路斷了、伺服器重啟、心跳逾時）：退避重連 */
  private ended(ctrl: AbortController): void {
    if (this.ctrl === ctrl) this.ctrl = null
    this.t.clearTimeout(this.watchdog)
    this.t.clearTimeout(this.stableTimer)
    if (!this.running || this.paused) return
    this.gap = true
    this.setStatus("down")
    this.backoff()
  }

  private hold(ms: number): void {
    this.holdUntil = this.t.now() + ms
    this.setStatus("down")
    this.retryAt(ms)
  }

  private backoff(): void {
    // 上限：0–3 秒起（部署時大家的重連分散開），之後加倍到 30 秒
    const cap = Math.min(BACKOFF_MAX_MS, Math.max(RECONNECT_SPREAD_MS, BACKOFF_BASE_MS * 2 ** this.attempt))
    this.attempt += 1
    // 完全隨機（0–上限），至少 250 毫秒
    this.retryAt(Math.max(250, this.random() * cap))
  }

  private retryAt(ms: number): void {
    this.clearRetry()
    if (!this.running) return
    this.retryTimer = this.t.setTimeout(() => {
      this.retryTimer = null
      if (this.running && !this.paused) this.connect()
    }, ms)
  }

  private clearRetry(): void {
    if (this.retryTimer !== null) this.t.clearTimeout(this.retryTimer)
    this.retryTimer = null
  }

  /** 看門狗：這麼久沒有任何資料（連心跳也沒有）就中斷，`run` 收到中斷後退避重連 */
  private arm(ctrl: AbortController, ms: number): void {
    this.t.clearTimeout(this.watchdog)
    this.watchdog = this.t.setTimeout(() => {
      if (this.ctrl === ctrl) ctrl.abort()
    }, ms)
  }

  private closeStream(): void {
    const ctrl = this.ctrl
    this.ctrl = null
    this.t.clearTimeout(this.watchdog)
    this.t.clearTimeout(this.stableTimer)
    ctrl?.abort()
  }

  private setStatus(s: RealtimeStatus): void {
    if (this.status === s) return
    this.status = s
    this.o.onStatus(s)
  }
}

/** 錯誤回應的 `error.code` 與 `error.retry_after_seconds`（讀不到就是 null） */
async function errorOf(res: Response): Promise<{ code: string | null; retryAfterMs: number | null } | null> {
  try {
    const body: unknown = await res.json()
    const e = (body as { error?: { code?: unknown; retry_after_seconds?: unknown } } | null)?.error
    if (!e || typeof e !== "object") return null
    const s = typeof e.retry_after_seconds === "number" ? e.retry_after_seconds : Number.NaN
    return { code: typeof e.code === "string" ? e.code : null, retryAfterMs: Number.isFinite(s) && s >= 0 ? s * 1000 : null }
  } catch {
    return null
  }
}

/** `Retry-After`：秒數（HTTP 日期格式不處理） */
function retryAfterMs(v: string | null): number | null {
  if (!v) return null
  const n = Number(v)
  return Number.isFinite(n) && n >= 0 ? n * 1000 : null
}
