/**
 * AI 回答文字的兩個顯示規則（純函式，方便測試）：
 * 1. 免責聲明由介面固定顯示（`done.disclaimer`，沒有時用常數）。模型自己在最後一行寫了同樣的話時，從文字裡拿掉，
 *    避免畫面上出現兩次；同一行裡的資料時間（「資料至 11/12 13:30」）保留。
 * 2. 「無來源」：後端的 `grounding` 事件列出像事實陳述、卻沒有附來源的段落，切成片段讓畫面在段落後面加上安靜的標記。
 */

import { DISCLAIMER as DISCLAIMERS } from "@/lib/disclaimer"

/** 與後端 `done.disclaimer`／`/ai/usage.disclaimer` 相同的固定文字（後端沒送時用；字在 `lib/disclaimer.ts`） */
export const DISCLAIMER = DISCLAIMERS.ai

/** 後端 AI 無法使用（503 `ai_unavailable`：沒有金鑰、所有金鑰停用或額度用完）時的一句話 */
export const AI_UNAVAILABLE = "AI 暫時不能用，晚一點再試。"

/** 「僅供參考，非投資建議。」「AI 分析僅供參考，不構成投資建議」這類句子（可在一行的結尾；以前的固定文字、模型偶爾自己寫的） */
const DISCLAIMER_TAIL = /[，,。．\s]*(?:以上)?(?:內容|資訊|分析|回答|AI\s*分析|AI\s*回答)?(?:僅供參考)[，,、\s]*(?:並)?(?:非|不構成|不代表|不是)(?:任何)?投資建議[。．.!！]*\s*$/

export function stripDisclaimer(text: string, disclaimer: string = DISCLAIMER): string {
  const trimmed = text.replace(/\s+$/, "")
  if (!trimmed) return text
  const lines = trimmed.split("\n")
  const last = lines[lines.length - 1]!
  const exact = disclaimer.trim()
  let rest: string | null = null
  if (exact && last.trim() === exact) rest = ""
  else if (exact && last.trim().endsWith(exact)) rest = last.trim().slice(0, -exact.length)
  else if (DISCLAIMER_TAIL.test(last)) rest = last.replace(DISCLAIMER_TAIL, "")
  if (rest === null) return text
  rest = rest.replace(/[，,、\s]+$/, "")
  const head = lines.slice(0, -1)
  const out = rest ? [...head, rest] : head
  return out.join("\n").replace(/\s+$/, "")
}

/**
 * 回答是 Markdown（產品負責人 2026-11-15；畫面用 `AiMarkdown` 顯示）。顯示前只做兩件事：
 * - 舊的回答與 mock 用「・」條列：行首的「・」「•」換成 Markdown 的 `- `，一樣畫成清單。
 * - 串流到一半、後半的 `**` 還沒到：最後一個落單的 `**` 先拿掉，不會閃一下星號。
 */
export function cleanAnswer(text: string, { streaming = false }: { streaming?: boolean } = {}): string {
  let out = text.replace(/^([ \t]*)[・•][ \t]*/gm, "$1- ")
  if (streaming && (out.match(/\*\*/g)?.length ?? 0) % 2 === 1) {
    const at = out.lastIndexOf("**")
    out = out.slice(0, at) + out.slice(at + 2)
  }
  return out
}

/**
 * 模型的固定小毛病，顯示前用程式整理（產品負責人 2026-11-15「AI 腔太重」；同樣的題目實測，提示詞改到某個程度之後
 * 再改也降不下來，這幾種是固定的寫法，交給程式最穩）。只做這幾件事，不改內容：
 * - 民國年、「2026年11月12日」寫法 → 「11/12」（不是今年才寫「2025/12/31」）；「今（13）日」「今（13日）」→「13 日」。
 * - 括號裡交代出處的說明（「（公開資訊觀測站）」「（PChome 新聞 11/11、鏡週刊 11/12）」「（資料來源：…）」「（資料來自工具）」）
 *   拿掉：出處由畫面列在回答下方。括號裡只有資料時間的（「（11/13 收盤資料）」）不動。
 * - 照貼回來的出處清單：整行就是某個引用的標題（或「11/10：標題」「媒體，11/10：標題」），或「資料來源：…」開頭的行，拿掉。
 * - 「工具資料顯示」「目前工具沒有顯示」這類說到工具的片語 → 「資料顯示」「目前沒有」。
 * - 清單的點和點之間的空行拿掉（畫成緊湊的清單）；漏出來的 `<cite>` 標籤拿掉。
 */
export interface TidyOptions {
  /** 這則回答的引用標題（`Citation.title`）：整行照貼的標題要拿掉 */
  titles?: (string | null | undefined)[]
  /** 今年（西元）：今年的日期只寫月/日 */
  year?: number
}

const SOURCE_WORDS = /來源|報導|新聞|週刊|時報|日報|觀測站|工具|網站|Yahoo|股市|社群|論壇/
const ROC_DATE = /(?<!\d)(1[01]\d)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日/g
const AD_DATE = /(?<!\d)(20\d\d)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日/g

export function tidyAnswer(text: string, { titles = [], year }: TidyOptions = {}): string {
  const md = (y: number, m: string, d: string) => (year && y !== year ? `${y}/${Number(m)}/${Number(d)}` : `${Number(m)}/${Number(d)}`)
  const known = titles.map((t) => (t ?? "").trim()).filter((t) => t.length >= 8)
  // 先拿掉照貼的出處清單（用原本的字比對標題），再整理寫法
  let out = text
    .replace(/<\/?cite[^>]*>/g, "")
    .split("\n")
    .filter((line) => {
      const t = line.trim().replace(/^(?:[-*+・]|\d+[.)])\s+/, "").replace(/\*\*/g, "")
      if (!t) return true
      if (/^(資料)?來源[：:]/.test(t)) return false
      const bare = t.replace(/^[^，：\n]{1,20}，(?=\d{1,2}\/\d{1,2}：)/, "").replace(/^\d{1,2}\/\d{1,2}：/, "").trim()
      return !known.some((k) => bare === k || (bare.length >= 8 && k.includes(bare)))
    })
    .join("\n")
  out = out
    .replace(ROC_DATE, (_, y: string, m: string, d: string) => md(Number(y) + 1911, m, d))
    .replace(AD_DATE, (_, y: string, m: string, d: string) => md(Number(y), m, d))
    .replace(/今（(\d{1,2})）日|今（(\d{1,2})日）/g, (_, a?: string, b?: string) => `${a ?? b} 日`)
    // 數字日期和後面的漢字之間空一格（「12/21 終止上市」），和其他回答的寫法一樣
    .replace(/(?<![\d/])(\d{1,2}\/\d{1,2})(?=[\u4e00-\u9fff])/g, "$1 ")
    // 括號裡交代出處的說明（全形與半形括號）；前面的空白一起拿掉。Markdown 連結的 `](網址)` 不動
    .replace(/(?<!\])[ \t]*[（(]([^（）()\n]{1,60})[）)]/g, (all, inner: string) => (SOURCE_WORDS.test(inner) && !/^\s*\d/.test(inner) && !/^https?:/.test(inner) ? "" : all))
    // 說到工具的片語：「工具顯示」「估值工具沒有提供」「依工具資料自行計算」
    .replace(/目前(?:我們的)?(?:估值|個股|技術|持股|財報|新聞)?工具(?:沒有|未)(?:提供|顯示|回傳)?/g, "目前沒有")
    .replace(/(?:我們的)?(?:估值|個股|技術|持股|財報|新聞)?工具(?:沒有|未)(?:提供|顯示|回傳)?/g, "目前沒有")
    .replace(/(?:我們的)?(?:估值|個股|技術|持股|財報|新聞)?工具(?:的)?(資料|數字|數據)/g, "$1")
    .replace(/(?:我們的)?(?:估值|個股|技術|持股|財報|新聞)?工具(?:顯示|指出|回傳)/g, "資料顯示")
  // 清單之間的空行；拿掉整行之後多出來的連續空行
  return out.replace(/(^[-*・][ \t][^\n]*)\n[ \t]*\n(?=[-*・][ \t])/gm, "$1\n").replace(/\n{3,}/g, "\n\n").replace(/^\n+/, "")
}

/**
 * 模型談自己的三種固定寫法（2026-11-26 常見問題實測：24 題裡 7 題有），系統提示也禁止，這裡是安全網，只拿掉整句或句首的那一段：
 * - 開頭交代要做什麼的一行：「我先查兩檔的基本資料、估值與財報。」
 * - 說自己不替使用者決定：「我不能替你判斷現在該不該買。」「我不替你選一檔。」「我也不替你挑。」「我可以提供的是…」；
 *   後面接「，但…」或「，這要看…」的，只拿掉前半（「我不能替你決定要不要停損，但目前的數字是：…」→「目前的數字是：…」）。
 * - 結尾的提議與交代資料的句子（寫完才拿，串流中不動，免得字閃掉）：「…可以再問我。」「我可以幫你整理。」
 *   「收盤數字以官方資料為準。」「以上是媒體整理的…」——句子裡有數字的不動。
 */
const PREAMBLE = /^(?:[^。\n]{0,60}[，,])?(?:好的?[，,]\s*)?我(?:先|來|會)?(?:幫你)?(?:查|看|確認|整理|搜尋|比對)[^。\n]{0,40}[。…]?[ \t]*$/
/** 模型把接著問寫成文字（後端也會拿掉並轉成接著問；串流中寫到一半也先藏起來） */
const WRITTEN_CALL = /^[ \t]*`?suggest_follow_ups\b.*$/gm
/** 到第一個逗號或句尾為止；「，但可以把幾個面向講清楚。」這種接著談自己的尾巴一起拿掉 */
const OFFER_TAIL = "(?:我)?(?:可以|能)(?:把|幫你|替你|提供|整理|說明)[^。！？\\n]*[。！？]"
const NOT_DECIDING = new RegExp(`我(?:也|並|都|就|還是|同樣)?(?:不能|無法|沒辦法|不會|不)?(?:替|幫|為)你(?:判斷|決定|選|挑|推薦)[^。！？\\n，,]*(?:[。！？]|[，,](?:但(?:是)?)?(?:${OFFER_TAIL})?)`, "g")
/**
 * 說自己不知道漲跌（產品負責人 2026-11-27：「不要回什麼沒辦法幫你挑、沒辦法知道這種回覆」）：「下週要買什麼，漲跌沒辦法事先知道，」
 * 到那個逗號或句尾為止；同一句前面沒有數字時（多半只是重述問題）連前面一起拿掉，後面的結論留著；前面有數字的那半句留著。
 */
const CANNOT_KNOW = /(^|[。！？\n])([^。！？\n]*?)(?:漲跌|股價|行情|走勢|會不會漲|哪檔會漲)[^。！？\n，,]{0,8}(?:沒辦法|沒有辦法|無法|不能)(?:事先|預先|提前)?(?:知道|預測|預知|預料)[^。！？\n，,]*(?:[。！？]|[，,])/g
const CANNOT_JUDGE = /我(?:不能|無法|沒辦法)(?:判斷|決定|預測|保證|告訴你)[^。！？\n，,]*(?:[。！？]|[，,](?:但(?:是)?)?)/g
/** 「我可以…」到句尾；同一句前面沒有數字時整句拿掉（「你可以到帳本看殖利率，我可以幫你整理。」） */
const OFFER_SENTENCE = /(^|[。！？\n])([^。！？\n]*?)我可以(?:提供|幫你|替你|整理|說明|再)[^。！？\n]*[。！？]/g
const TRAIL_OFFER = /再問我|問我|告訴我|我可以|需要的話|歡迎再|不替你(?:決定|判斷|選)/
/** 對著沒說過的話認錯（「你說的沒錯，我把 11/26 的走勢寫錯了。」「下面的內容請以這個為準。」）：整句拿掉 */
const OWN_CORRECTION = /(^|[。！？\n])[^。！？\n]*(?:你說的(?:沒錯|對)|我(?:把|先前|剛才|前面)[^。！？\n]{0,24}(?:寫錯|說錯|弄錯|搞錯)|請以(?:這個|此|上面|下面)為準)[^。！？\n]*[。！？]/g
/** 句中交代自己接著要做什麼：「…目前沒有，我再找公開資料。」 */
const NARRATION = /(^|[。！？\n])[^。！？\n]*我(?:再|先|來)(?:找|查|看|搜尋|確認)[^。！？\n]*[。！？]/g
const TRAIL_FILLER = /以[^。]{0,12}為準|^以上(?:是|為)?[^。]*(?:整理|統計|資料|數據|數字|報導)|不是 ?Forliosa/
/** 交代資料的結尾句裡的日期，回答別的地方都寫過了才算沒有新資訊 */
const DATES = /\d{1,2}\/\d{1,2}/g

/** 中日韓的字：回答是繁體中文，整行沒有一個中文字、只有英文句子的第一行是模型寫給自己的備註 */
const CJK = /[\u3400-\u9fff\uf900-\ufaff]/
const ENGLISH_NOTE = /[A-Za-z]{2,}[^\n]*\s[A-Za-z]{2,}/

export function dropAiHabits(text: string, { streaming = false }: { streaming?: boolean } = {}): string {
  const lines = text.split("\n")
  const first = lines.findIndex((l) => l.trim())
  const rest = first >= 0 ? lines.slice(first + 1) : []
  // 開頭交代要做什麼的一行；或一行英文的備註（「Per rules, no items means don't write it. Draw chart.」，2026-11-27 實測）——
  // 後面要有中文的回答才拿，整則只有這一行時不動
  if (first >= 0 && PREAMBLE.test(lines[first]!.trim()) && rest.some((l) => l.trim())) lines.splice(first, 1)
  else if (first >= 0 && !CJK.test(lines[first]!) && ENGLISH_NOTE.test(lines[first]!) && rest.some((l) => CJK.test(l))) lines.splice(first, 1)
  let out = lines.join("\n").replace(WRITTEN_CALL, "").replace(/^[ \t]*<br\s*\/?>[ \t]*$/gim, "")
  const narrated = out.replace(OWN_CORRECTION, "$1").replace(NARRATION, "$1")
  out = (narrated.trim() ? narrated : out)
    .replace(CANNOT_KNOW, (m, lead: string, before: string) => {
      if (!/\d/.test(before)) return lead
      // 前面有數字：留到最後一個逗號為止，補上句號（「台積電收 2,145 元，之後的漲跌沒辦法事先知道。」→「台積電收 2,145 元。」）
      const cut = before.lastIndexOf("，") // 只認全形逗號：半形的可能是「2,145」的千分位
      return cut < 0 ? m : `${lead}${before.slice(0, cut)}。`
    })
    .replace(NOT_DECIDING, "")
    .replace(CANNOT_JUDGE, "").replace(OFFER_SENTENCE, (_m, lead: string, before: string) => lead + (/\d/.test(before) ? before.replace(/[，,、\s]+$/, "。") : ""))
  if (!streaming) {
    // 結尾：最後一行從後面往前，拿掉沒有數字的提議或交代資料的句子；整行都拿掉時換上一行
    const rows = out.replace(/\s+$/, "").split("\n")
    while (rows.length) {
      const sentences = rows[rows.length - 1]!.match(/[^。！？]+[。！？]?/g) ?? []
      let keep = sentences.length
      while (keep > 0) {
        const s = sentences[keep - 1]!.trim()
        const elsewhere = [...rows.slice(0, -1), ...sentences.slice(0, keep - 1)].join("\n")
        const datesOnly = /^以上/.test(s) && (s.match(DATES) ?? []).every((d) => elsewhere.includes(d)) && !/\d/.test(s.replace(DATES, ""))
        if ((/\d/.test(s) && !datesOnly) || !(TRAIL_OFFER.test(s) || TRAIL_FILLER.test(s))) break
        keep--
      }
      if (keep === sentences.length) break
      const rest = sentences.slice(0, keep).join("").replace(/\s+$/, "")
      if (rest.replace(/^\s*[-*]\s*/, "").trim()) {
        rows[rows.length - 1] = rest
        break
      }
      rows.pop()
      while (rows.length && !rows[rows.length - 1]!.trim()) rows.pop()
    }
    out = rows.join("\n")
  }
  return out.replace(/\n{3,}/g, "\n\n").replace(/^\n+/, "")
}

/** 顯示用：舊的「・」條列換成 Markdown 清單，再整理固定的小毛病 */
export function displayAnswer(text: string, opts: TidyOptions & { streaming?: boolean } = {}): string {
  return dropAiHabits(tidyAnswer(cleanAnswer(text, { streaming: opts.streaming }), opts), { streaming: opts.streaming })
}

/**
 * 沒有附來源的段落，換成畫面上找得到的樣子：同一套整理，再拿掉 Markdown 的格式記號（畫出來之後看不到的那些）——
 * 行首的清單記號、`**`、`__`、反引號。
 */
export function markNeedle(passage: string, opts: TidyOptions = {}): string {
  return displayAnswer(passage, opts)
    .replace(/^[ \t]*(?:[-*+]|\d+[.)])[ \t]+/gm, "")
    .replace(/\*\*|__|`/g, "")
    .trim()
}

/** 沒有附來源的段落（`grounding` 事件的一項；後端欄位以 text 為主，start／end 是選填的字元位置） */
export interface UngroundedPassage {
  text: string
  reason?: string | null
  start?: number | null
  end?: number | null
}

export interface TextSegment {
  text: string
  /** 這一段後面要加「無來源」標記 */
  ungrounded?: UngroundedPassage
}

/**
 * 把回答切成片段：每個沒有來源的段落成為一段（帶標記），其他文字原樣。
 * 先用 start／end（位置要和 text 對得上），對不上就在文字裡找 text；找不到的段落略過，不硬塞。
 */
export function splitUngrounded(text: string, passages: UngroundedPassage[] | undefined, opts: TidyOptions = {}): TextSegment[] {
  if (!passages?.length || !text) return [{ text }]
  const spans: { start: number; end: number; p: UngroundedPassage }[] = []
  for (const p of passages) {
    // 回答顯示前整理過（`displayAnswer`）：要找的那一段也整理一次才對得上
    const needle = displayAnswer(p.text ?? "", opts).trim()
    if (!needle) continue
    let start = -1
    if (typeof p.start === "number" && typeof p.end === "number" && p.end > p.start && text.slice(p.start, p.end).trim() === needle) {
      start = p.start + text.slice(p.start, p.end).indexOf(needle)
    } else {
      let from = 0
      // 同一句出現多次時取第一個還沒被標過的位置
      for (;;) {
        const at = text.indexOf(needle, from)
        if (at === -1) break
        if (!spans.some((s) => at < s.end && at + needle.length > s.start)) {
          start = at
          break
        }
        from = at + 1
      }
    }
    if (start === -1) continue
    const end = start + needle.length
    if (spans.some((s) => start < s.end && end > s.start)) continue
    spans.push({ start, end, p })
  }
  if (spans.length === 0) return [{ text }]
  spans.sort((a, b) => a.start - b.start)
  const out: TextSegment[] = []
  let cursor = 0
  for (const s of spans) {
    if (s.start > cursor) out.push({ text: text.slice(cursor, s.start) })
    out.push({ text: text.slice(s.start, s.end), ungrounded: s.p })
    cursor = s.end
  }
  if (cursor < text.length) out.push({ text: text.slice(cursor) })
  return out
}

/** `grounding` 事件的資料：容錯解析 `{items: [...]}`、陣列，或單一物件 */
export function parseGrounding(data: unknown): UngroundedPassage[] {
  const raw = Array.isArray(data) ? data : data && typeof data === "object" && Array.isArray((data as { items?: unknown }).items) ? (data as { items: unknown[] }).items : data ? [data] : []
  return raw.flatMap((x): UngroundedPassage[] => {
    if (!x || typeof x !== "object") return []
    const o = x as Record<string, unknown>
    const text = typeof o.text === "string" ? o.text : typeof o.passage === "string" ? o.passage : ""
    if (!text.trim()) return []
    return [{
      text,
      reason: typeof o.reason === "string" ? o.reason : null,
      start: typeof o.start === "number" ? o.start : null,
      end: typeof o.end === "number" ? o.end : null,
    }]
  })
}

/** grounding 的 reason 代碼（後端 `ai/grounding.py`）→ 給人看的話；認不得的代碼不顯示 */
const REASON_TEXT: Record<string, string> = {
  uncited_news_claim: "像新聞敘述，但沒有對到任何引用的來源。",
}

export function groundingReason(reason: string | null | undefined): string {
  const r = (reason ?? "").trim()
  if (!r) return ""
  if (REASON_TEXT[r]) return REASON_TEXT[r]
  return /^[a-z0-9_:-]+$/i.test(r) ? "" : r
}

/**
 * 模型回答的排版片段（`KaiText`）：楷體的墨跡填不滿字框，漢字與全形標點的連續片段要收一點字距；
 * 數字與拉丁字母是 Noto Sans，不收字距；數字和後面的單位（元、股、張、%、倍、億…）連成一段，不在行尾拆開。
 * - `han`：漢字、全形標點、破折號與刪節號
 * - `num`：數字（可帶 ▲▼、正負號、NT$／US$、千分位、小數、日期與時間的 / :）＋可選的單位
 * - `plain`：其他（空白、換行、拉丁字母、半形標點）
 */
export interface KaiRun {
  kind: "han" | "num" | "plain"
  text: string
}

// 長的單位放前面（「個月」先於「月」、「美元」先於「元」）；數字和單位之間最多一個空白（不吃換行）
const UNIT = "(?:個月|小時|分鐘|美元|%|％|元|股|張|倍|億|萬|兆|千|檔|天|月|年|日|週|季|次|筆|名|位|點|成|秒|人|家|則|項|期)"
const NUM = `(?:[▲▼][ \\u00A0]?)?[+\\-−]?(?:NT\\$|US\\$|\\$)?[+\\-−]?\\d[\\d,]*(?:[.:/]\\d+)*(?:[ \\u00A0]?${UNIT})?`
const HAN = "[\\u2E80-\\u9FFF\\uF900-\\uFAFF\\uFE30-\\uFE4F\\uFF00-\\uFFEF\\u2014\\u2025\\u2026\\u2027]+"
const RUN = new RegExp(`(${NUM})|(${HAN})`, "gu")

export function kaiRuns(text: string): KaiRun[] {
  const out: KaiRun[] = []
  const push = (kind: KaiRun["kind"], t: string) => {
    if (!t) return
    const prev = out[out.length - 1]
    // 相鄰的數字各自一段（「1 張」「500 股」中間可以換行）；漢字與其他文字合併
    if (prev && prev.kind === kind && kind !== "num") prev.text += t
    else out.push({ kind, text: t })
  }
  let cursor = 0
  for (const m of text.matchAll(RUN)) {
    const at = m.index ?? 0
    push("plain", text.slice(cursor, at))
    push(m[1] ? "num" : "han", m[0])
    cursor = at + m[0].length
  }
  push("plain", text.slice(cursor))
  return out
}
