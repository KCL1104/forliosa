import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"
import { bodyProblem, charCount, nameKey, normalizeText, publicNameProblem, titleProblem } from "@/lib/discussion-text"
import { linkParts } from "@/lib/linkify"
import { PlainText } from "../PlainText"

afterEach(cleanup)

const links = (text: string) => linkParts(text).flatMap((p) => (p.kind === "link" ? [p.href] : []))

describe("網址變成連結（純函式 linkParts）", () => {
  it("只有 http(s):// 的網址；其他協定與看起來像網址的字都只是字", () => {
    expect(links("看 https://www.twse.com.tw/zh/page.html 的說明")).toEqual(["https://www.twse.com.tw/zh/page.html"])
    expect(links("http://example.com/a?b=1&c=2#d")).toEqual(["http://example.com/a?b=1&c=2#d"])
    for (const text of ["javascript:alert(1)", "JAVASCRIPT://alert(1)", "data:text/html,<script>alert(1)</script>", "vbscript:msgbox(1)", "ftp://example.com/file", "www.example.com", "example.com/path", "mailto:a@example.com", "https://", "http:// 空白"]) {
      expect(links(text), text).toEqual([])
    }
  })
  it("中文句子裡網址後面的標點不算在網址裡；網址裡的中文字照樣算", () => {
    expect(linkParts("我有找到證交所的網站 https://www.twse.com.tw/，但規則看不太懂。")).toEqual([
      { kind: "text", text: "我有找到證交所的網站 " },
      { kind: "link", text: "https://www.twse.com.tw/", href: "https://www.twse.com.tw/" },
      { kind: "text", text: "，但規則看不太懂。" },
    ])
    expect(links("（見 https://example.com/a）")).toEqual(["https://example.com/a"])
    expect(links("網址是 https://example.com/a.")).toEqual(["https://example.com/a"])
    expect(links("(見 https://example.com/a)")).toEqual(["https://example.com/a"])
    expect(links("https://en.wikipedia.org/wiki/Fee_(finance)")).toEqual(["https://en.wikipedia.org/wiki/Fee_(finance)"])
    expect(linkParts("https://zh.wikipedia.org/wiki/台積電 是條目")[0]).toMatchObject({ kind: "link", text: "https://zh.wikipedia.org/wiki/台積電" })
    expect(links("兩個：https://a.example/1 和 https://b.example/2")).toEqual(["https://a.example/1", "https://b.example/2"])
  })
  it("切出來的片段接起來就是原文（沒有字被吃掉或重複）", () => {
    for (const text of ["", "沒有網址", "https://example.com", "前 https://example.com/x, 後", "<b>https://example.com</b>", "a\nhttps://example.com\nb"]) {
      expect(linkParts(text).map((p) => p.text).join("")).toBe(text)
    }
  })
})

describe("使用者的文字（PlainText）：純文字、不產生 HTML", () => {
  it("連結另開新視窗，rel 是 nofollow ugc noopener noreferrer", () => {
    render(<PlainText text={"看這裡 https://www.twse.com.tw/，謝謝"} />)
    const a = screen.getByRole("link")
    expect(a).toHaveAttribute("href", "https://www.twse.com.tw/")
    expect(a).toHaveAttribute("target", "_blank")
    expect(a).toHaveAttribute("rel", "nofollow ugc noopener noreferrer")
    // 看得到的字就是網址本身；另開新視窗只告訴螢幕閱讀器
    expect(a).toHaveTextContent("https://www.twse.com.tw/（另開新視窗）")
  })
  it("HTML、腳本、事件屬性都只是字：畫面上沒有多出任何元素", () => {
    const evil = '<img src=x onerror="alert(1)"><script>alert(2)</script><a href="javascript:alert(3)">點我</a> javascript:alert(4) <iframe src="https://evil.example">'
    const { container } = render(<PlainText text={evil} />)
    expect(container.querySelector("img, script, iframe")).toBeNull()
    // 唯一的連結是 https 網址本身（屬性裡的引號不會被帶進 href）
    const anchors = [...container.querySelectorAll("a")]
    expect(anchors.map((a) => a.getAttribute("href"))).toEqual(["https://evil.example/"])
    expect(container.querySelector("[onerror], [onclick]")).toBeNull()
    expect(container.textContent).toContain('<script>alert(2)</script>')
    expect(container.textContent).toContain('<a href="javascript:alert(3)">點我</a>')
    expect(container.innerHTML).toContain("&lt;script&gt;")
  })
  it("換行保留（pre-wrap），不是 <br> 也不是多個段落", () => {
    const { container } = render(<PlainText text={"第一行\n\n第三行"} />)
    const p = container.querySelector("p")!
    expect(p.className).toMatch(/\bwhitespace-pre-wrap\b/)
    expect(p.textContent).toBe("第一行\n\n第三行")
    expect(container.querySelectorAll("br, p").length).toBe(1)
  })
})

describe("文字規則（和後端同一套，表單在送出前先檢查）", () => {
  it("內文正規化：CRLF 轉 LF、去掉行尾空白、連續空行最多 2 個、去掉頭尾空行", () => {
    expect(normalizeText("\r\n\r\n一  \r\n\n\n\n\n二\r三\n\n")).toBe("一\n\n\n二\n三")
    expect(normalizeText("   ")).toBe("")
  })
  it("標題與內文：空的、太長、有 Tab 或看不見的字元各有一句說明；合規則回 null", () => {
    expect(titleProblem("  ", 80)).toBe("請寫標題。")
    expect(titleProblem("字".repeat(81), 80)).toMatch(/最多 80 個字，現在 81 個字/)
    expect(titleProblem("兩行\n標題", 80)).toMatch(/只能有一行/)
    expect(titleProblem(" 0050 要不要改買 006208？ ", 80)).toBeNull()
    expect(bodyProblem("\n \n", 2000, "回覆")).toBe("請寫回覆。")
    expect(bodyProblem("字".repeat(2001), 2000, "回覆")).toMatch(/回覆最多 2000 個字，現在 2001 個字/)
    expect(bodyProblem("有\tTab", 5000, "內文")).toMatch(/Tab/)
    expect(bodyProblem("第一段\n\n第二段 👍", 5000, "內文")).toBeNull()
    // 一個表情算一個字（和後端的字數算法一樣）
    expect(charCount("👍👍")).toBe(2)
  })
  it("公開暱稱：2–20 字、一行、不能含保留字（不分大小寫與全半形、中間夾空白也算）", () => {
    expect(publicNameProblem("一")).toMatch(/2 到 20 個字/)
    expect(publicNameProblem("字".repeat(21))).toMatch(/2 到 20 個字/)
    expect(publicNameProblem("  ")).toMatch(/2 到 20 個字/)
    expect(publicNameProblem("官方小編")).toBe("公開暱稱不能含「官方」。")
    expect(publicNameProblem("ＡＤＭＩＮ")).toBe("公開暱稱不能含「admin」。")
    expect(publicNameProblem("S y s t e m")).toBe("公開暱稱不能含「system」。")
    expect(publicNameProblem("我是Forliosa粉")).toBe("公開暱稱不能含「forliosa」。")
    expect(publicNameProblem(" 示範小資 ")).toBeNull()
    expect(nameKey("ＡＢＣ  小明")).toBe(nameKey("abc 小明"))
  })
})
