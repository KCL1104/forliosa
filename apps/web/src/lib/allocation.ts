import type { AllocationSlice } from "@/api/types"

/** 超過 6 塊的部分合併成「其他」（dataviz：不產生第 7 個顏色） */
export function foldSlices(slices: AllocationSlice[], max = 6): AllocationSlice[] {
  if (slices.length <= max) return slices
  const head = slices.slice(0, max - 1)
  const tail = slices.slice(max - 1)
  return [
    ...head,
    {
      key: "__other",
      label: `其他 ${tail.length} 項`,
      value: tail.reduce((s, x) => s + x.value, 0),
      weight: tail.reduce((s, x) => s + x.weight, 0),
    },
  ]
}
