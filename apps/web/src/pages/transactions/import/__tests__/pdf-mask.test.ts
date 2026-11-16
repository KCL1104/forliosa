// @vitest-environment node
import { getDocument, PasswordResponses } from "pdfjs-dist/legacy/build/pdf.mjs"
import { describe, expect, it } from "vitest"
import { maskTextBoxes } from "../mask"
import { isTextItem, toBox } from "../prepare-pdf"

/**
 * 用真的 pdf.js 打開合成的月對帳單（scripts/fixtures/statement-locked.pdf：假的姓名、身分證字號、帳號，
 * 密碼是假的身分證字號 A123456789），確認密碼的錯誤碼和塗黑：文字層換算成畫布座標之後，個資都找得到、交易列一個字都不動。
 * Node 裡 pdf.js 不畫圖（沒有 canvas），只讀文字層——瀏覽器裡的畫圖與塗黑由 smoke 跑一次。和畫面一樣用 legacy 版。
 */
const FIXTURE = new URL("../../../../../scripts/fixtures/statement-locked.pdf", import.meta.url)
// 前端的 tsconfig 沒有 Node 的型別（不要讓 Node 的全域型別混進畫面的程式）：只在這裡動態載入 fs
const NODE_FS = "node:fs"
const readFixture = async () => {
  const fs = (await import(/* @vite-ignore */ NODE_FS)) as { readFileSync: (p: URL) => Uint8Array }
  return new Uint8Array(fs.readFileSync(FIXTURE))
}
const open = async (password?: string) => getDocument({ data: await readFixture(), password, verbosity: 0 }).promise

describe("pdf.js：有密碼的 PDF 與文字層的塗黑", () => {
  it("沒給密碼是 NEED_PASSWORD、給錯是 INCORRECT_PASSWORD（畫面上的「密碼不對」）", async () => {
    await expect(open()).rejects.toMatchObject({ name: "PasswordException", code: PasswordResponses.NEED_PASSWORD })
    await expect(open("A000000000")).rejects.toMatchObject({ name: "PasswordException", code: PasswordResponses.INCORRECT_PASSWORD })
  })

  it("密碼對了：每一頁的姓名、身分證字號、帳號、地址、電話都塗掉，交易列照原樣", async () => {
    const doc = await open("A123456789")
    try {
      expect(doc.numPages).toBe(2)
      for (let n = 1; n <= doc.numPages; n++) {
        const page = await doc.getPage(n)
        const viewport = page.getViewport({ scale: 150 / 72 })
        const content = await page.getTextContent()
        const boxes = content.items.filter(isTextItem).flatMap((i) => toBox(i, { viewport }) ?? [])
        expect(boxes.length).toBeGreaterThan(50)
        // 橫書的頁面：每個框都照字數比例切
        expect(boxes.every((b) => b.horizontal)).toBe(true)
        const res = maskTextBoxes(boxes)
        for (const pii of ["王小明", "A123456789", "9A99-0123456", "範例路", "02-0000-0000"]) expect(res.text).not.toContain(pii)
        expect(res.masked).toBeGreaterThanOrEqual(5)
        // 塗黑的框在頁首（頁面上方 20% 以內），交易表格沒有被塗到
        expect(res.rects.every((r) => r.y < viewport.height * 0.2)).toBe(true)
        expect(res.text).toMatch(/長榮|鴻海|聯發科/)
        expect(res.text).toMatch(/2026\/10\/\d\d/)
        page.cleanup()
      }
    } finally {
      await doc.loadingTask.destroy()
    }
  })
})
