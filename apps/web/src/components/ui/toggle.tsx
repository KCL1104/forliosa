import { Toggle as TogglePrimitive } from "@base-ui/react/toggle"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

/** 切換（選項 chip）：選取語法 (b)——`sel-chip`（aria-pressed／data-pressed） */
const toggleVariants = cva(
  "press sel-chip group/toggle inline-flex items-center justify-center gap-1 rounded-sm text-sm whitespace-nowrap text-ink-2 outline-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-transparent",
        outline: "border border-ctl bg-transparent",
      },
      size: {
        default: "h-8 min-w-8 px-2.5 pointer-coarse:h-11",
        sm: "h-7 min-w-7 px-2 text-sm [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-10 min-w-10 px-3 pointer-coarse:h-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Toggle({
  className,
  variant = "default",
  size = "default",
  ...props
}: TogglePrimitive.Props & VariantProps<typeof toggleVariants>) {
  return (
    <TogglePrimitive
      data-slot="toggle"
      className={cn(toggleVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Toggle, toggleVariants }
