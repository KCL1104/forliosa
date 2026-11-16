import type { ImportPage } from "@/api/types"

/**
 * 截圖與照片：在瀏覽器裡解碼、轉正（照片的拍攝方向）、切塊，重新存成 JPEG 送出。
 * - 長邊不超過 2,576px（模型看圖不再縮小的上限）；一般的截圖整張縮進去就好，
 *   很長的捲動截圖（高超過寬的 2.5 倍）照高度切成好幾塊，上下重疊 160px，切到一半的那一列在下一塊還看得到。
 * - 重新存成 JPEG 也順便拿掉照片裡的 EXIF（拍攝地點、機型）。
 * - 不信副檔名：看檔案開頭的幾個位元組判斷格式。HEIC 這台瀏覽器解不開時，請使用者改存成 JPEG。
 */

export const MAX_EDGE = 2576
export const TILE_OVERLAP = 160
/** 一次最多幾張截圖（產品負責人 2026-11-16） */
export const MAX_IMAGES = 5
/** 一次最多送幾頁（切塊之後也算） */
export const MAX_PAGES = 20
const TALL = 2.5
const JPEG_QUALITY = 0.86

export type SniffedType = "image/jpeg" | "image/png" | "image/webp" | "image/heic" | "image/avif" | "application/pdf"

/** 看檔案開頭判斷格式；認不得是 null */
export function sniffType(head: Uint8Array): SniffedType | null {
  const at = (i: number) => head[i] ?? -1
  const ascii = (from: number, to: number) => String.fromCharCode(...head.slice(from, to))
  if (at(0) === 0xff && at(1) === 0xd8 && at(2) === 0xff) return "image/jpeg"
  if (at(0) === 0x89 && ascii(1, 4) === "PNG") return "image/png"
  if (ascii(0, 4) === "RIFF" && ascii(8, 12) === "WEBP") return "image/webp"
  if (ascii(0, 5) === "%PDF-") return "application/pdf"
  if (ascii(4, 8) === "ftyp") {
    const brand = ascii(8, 12)
    if (["heic", "heix", "hevc", "hevx", "heim", "heis", "hevm", "hevs", "mif1", "msf1"].includes(brand)) return "image/heic"
    if (brand === "avif" || brand === "avis") return "image/avif"
  }
  return null
}

export async function sniffFile(file: Blob): Promise<SniffedType | null> {
  return sniffType(new Uint8Array(await file.slice(0, 16).arrayBuffer()))
}

export interface Tile {
  /** 原圖上的範圍 */
  sx: number
  sy: number
  sw: number
  sh: number
  /** 輸出的大小 */
  width: number
  height: number
}

/** 一張圖要切成哪幾塊（每一塊的長邊都不超過 `max`） */
export function planTiles(width: number, height: number, max = MAX_EDGE, overlap = TILE_OVERLAP): Tile[] {
  if (width <= 0 || height <= 0) return []
  const long = Math.max(width, height)
  if (long <= max) return [{ sx: 0, sy: 0, sw: width, sh: height, width, height }]
  if (height / width <= TALL) {
    const s = max / long
    return [{ sx: 0, sy: 0, sw: width, sh: height, width: Math.round(width * s), height: Math.round(height * s) }]
  }
  // 很長的捲動截圖：寬縮到不超過上限，再照高度切
  const s = Math.min(1, max / width)
  const outW = Math.round(width * s)
  const totalH = height * s
  const step = max - overlap
  const count = Math.ceil((totalH - overlap) / step)
  const tiles: Tile[] = []
  for (let i = 0; i < count; i++) {
    const top = Math.min(i * step, totalH - max)
    const tileH = Math.min(max, totalH)
    tiles.push({ sx: 0, sy: top / s, sw: width, sh: tileH / s, width: outW, height: Math.round(tileH) })
  }
  return tiles
}

export function canvasToJpeg(canvas: HTMLCanvasElement, quality = JPEG_QUALITY): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("圖片轉不出來"))), "image/jpeg", quality)
  })
}

/** base64（不含 `data:` 前綴） */
export function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(String(r.result).replace(/^data:[^,]*,/, ""))
    r.onerror = () => reject(r.error ?? new Error("讀不到檔案"))
    r.readAsDataURL(blob)
  })
}

export class ImageReadError extends Error {
  constructor(
    readonly reason: "heic" | "unsupported" | "broken",
    readonly fileName: string,
  ) {
    super(reason)
    this.name = "ImageReadError"
  }
}

const abortError = () => new DOMException("已取消", "AbortError")

/** 一張截圖或照片 → 一到好幾頁（JPEG） */
export async function prepareImage(file: File, signal?: AbortSignal): Promise<ImportPage[]> {
  const type = await sniffFile(file)
  if (type === "application/pdf" || type === "image/avif") throw new ImageReadError("unsupported", file.name)
  let bitmap: ImageBitmap
  try {
    // 照片的拍攝方向照 EXIF 轉正
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" })
  } catch {
    // Safari 解得開 HEIC，其他瀏覽器不行
    throw new ImageReadError(type === "image/heic" ? "heic" : type ? "broken" : "unsupported", file.name)
  }
  try {
    const pages: ImportPage[] = []
    for (const t of planTiles(bitmap.width, bitmap.height)) {
      if (signal?.aborted) throw abortError()
      const canvas = document.createElement("canvas")
      canvas.width = t.width
      canvas.height = t.height
      const ctx = canvas.getContext("2d")
      if (!ctx) throw new ImageReadError("broken", file.name)
      ctx.fillStyle = "#fff"
      ctx.fillRect(0, 0, t.width, t.height)
      ctx.imageSmoothingQuality = "high"
      ctx.drawImage(bitmap, t.sx, t.sy, t.sw, t.sh, 0, 0, t.width, t.height)
      const blob = await canvasToJpeg(canvas)
      pages.push({ media_type: "image/jpeg", data: await blobToBase64(blob) })
      canvas.width = 0
      canvas.height = 0
    }
    return pages
  } finally {
    bitmap.close()
  }
}
