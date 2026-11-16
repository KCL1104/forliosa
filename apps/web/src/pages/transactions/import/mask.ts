/**
 * 在瀏覽器裡塗掉對帳單的個資（PDF 的文字層找得到位置的才塗得掉；截圖沒有文字層，整張送出）。
 * 不碰 pdf.js：輸入是已經換算成畫布座標（左上角原點、往下是 y）的文字框，輸出是要塗黑的框與塗過的文字。
 *
 * 找的東西：
 * - 身分證字號／居留證號（英文字母＋1、2、4、8、9 開頭的 9 個數字）；
 * - 「分公司代碼-帳號」的寫法（9A99-0123456）；
 * - 「客戶姓名、姓名、身分證字號、通訊地址、地址、電話、手機、帳號」這些標籤後面的值（到下一個空白段、下一個標籤或行尾）。
 * 一行裡的字由好幾個文字框拼起來；找到的那一段落在哪幾個框、框裡的第幾個字，就塗那一小段（橫寫的字照字數比例切）。
 */

export interface TextBox {
  str: string
  /** 畫布座標：左上角、寬、高（px） */
  x: number
  y: number
  w: number
  h: number
  /** 字是橫著寫的（直書或旋轉過的頁面整個框都塗，不照字數切） */
  horizontal?: boolean
}

export interface Rect {
  x: number
  y: number
  w: number
  h: number
}

export interface MaskResult {
  /** 要塗黑的框（已經往外多留一點） */
  rects: Rect[]
  /** 塗過的文字層（一行一行；個資換成「〔已遮蔽〕」） */
  text: string
  /** 塗掉幾處 */
  masked: number
}

export const MASK_TOKEN = "〔已遮蔽〕"

const ID_RE = /(?<![A-Za-z0-9])[A-Z][12489]\d{8}(?!\d)/g
const ACCOUNT_RE = /(?<![\w-])[0-9A-Z]{4}-\d{6,8}(?![\w-])/g
/** 冒號可以省略的標籤（標籤本身夠明確） */
const STRONG_LABELS = ["客戶姓名", "身分證字號", "身分證號", "通訊地址", "聯絡地址", "戶籍地址"]
/** 一定要接冒號的標籤（「電話」「帳號」也可能是表頭） */
const LABELS = ["姓名", "地址", "電話", "手機", "帳號"]
const LABEL_RE = new RegExp(
  `(?:(${STRONG_LABELS.join("|")})(?:\\s*[：:]\\s*|\\s+)|(${LABELS.join("|")})\\s*[：:]\\s*)`,
  "g",
)
/** 值到這裡為止：兩個以上的空白、全形空白、tab */
const VALUE_END = /\s{2,}|\u3000|\t/

interface Line {
  items: TextBox[]
  cy: number
  h: number
}

/** 照垂直位置分行（同一行的字中線差不到半個字高），行裡從左到右 */
function groupLines(items: TextBox[]): Line[] {
  const sorted = items.filter((i) => i.str.length > 0).sort((a, b) => a.y + a.h / 2 - (b.y + b.h / 2) || a.x - b.x)
  const lines: Line[] = []
  for (const it of sorted) {
    const cy = it.y + it.h / 2
    const line = lines.at(-1)
    if (line && Math.abs(cy - line.cy) <= Math.max(2, Math.min(it.h, line.h) / 2)) {
      line.items.push(it)
      line.cy = (line.cy * (line.items.length - 1) + cy) / line.items.length
      line.h = Math.max(line.h, it.h)
    } else {
      lines.push({ items: [it], cy, h: it.h })
    }
  }
  for (const l of lines) l.items.sort((a, b) => a.x - b.x)
  return lines
}

/** 一行的文字：框和框之間隔得開（超過四分之一個字高）就補兩個空白（等於分隔），緊貼就直接接上 */
function lineText(line: Line): { text: string; spans: { item: TextBox; start: number; end: number }[] } {
  let text = ""
  const spans: { item: TextBox; start: number; end: number }[] = []
  let prev: TextBox | null = null
  for (const it of line.items) {
    if (prev) {
      const gap = it.x - (prev.x + prev.w)
      if (gap > Math.max(prev.h, it.h) * 0.25 && !/\s$/.test(text) && !/^\s/.test(it.str)) text += "  "
    }
    const start = text.length
    text += it.str
    spans.push({ item: it, start, end: text.length })
    prev = it
  }
  return { text, spans }
}

/** 一行裡要塗的範圍 [start, end) */
export function findSensitiveRanges(text: string): [number, number][] {
  const out: [number, number][] = []
  for (const re of [ID_RE, ACCOUNT_RE]) {
    re.lastIndex = 0
    for (let m = re.exec(text); m; m = re.exec(text)) out.push([m.index, m.index + m[0].length])
  }
  LABEL_RE.lastIndex = 0
  const labels: { at: number; valueStart: number }[] = []
  for (let m = LABEL_RE.exec(text); m; m = LABEL_RE.exec(text)) labels.push({ at: m.index, valueStart: m.index + m[0].length })
  labels.forEach((l, i) => {
    const nextLabel = labels[i + 1]?.at ?? text.length
    // 標籤和值分在兩個隔開的框時，中間補的空白不算值的結尾
    const lead = /^\s*/.exec(text.slice(l.valueStart, nextLabel))![0].length
    const start = l.valueStart + lead
    const rest = text.slice(start, nextLabel)
    const stop = rest.search(VALUE_END)
    const value = (stop >= 0 ? rest.slice(0, stop) : rest).replace(/\s+$/, "")
    if (value) out.push([start, start + value.length])
  })
  // 合併重疊的範圍
  out.sort((a, b) => a[0] - b[0])
  const merged: [number, number][] = []
  for (const r of out) {
    const last = merged.at(-1)
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1])
    else merged.push([r[0], r[1]])
  }
  return merged
}

export function maskTextBoxes(items: TextBox[]): MaskResult {
  const rects: Rect[] = []
  const lines: string[] = []
  let masked = 0
  for (const line of groupLines(items)) {
    const { text, spans } = lineText(line)
    const ranges = findSensitiveRanges(text)
    masked += ranges.length
    let out = ""
    let cursor = 0
    for (const [s, e] of ranges) {
      out += text.slice(cursor, s) + MASK_TOKEN
      cursor = e
      for (const sp of spans) {
        if (sp.end <= s || sp.start >= e) continue
        const it = sp.item
        const pad = Math.max(1.5, it.h * 0.15)
        const len = Math.max(it.str.length, 1)
        if (it.horizontal === false) {
          rects.push({ x: it.x - pad, y: it.y - pad, w: it.w + pad * 2, h: it.h + pad * 2 })
          continue
        }
        const a = (Math.max(s, sp.start) - sp.start) / len
        const b = (Math.min(e, sp.end) - sp.start) / len
        rects.push({ x: it.x + it.w * a - pad, y: it.y - pad, w: it.w * (b - a) + pad * 2, h: it.h + pad * 2 })
      }
    }
    out += text.slice(cursor)
    lines.push(out)
  }
  return { rects, text: lines.join("\n"), masked }
}
