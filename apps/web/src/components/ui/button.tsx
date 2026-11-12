import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

/**
 * 按鈕（聯絡簿）：方肩 4px。
 * - default：藍黑墨底（主要動作，一個畫面最多一個）
 * - outline：1px 鉛筆灰框（次要動作）
 * - ghost：透明（工具列圖示）
 * - ai：紫色虛線（只屬於 AI 的動作，例如「待簽名」）
 */
const buttonVariants = cva(
  "rounded-sm border border-transparent bg-clip-padding text-md font-medium press [&_svg:not([class*='size-'])]:size-4 group/button inline-flex shrink-0 items-center justify-center whitespace-nowrap outline-none select-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-ink [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-act text-act-fg hover:bg-act-hover",
        outline: "border-ctl bg-transparent text-ink hover:bg-hov aria-expanded:bg-hov",
        secondary: "bg-hov text-ink hover:bg-sel aria-expanded:bg-sel",
        ghost: "text-ink-2 hover:bg-hov hover:text-ink aria-expanded:bg-hov aria-expanded:text-ink",
        destructive: "bg-act text-act-fg hover:bg-act-hover",
        ai: "border-dashed border-ai-rule bg-ai-wash text-ai hover:border-ai focus-visible:outline-ai",
        link: "h-auto px-0 text-ink underline underline-offset-3 hover:text-ink-2",
      },
      size: {
        default: "h-10 gap-2 px-3 pointer-coarse:h-11",
        xs: "h-7 gap-1 px-2 text-xs [&_svg:not([class*='size-'])]:size-3",
        sm: "h-8 gap-1.5 px-2.5 text-sm pointer-coarse:h-10 [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-11 gap-2 px-4 text-base",
        icon: "size-10 pointer-coarse:size-11",
        "icon-xs": "size-7 [&_svg:not([class*='size-'])]:size-3.5",
        "icon-sm": "size-9 pointer-coarse:size-11",
        "icon-lg": "size-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
