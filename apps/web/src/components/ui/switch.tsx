import { Switch as SwitchPrimitive } from "@base-ui/react/switch"
import { cn } from "@/lib/utils"

function Switch({
  className,
  size = "default",
  ...props
}: SwitchPrimitive.Root.Props & {
  size?: "sm" | "default"
}) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      data-size={size}
      className={cn(
        // 開＝選取語法 (b)：on-bg 底＋1px 內框 on-ring（淺色是墨色實底；深色是格線藍底，不是白色實塊）
        // 關：淺色鉛筆灰實底；深色只有 1px 鉛筆灰內框（底和紙同色）
        "data-checked:bg-on-bg data-checked:inset-ring data-checked:inset-ring-on-ring data-unchecked:bg-ctl dark:data-unchecked:bg-transparent dark:data-unchecked:inset-ring dark:data-unchecked:inset-ring-ctl aria-invalid:outline-2 aria-invalid:outline-offset-2 aria-invalid:outline-ink shrink-0 rounded-full border border-transparent data-[size=default]:h-[18.4px] data-[size=default]:w-[32px] data-[size=sm]:h-[14px] data-[size=sm]:w-[24px] peer group/switch relative inline-flex items-center transition-colors outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink after:absolute after:-inset-x-3 after:-inset-y-2 data-disabled:cursor-not-allowed data-disabled:opacity-50",
        className
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className="bg-paper data-checked:bg-on-fg dark:data-unchecked:bg-ink-2 rounded-full group-data-[size=default]/switch:size-4 group-data-[size=sm]/switch:size-3 group-data-[size=default]/switch:data-checked:translate-x-[calc(100%-2px)] group-data-[size=sm]/switch:data-checked:translate-x-[calc(100%-2px)] group-data-[size=default]/switch:data-unchecked:translate-x-0 group-data-[size=sm]/switch:data-unchecked:translate-x-0 pointer-events-none block ring-0 transition-transform"
      />
    </SwitchPrimitive.Root>
  )
}

export { Switch }
