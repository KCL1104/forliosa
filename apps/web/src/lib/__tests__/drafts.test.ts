import { beforeEach, describe, expect, it } from "vitest"
import { clearDraft, hasTopicContent, newTopicDraftKey, parseNewTopicDraft, parseReplyDraft, readDraft, replyDraftKey, writeDraft, type NewTopicDraft } from "../drafts"

/**
 * 還沒送出的字（回覆、開新主題）：存在這個分頁的 sessionStorage，離開再回來還在，送出成功才清掉。
 * 一個主題一份回覆草稿；鍵含使用者 id（同一個分頁換人登入看不到上一個人的草稿）；存不了就當作沒有草稿。
 */
beforeEach(() => window.sessionStorage.clear())

describe("回覆的草稿", () => {
  it("存、讀、清：一段字；只有空白不算草稿", () => {
    const key = replyDraftKey("usr_a", "top_1")
    expect(readDraft(key, parseReplyDraft)).toBeNull()
    writeDraft(key, "寫到一半")
    expect(readDraft(key, parseReplyDraft)).toBe("寫到一半")
    writeDraft(key, parseReplyDraft("   \n"))
    expect(window.sessionStorage.getItem(key)).toBeNull()
    writeDraft(key, "又寫了")
    clearDraft(key)
    expect(readDraft(key, parseReplyDraft)).toBeNull()
  })

  it("一個主題一份、一個人一份：互不相干", () => {
    writeDraft(replyDraftKey("usr_a", "top_1"), "給第一個主題的")
    expect(readDraft(replyDraftKey("usr_a", "top_2"), parseReplyDraft)).toBeNull()
    expect(readDraft(replyDraftKey("usr_b", "top_1"), parseReplyDraft)).toBeNull()
    expect(readDraft(newTopicDraftKey("usr_a"), parseNewTopicDraft)).toBeNull()
    expect(readDraft(replyDraftKey("usr_a", "top_1"), parseReplyDraft)).toBe("給第一個主題的")
  })

  it("壞掉的內容、存不了：當作沒有草稿，不丟例外", () => {
    const key = replyDraftKey("usr_a", "top_1")
    window.sessionStorage.setItem(key, "{不是 JSON")
    expect(readDraft(key, parseReplyDraft)).toBeNull()
    window.sessionStorage.setItem(key, JSON.stringify({ not: "a string" }))
    expect(readDraft(key, parseReplyDraft)).toBeNull()
    const original = Storage.prototype.setItem
    Storage.prototype.setItem = () => {
      throw new DOMException("QuotaExceededError")
    }
    try {
      expect(() => writeDraft(key, "存不進去")).not.toThrow()
    } finally {
      Storage.prototype.setItem = original
    }
  })
})

describe("開新主題的草稿", () => {
  const draft: NewTopicDraft = { dest: "group:grp_family", title: "年底對帳", body: "大家把交易補齊", tags: [{ symbol: "2330.TW", code: "2330", name: "台積電" }], removedPreset: null }

  it("發到哪裡、標題、內文、標記都留著", () => {
    const key = newTopicDraftKey("usr_a")
    writeDraft(key, draft)
    expect(readDraft(key, parseNewTopicDraft)).toEqual(draft)
  })

  it("只選了發到哪裡不算草稿（那是要緊的選擇，不替使用者記著）；有標題、內文或標記才算", () => {
    expect(hasTopicContent({ title: " ", body: "\n", tags: [] })).toBe(false)
    expect(hasTopicContent({ title: "有標題", body: "", tags: [] })).toBe(true)
    expect(hasTopicContent({ title: "", body: "有內文", tags: [] })).toBe(true)
    expect(hasTopicContent({ title: "", body: "", tags: draft.tags })).toBe(true)
    expect(parseNewTopicDraft({ dest: "public", title: "", body: "", tags: [] })).toBeNull()
  })

  it("形狀不對的欄位丟掉，不讓壞掉的草稿弄壞表單", () => {
    expect(parseNewTopicDraft(null)).toBeNull()
    expect(parseNewTopicDraft("字串")).toBeNull()
    expect(parseNewTopicDraft({ dest: 3, title: "標題", body: 5, tags: [{ symbol: "2330.TW" }, { symbol: "0050.TW", code: "0050", name: "元大台灣50", extra: 1 }, "x"], removedPreset: 9 })).toEqual({
      dest: null,
      title: "標題",
      body: "",
      tags: [{ symbol: "0050.TW", code: "0050", name: "元大台灣50" }],
      removedPreset: null,
    })
  })
})
