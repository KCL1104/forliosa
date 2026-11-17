/**
 * Server-Sent Events 的解析（`text/event-stream`）：餵入任意切段的文字，每收到一個完整的事件（空行結束）就回呼。
 * AI 對話的串流（`ai/remote.ts`）與即時更新（`realtime/client.ts`）共用。
 *
 * - 欄位：`event`、`data`（多行接起來）、`id`、`retry`；`:` 開頭是註解（心跳 `: ping`），交給 `onComment`
 * - 換行：LF、CRLF、CR 都可以；一個 `\r\n` 被切在兩段之間也沒關係
 * - 只有帶 `data` 的區塊才算一個事件（規格如此）；只有 `retry:` 的區塊照樣把 `retry` 交給 `onRetry`
 */
export interface SseMessage {
  /** 沒寫 `event:` 時是空字串（規格的預設 "message" 由使用的人決定要不要接受） */
  event: string
  data: string
  /** 這個區塊的 `id:`（沒有時 undefined） */
  id?: string
}

export interface SseHandlers {
  onMessage: (m: SseMessage) => void
  /** 註解行（`: ping` 是心跳；不含開頭的冒號與一個空白） */
  onComment?: (text: string) => void
  /** `retry:` 欄位（毫秒） */
  onRetry?: (ms: number) => void
}

export function createSseReader(handlers: SseHandlers | ((m: SseMessage) => void)): (chunk: string) => void {
  const h: SseHandlers = typeof handlers === "function" ? { onMessage: handlers } : handlers
  let buffer = ""
  return (chunk: string) => {
    buffer += chunk
    // CRLF / CR → LF；結尾的 \r 可能是被切開的 \r\n 的前半，留到下一段
    const tail = buffer.endsWith("\r") ? "\r" : ""
    buffer = (tail ? buffer.slice(0, -1) : buffer).replace(/\r\n?/g, "\n")
    let cut = buffer.indexOf("\n\n")
    while (cut !== -1) {
      const block = buffer.slice(0, cut)
      buffer = buffer.slice(cut + 2)
      dispatch(block, h)
      cut = buffer.indexOf("\n\n")
    }
    buffer += tail
  }
}

function dispatch(block: string, h: SseHandlers) {
  let event = ""
  let id: string | undefined
  const data: string[] = []
  for (const line of block.split("\n")) {
    if (line === "") continue
    if (line.startsWith(":")) {
      h.onComment?.(line.slice(1).replace(/^ /, ""))
      continue
    }
    const colon = line.indexOf(":")
    const field = colon === -1 ? line : line.slice(0, colon)
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "")
    if (field === "event") event = value
    else if (field === "data") data.push(value)
    else if (field === "id") {
      // 規格：含 NUL 的 id 不算
      if (!value.includes("\0")) id = value
    } else if (field === "retry") {
      if (/^\d+$/.test(value)) h.onRetry?.(Number(value))
    }
  }
  if (data.length > 0) h.onMessage({ event, data: data.join("\n"), ...(id !== undefined ? { id } : {}) })
}
