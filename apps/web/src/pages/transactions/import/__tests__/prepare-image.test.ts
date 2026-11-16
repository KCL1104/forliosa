import { describe, expect, it } from "vitest"
import { MAX_EDGE, planTiles, sniffType, TILE_OVERLAP } from "../prepare-image"

const bytes = (...parts: (number[] | string)[]) =>
  new Uint8Array(parts.flatMap((p) => (typeof p === "string" ? [...p].map((c) => c.charCodeAt(0)) : p)))

describe("看檔案開頭判斷格式（不信副檔名）", () => {
  it("JPEG、PNG、WebP、PDF、HEIC、AVIF；認不得是 null", () => {
    expect(sniffType(bytes([0xff, 0xd8, 0xff, 0xe0]))).toBe("image/jpeg")
    expect(sniffType(bytes([0x89], "PNG", [0x0d, 0x0a, 0x1a, 0x0a]))).toBe("image/png")
    expect(sniffType(bytes("RIFF", [0, 0, 0, 0], "WEBPVP8 "))).toBe("image/webp")
    expect(sniffType(bytes("%PDF-1.7"))).toBe("application/pdf")
    expect(sniffType(bytes([0, 0, 0, 0x18], "ftypheic"))).toBe("image/heic")
    expect(sniffType(bytes([0, 0, 0, 0x18], "ftypmif1"))).toBe("image/heic")
    expect(sniffType(bytes([0, 0, 0, 0x18], "ftypavif"))).toBe("image/avif")
    expect(sniffType(bytes("GIF89a"))).toBeNull()
    expect(sniffType(new Uint8Array())).toBeNull()
  })
})

describe("切塊：每一塊的長邊都不超過 2,576px", () => {
  const ok = (tiles: ReturnType<typeof planTiles>) => tiles.every((t) => Math.max(t.width, t.height) <= MAX_EDGE)

  it("一般的手機截圖整張送（不縮）", () => {
    expect(planTiles(1170, 2532)).toEqual([{ sx: 0, sy: 0, sw: 1170, sh: 2532, width: 1170, height: 2532 }])
  })

  it("大張的照片、稍微超過的截圖：縮到長邊 2,576、還是一張", () => {
    const photo = planTiles(4032, 3024)
    expect(photo).toHaveLength(1)
    expect(photo[0]).toMatchObject({ width: 2576, height: 1932 })
    const pro = planTiles(1290, 2796)
    expect(pro).toHaveLength(1)
    expect(ok(pro)).toBe(true)
  })

  it("很長的捲動截圖：照高度切、上下重疊、從頭蓋到尾", () => {
    const tiles = planTiles(1170, 8000)
    expect(tiles.length).toBe(4)
    expect(ok(tiles)).toBe(true)
    expect(tiles[0]!.sy).toBe(0)
    expect(tiles.at(-1)!.sy + tiles.at(-1)!.sh).toBeCloseTo(8000)
    for (let i = 1; i < tiles.length; i++) {
      const overlap = tiles[i - 1]!.sy + tiles[i - 1]!.sh - tiles[i]!.sy
      expect(overlap).toBeGreaterThanOrEqual(TILE_OVERLAP - 0.5)
    }
  })

  it("又寬又長：先把寬縮到上限，再切", () => {
    const tiles = planTiles(3000, 12000)
    expect(ok(tiles)).toBe(true)
    expect(tiles.every((t) => t.width === 2576)).toBe(true)
    expect(tiles.at(-1)!.sy + tiles.at(-1)!.sh).toBeCloseTo(12000)
  })

  it("壞掉的尺寸：不切", () => {
    expect(planTiles(0, 100)).toEqual([])
  })
})
