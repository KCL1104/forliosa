import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { BENCHMARK_OPTIONS } from "@/lib/labels"

/** 績效比較基準（0050、加權報酬指數…）；變更會存成使用者偏好 */
export function BenchmarkSelect({ value, onChange, size = "default", className }: { value: string; onChange: (v: string) => void; size?: "sm" | "default"; className?: string }) {
  const options = BENCHMARK_OPTIONS.some((o) => o.value === value) ? BENCHMARK_OPTIONS : [...BENCHMARK_OPTIONS, { value, label: value, description: "" }]
  return (
    <Select value={value} onValueChange={(v) => onChange(v as string)} items={options.map((o) => ({ value: o.value, label: o.label }))}>
      <SelectTrigger size={size} className={className ?? "min-w-44"} aria-label="績效比較基準">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
