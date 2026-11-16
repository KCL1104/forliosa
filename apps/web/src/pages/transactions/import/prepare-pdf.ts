import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist"
import type { TextItem } from "pdfjs-dist/types/src/display/api"
import type { ImportPage } from "@/api/types"
import { maskTextBoxes, type TextBox } from "./mask"
import { blobToBase64, canvasToJpeg, MAX_EDGE } from "./prepare-image"

/**
 * PDF 對帳單在瀏覽器裡處理（產品負責人 2026-11-16：密碼和原始檔都不離開這台裝置）：
 * 用 pdf.js 打開（有密碼就用使用者輸入的密碼解開）→ 每一頁畫成約 150 dpi 的圖 → 依文字層的位置塗掉個資 → 存成 JPEG，
 * 另外附上塗過的文字層。送出去的只有這些圖和字。
 *
 * pdf.js 只在這個畫面載入（動態 import）。worker 是 Vite 打包出來的一個檔案；
 * 中文字型的 CMap、標準字型與解碼用的 wasm 也是打包時複製的檔案，用到才下載（`import.meta.glob` 不預先載入）。
 * 用 pdf.js 的 legacy 版：一般版用到很新的 JavaScript（`Promise.try`、`Map.getOrInsertComputed`、`Math.sumPrecise`），
 * iOS 18.2 以前的 Safari 會打不開；legacy 版多約 20 KB（gzip）。
 */

const DPI = 150
const MAX_TEXT = 20_000

export class PdfPasswordError extends Error {
  constructor(readonly reason: "need" | "incorrect") {
    super(reason === "need" ? "需要密碼" : "密碼不對")
    this.name = "PdfPasswordError"
  }
}

export class PdfOpenError extends Error {
  constructor() {
    super("這個 PDF 打不開")
    this.name = "PdfOpenError"
  }
}

type PdfJs = typeof import("pdfjs-dist/legacy/build/pdf.mjs")
let loading: Promise<PdfJs> | null = null

/** 載入 pdf.js（只有第一次真的下載；之後共用同一份） */
export function loadPdfjs(): Promise<PdfJs> {
  loading ??= Promise.all([import("pdfjs-dist/legacy/build/pdf.mjs"), import("pdfjs-dist/legacy/build/pdf.worker.min.mjs?url")]).then(([pdfjs, worker]) => {
    pdfjs.GlobalWorkerOptions.workerSrc = worker.default
    return pdfjs
  })
  // 載入失敗（網路斷了）時下次重新來
  loading.catch(() => {
    loading = null
  })
  return loading
}

/** pdf.js 要的 CMap、標準字型、wasm：打包成獨立的檔案，用到哪一個才抓哪一個 */
const ASSETS = import.meta.glob<string>(
  ["/node_modules/pdfjs-dist/cmaps/*.bcmap", "/node_modules/pdfjs-dist/standard_fonts/*.{pfb,ttf}", "/node_modules/pdfjs-dist/wasm/*.{wasm,js}"],
  { query: "?url", import: "default" },
)
const ASSET_DIRS: Record<string, string> = { cMapUrl: "cmaps", standardFontDataUrl: "standard_fonts", wasmUrl: "wasm" }

/** pdf.js 的 BinaryDataFactory：照檔名找到打包後的網址再抓（不用把整個資料夾放在 public/） */
class BundledBinaryDataFactory {
  async fetch({ kind, filename }: { kind: string; filename: string }): Promise<Uint8Array> {
    const load = ASSETS[`/node_modules/pdfjs-dist/${ASSET_DIRS[kind] ?? ""}/${filename}`]
    if (!load) throw new Error(`pdf.js 的資料檔不存在：${kind} ${filename}`)
    const res = await fetch(await load())
    if (!res.ok) throw new Error(`pdf.js 的資料檔讀不到：${filename}`)
    return new Uint8Array(await res.arrayBuffer())
  }
}

/**
 * 打開 PDF：有密碼而且沒給（或給錯）時丟 `PdfPasswordError`，壞掉的檔案丟 `PdfOpenError`。
 * 每次都從檔案重新讀一份位元組（pdf.js 會把資料交給 worker，原本的那份就不能再用）。
 */
export async function openPdf(file: Blob, password?: string): Promise<PDFDocumentProxy> {
  const pdfjs = await loadPdfjs()
  const data = new Uint8Array(await file.arrayBuffer())
  const task = pdfjs.getDocument({
    data,
    password: password || undefined,
    BinaryDataFactory: BundledBinaryDataFactory,
    cMapUrl: "cmaps/",
    standardFontDataUrl: "standard_fonts/",
    wasmUrl: "wasm/",
    useWorkerFetch: false,
    // 只畫圖、讀文字：不需要 PDF 裡的 XFA 表單
    enableXfa: false,
  })
  try {
    return await task.promise
  } catch (e) {
    void task.destroy()
    const err = e as { name?: string; code?: number }
    if (err?.name === "PasswordException") {
      throw new PdfPasswordError(err.code === pdfjs.PasswordResponses.INCORRECT_PASSWORD ? "incorrect" : "need")
    }
    throw new PdfOpenError()
  }
}

export interface PreparedPdf {
  pages: ImportPage[]
  /** 塗掉幾處個資 */
  masked: number
  /** 沒有文字層的頁數（掃描的 PDF：塗不了，整頁送出） */
  scannedPages: number
}

export const isTextItem = (i: unknown): i is TextItem => typeof (i as TextItem).str === "string" && Array.isArray((i as TextItem).transform)

/** 文字層的一個框換成畫布座標（左上角原點） */
export function toBox(item: TextItem, page: { viewport: Pick<ReturnType<PDFPageProxy["getViewport"]>, "convertToViewportPoint"> }): TextBox | null {
  const [a, b, c, d, e, f] = item.transform as number[]
  const runLen = Math.hypot(a!, b!) || 1
  const fontH = Math.hypot(c!, d!) || Math.abs(item.height) || 1
  const ux = a! / runLen
  const uy = b! / runLen
  const vx = c! / fontH
  const vy = d! / fontH
  const w = item.width
  // 字框：基線往下留一點（descent），往上一個字高
  const corners = [
    [e! - vx * fontH * 0.25, f! - vy * fontH * 0.25],
    [e! + ux * w - vx * fontH * 0.25, f! + uy * w - vy * fontH * 0.25],
    [e! + vx * fontH, f! + vy * fontH],
    [e! + ux * w + vx * fontH, f! + uy * w + vy * fontH],
  ].map(([x, y]) => page.viewport.convertToViewportPoint(x!, y!) as [number, number])
  const xs = corners.map((p) => p[0])
  const ys = corners.map((p) => p[1])
  const x = Math.min(...xs)
  const y = Math.min(...ys)
  const bw = Math.max(...xs) - x
  const bh = Math.max(...ys) - y
  if (!Number.isFinite(x) || !Number.isFinite(y) || bw <= 0 || bh <= 0) return null
  // 畫布上還是橫的（文字方向沒有轉、頁面也沒有轉）才照字數比例切，否則整個框塗掉
  const [p0, p1] = corners
  const horizontal = Math.abs(p1![1] - p0![1]) < 0.5 && p1![0] > p0![0]
  return { str: item.str, x, y, w: bw, h: bh, horizontal }
}

const abortError = () => new DOMException("已取消", "AbortError")

/** 每一頁畫成圖、塗掉個資、存成 JPEG（最多 `maxPages` 頁） */
export async function preparePdf(doc: PDFDocumentProxy, opts: { signal?: AbortSignal; maxPages?: number } = {}): Promise<PreparedPdf> {
  const pdfjs = await loadPdfjs()
  const pages: ImportPage[] = []
  let masked = 0
  let scannedPages = 0
  const count = Math.min(doc.numPages, opts.maxPages ?? doc.numPages)
  for (let n = 1; n <= count; n++) {
    if (opts.signal?.aborted) throw abortError()
    const page = await doc.getPage(n)
    try {
      const base = page.getViewport({ scale: 1 })
      let scale = DPI / 72
      const long = Math.max(base.width, base.height) * scale
      if (long > MAX_EDGE) scale *= MAX_EDGE / long
      const viewport = page.getViewport({ scale })
      const canvas = document.createElement("canvas")
      canvas.width = Math.ceil(viewport.width)
      canvas.height = Math.ceil(viewport.height)
      await page.render({ canvas, viewport, annotationMode: pdfjs.AnnotationMode.DISABLE, background: "#ffffff" }).promise
      const content = await page.getTextContent()
      const boxes = content.items.filter(isTextItem).flatMap((i) => toBox(i, { viewport }) ?? [])
      if (!boxes.some((b) => b.str.trim())) scannedPages++
      const result = maskTextBoxes(boxes)
      masked += result.masked
      const ctx = canvas.getContext("2d")!
      ctx.fillStyle = "#000"
      for (const r of result.rects) ctx.fillRect(r.x, r.y, r.w, r.h)
      const blob = await canvasToJpeg(canvas)
      const text = result.text.trim()
      pages.push({ media_type: "image/jpeg", data: await blobToBase64(blob), ...(text ? { text: text.slice(0, MAX_TEXT) } : {}) })
      canvas.width = 0
      canvas.height = 0
    } finally {
      page.cleanup()
    }
  }
  return { pages, masked, scannedPages }
}
