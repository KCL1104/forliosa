/**
 * 討論串的文字規則（docs/api-contract.md「討論串」的「內文」與「公開暱稱」），和後端 `textsafe.py` 同一套：
 * 表單在送出前先檢查（錯誤就地說明），mock adapter 用同一份規則回 422。伺服器仍然是最後的把關。
 */

/** 換行、Tab、其他控制字元（Cc）與行／段分隔符（Zl、Zp） */
const BREAKING = /[\p{Cc}\p{Zl}\p{Zp}]/u
/** 看不見的格式字元（Cf：雙向控制、零寬空白、BOM…）與落單的代理字元（Cs）；零寬連接符（U+200D，表情組合要用）除外 */
const INVISIBLE = /(?!\u200d)[\p{Cf}\p{Cs}]/u
/** 放得進去、但畫面上什麼都看不到的字元：零寬連接符、韓文填充字、點字空白、組合用連接符、變體選擇符 */
const BLANKS = new Set([0x200d, 0x115f, 0x1160, 0x3164, 0xffa0, 0x2800, 0x034f])
function showsNothing(ch: string): boolean {
  const cp = ch.codePointAt(0) ?? 0
  return BLANKS.has(cp) || (cp >= 0xfe00 && cp <= 0xfe0f) || (cp >= 0xe0100 && cp <= 0xe01ef)
}
const dropBlanks = (text: string) => [...text].filter((ch) => !showsNothing(ch)).join("")

/** 一行文字裡不能有的字元：換行、Tab、控制字元、看不見的格式字元 */
export function hasControl(text: string): boolean {
  return BREAKING.test(text) || INVISIBLE.test(text)
}

/** 多行文字：換行（LF）是唯一允許的控制字元 */
export function textHasControl(text: string): boolean {
  return hasControl(text.replaceAll("\n", ""))
}

/** 多行純文字存起來的樣子：CRLF／CR 轉 LF、去掉行尾空白、連續空行最多 2 個、去掉開頭與結尾的空行 */
export function normalizeText(text: string): string {
  const out: string[] = []
  let blank = 0
  for (const raw of text.replace(/\r\n?/g, "\n").split("\n")) {
    const line = raw.trimEnd()
    blank = line ? 0 : blank + 1
    if (blank <= 2) out.push(line)
  }
  return out.join("\n").replace(/^\n+|\n+$/g, "")
}

/** 讀的人實際看得到的字（去掉空白與看不見的字元） */
export function visible(text: string): string {
  return dropBlanks(text.replace(/\s/gu, ""))
}

/** 一行：控制字元與換行變成空白、看不見的格式字元拿掉、連續空白合成一個 */
export function oneLine(text: string): string {
  return text
    .replace(new RegExp(BREAKING.source, "gu"), " ")
    .replace(new RegExp(INVISIBLE.source, "gu"), "")
    .split(/\s+/u)
    .filter(Boolean)
    .join(" ")
}

/** 字數：以 Unicode 字元（code point）算，和後端的 `len()` 一樣（一個表情不會算成兩個字） */
export function charCount(text: string): number {
  return [...text].length
}

/** 公開暱稱的比對鍵：NFKC＋不分大小寫（全形半形、大小寫是同一個名字），去掉看不見的字元，連續空白視為一個 */
export function nameKey(name: string): string {
  const key = dropBlanks(name.normalize("NFKC"))
  return key.toLowerCase().normalize("NFKC").split(/\s+/u).filter(Boolean).join(" ")
}

/** 公開暱稱不能用的字（不分大小寫與全半形，含這些字也不行） */
export const RESERVED_NAMES = ["forliosa", "官方", "管理員", "站方", "admin", "system"] as const

export const PUBLIC_NAME_RULE = "2 到 20 個字、一行；不能和別人重複，也不能含「官方」「管理員」「站方」這類字。"

/** 公開暱稱哪裡不合規則（給使用者看的一句話）；合規則回 null。唯一性只有伺服器知道（409 public_name_taken） */
export function publicNameProblem(input: string): string | null {
  const name = input.trim()
  const n = charCount(name)
  if (n < 2 || n > 20 || charCount(visible(name)) < 2) return "公開暱稱要 2 到 20 個字。"
  if (hasControl(name)) return "公開暱稱只能有一行，不能有換行或看不見的字元。"
  const key = nameKey(name)
  const squeezed = key.replace(/\s/gu, "")
  const hit = RESERVED_NAMES.find((w) => key.includes(nameKey(w)) || squeezed.includes(nameKey(w)))
  if (hit) return `公開暱稱不能含「${hit}」。`
  return null
}

/** 標題（1–80 字、一行）哪裡不合規則 */
export function titleProblem(input: string, max: number): string | null {
  const title = input.trim()
  if (!visible(title)) return "請寫標題。"
  if (charCount(title) > max) return `標題最多 ${max} 個字，現在 ${charCount(title)} 個字。`
  if (hasControl(title)) return "標題只能有一行，不能有換行或 Tab。"
  return null
}

/** 內文或回覆（1–max 字，可換行）哪裡不合規則；`what` 是「內文」「回覆」「補充說明」 */
export function bodyProblem(input: string, max: number, what: string): string | null {
  const body = normalizeText(input)
  if (!visible(body)) return `請寫${what}。`
  if (charCount(body) > max) return `${what}最多 ${max} 個字，現在 ${charCount(body)} 個字。`
  if (textHasControl(body)) return `${what}裡有 Tab 或看不見的控制字元，請拿掉再送出。`
  return null
}
