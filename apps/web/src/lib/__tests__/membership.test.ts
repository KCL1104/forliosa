import { describe, expect, it } from "vitest"
import type { AdminMember } from "@/api/types"
import { formatDay, monthLater } from "@/lib/membership"

const member = (until: string | null, active = true): AdminMember => ({ user_id: "usr_a", email: "a@example.com", display_name: "阿明", until, note: null, active })

describe("monthLater（會員多一個月的最後一天）", () => {
  it("新開通：從今天起算一個月（11/15 → 12/14），月底不足就到月底", () => {
    expect(monthLater("2026-11-15")).toBe("2026-12-14")
    expect(monthLater("2026-01-31")).toBe("2026-02-27")
    expect(monthLater("2026-12-20")).toBe("2027-01-19")
  })
  it("續期：還是會員就從原本的最後一天往後接；過期了從今天起算", () => {
    expect(monthLater("2026-11-15", member("2026-12-14"))).toBe("2027-01-14")
    expect(monthLater("2026-11-15", member("2026-11-01", false))).toBe("2026-12-14")
  })
  it("formatDay", () => {
    expect(formatDay("2026-12-04")).toBe("2026/12/4")
  })
})
