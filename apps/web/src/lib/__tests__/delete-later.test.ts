import { beforeEach, describe, expect, it, vi } from "vitest"

type ToastOptions = { description?: string; duration?: number; action: { label: string; onClick: () => void }; onAutoClose: () => void; onDismiss: () => void }
const toastMock = vi.hoisted(() => {
  let nextId = 0
  const fn = Object.assign(
    vi.fn((_title: string, _options: unknown) => ++nextId),
    { dismiss: vi.fn(), error: vi.fn() },
  )
  return fn
})
vi.mock("sonner", () => ({ toast: toastMock }))

import { deleteLater, UNDO_MS, usePendingDeletes } from "../delete-later"

/**
 * 可以復原的刪除（討論的回覆與主題）：畫面先拿掉 → 通知附「復原」→ 通知結束才送出。
 * 「復原」什麼都不送；頁面先被關掉或藏起來就當下送出（keepalive）；送出失敗放回原位並通知；404 當成已經刪除。
 */
const pending = () => [...usePendingDeletes.getState().keys]
const lastToast = () => toastMock.mock.calls.at(-1) as unknown as [string, ToastOptions]
const settle = () => new Promise((r) => setTimeout(r, 0))
let n = 0
function start(overrides: Partial<Parameters<typeof deleteLater>[0]> = {}) {
  const key = `reply:rep_${++n}`
  const send = vi.fn(() => Promise.resolve())
  const onDeleted = vi.fn()
  deleteLater({ key, title: "已刪除回覆", failed: "回覆沒有刪除，已經放回原位", send, onDeleted, ...overrides })
  return { key, send: (overrides.send as typeof send | undefined) ?? send, onDeleted }
}

beforeEach(() => {
  toastMock.mockClear()
  toastMock.dismiss.mockClear()
  toastMock.error.mockClear()
})

describe("deleteLater", () => {
  it("按下刪除：畫面上立刻拿掉、通知附「復原」，還沒送出任何請求", () => {
    const { key, send } = start()
    expect(pending()).toContain(key)
    expect(send).not.toHaveBeenCalled()
    const [title, options] = lastToast()
    expect(title).toBe("已刪除回覆")
    expect(options.action.label).toBe("復原")
    expect(options.duration).toBe(UNDO_MS)
    options.action.onClick() // 收尾：不留在等待清單裡
  })

  it("復原：放回原位，之後通知結束也不會送出", async () => {
    const { key, send, onDeleted } = start()
    const [, options] = lastToast()
    options.action.onClick()
    expect(pending()).not.toContain(key)
    options.onAutoClose()
    options.onDismiss()
    await settle()
    expect(send).not.toHaveBeenCalled()
    expect(onDeleted).not.toHaveBeenCalled()
  })

  it("通知結束（逾時或滑掉）：送出一次（不是 keepalive）；清單重新讀完之後才不再濾掉", async () => {
    const { key, send, onDeleted } = start()
    const [, options] = lastToast()
    options.onAutoClose()
    options.onDismiss() // 同一則通知的兩個事件都來了也只送一次
    expect(send).toHaveBeenCalledTimes(1)
    expect(send).toHaveBeenCalledWith({ keepalive: false })
    expect(pending()).toContain(key)
    await settle()
    expect(onDeleted).toHaveBeenCalledTimes(1)
    expect(pending()).not.toContain(key)
    expect(toastMock.error).not.toHaveBeenCalled()
  })

  it("頁面被關掉（pagehide）：還在等的刪除當下送出（keepalive），通知收掉", async () => {
    const { send } = start()
    window.dispatchEvent(new Event("pagehide"))
    expect(send).toHaveBeenCalledWith({ keepalive: true })
    expect(toastMock.dismiss).toHaveBeenCalledTimes(1)
    await settle()
    // 已經送出：之後通知的事件不會再送一次
    lastToast()[1].onAutoClose()
    expect(send).toHaveBeenCalledTimes(1)
  })

  it("頁面被藏起來（切到別的分頁、鎖螢幕）：也是當下送出", async () => {
    const { send } = start()
    const original = Object.getOwnPropertyDescriptor(Document.prototype, "visibilityState")!
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" })
    try {
      document.dispatchEvent(new Event("visibilitychange"))
    } finally {
      Object.defineProperty(document, "visibilityState", original)
    }
    expect(send).toHaveBeenCalledWith({ keepalive: true })
    await settle()
  })

  it("送出失敗：放回原位，通知說沒有刪除", async () => {
    const send = vi.fn(() => Promise.reject(new Error("網路中斷")))
    const { key, onDeleted } = start({ send })
    lastToast()[1].onAutoClose()
    await settle()
    expect(pending()).not.toContain(key)
    expect(onDeleted).not.toHaveBeenCalled()
    expect(toastMock.error).toHaveBeenCalledWith("回覆沒有刪除，已經放回原位", { description: "網路中斷" })
  })

  it("伺服器回 404（別的地方已經刪了）：當成已經刪除，不說失敗", async () => {
    const send = vi.fn(() => Promise.reject(Object.assign(new Error("找不到資源"), { status: 404 })))
    const { key, onDeleted } = start({ send })
    lastToast()[1].onAutoClose()
    await settle()
    expect(onDeleted).toHaveBeenCalledTimes(1)
    expect(pending()).not.toContain(key)
    expect(toastMock.error).not.toHaveBeenCalled()
  })

  it("同一則連按兩次刪除：只有一則通知、只送一次", async () => {
    const send = vi.fn(() => Promise.resolve())
    deleteLater({ key: "topic:top_dup", title: "已刪除主題", failed: "主題沒有刪除，已經放回原位", send })
    deleteLater({ key: "topic:top_dup", title: "已刪除主題", failed: "主題沒有刪除，已經放回原位", send })
    expect(toastMock).toHaveBeenCalledTimes(1)
    lastToast()[1].onAutoClose()
    await settle()
    expect(send).toHaveBeenCalledTimes(1)
  })
})
