import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

/**
 * 按鈕（聯絡簿）：方肩 4px。
 * - default：藍黑墨底（主要動作，一個畫面最多一個）
 * - outline：1px 鉛筆灰框（次要動作）
 * - ghost：透明（工具列圖示）
 * - ai：石墨灰虛線（只屬於 AI 的動作，例如「待簽名」）
 * 框線的顏色寫在每個 variant 裡（不寫在共用的那一串）：`buttonVariants()` 直接用在 `<Link>` 上時沒有經過 tailwind-merge，
 * 共用的 `border-transparent` 會蓋掉 outline 的鉛筆灰框（「回到帳本」「登入」這些連結樣式的按鈕就沒有框）。
 * - sign：簽名格的語法（表單上唯一「定案」的動作：建立群組、儲存、加入群組、記一筆的送出）——
 *   直角、墨色底、內縮 3px 的 1px 細框（40%）、14px 粗體；高度和一般按鈕相同（40px，觸控 44px）
 */
const buttonVariants = cva(
  "rounded-sm border bg-clip-padding text-md font-medium press [&_svg:not([class*='size-'])]:size-4 group/button inline-flex shrink-0 items-center justify-center whitespace-nowrap outline-none select-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-ink [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "border-transparent bg-act text-act-fg hover:bg-act-hover",
        outline: "border-ctl bg-transparent text-ink hover:bg-hov aria-expanded:bg-hov",
        secondary: "border-transparent bg-hov text-ink hover:bg-sel aria-expanded:bg-sel",
        ghost: "border-transparent text-ink-2 hover:bg-hov hover:text-ink aria-expanded:bg-hov aria-expanded:text-ink",
        destructive: "border-transparent bg-act text-act-fg hover:bg-act-hover",
        ai: "border-dashed border-ai-rule bg-ai-wash text-ai hover:border-ai focus-visible:outline-ai",
        link: "h-auto border-transparent px-0 text-ink underline underline-offset-3 hover:text-ink-2",
        sign: "relative rounded-none border-0 bg-act font-bold text-act-fg hover:bg-act-hover after:pointer-events-none after:absolute after:inset-0.75 after:border after:border-current after:opacity-40 disabled:bg-rule disabled:text-ink-2 disabled:opacity-100 disabled:after:opacity-0",
      },
      size: {
        default: "h-10 gap-2 px-3 pointer-coarse:h-11",
        xs: "h-7 gap-1 px-2 text-xs [&_svg:not([class*='size-'])]:size-3",
        sm: "h-8 gap-1.5 px-2.5 text-sm pointer-coarse:h-11 [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-11 gap-2 px-4 text-base",
        icon: "size-10 pointer-coarse:size-11",
        "icon-xs": "size-7 [&_svg:not([class*='size-'])]:size-3.5",
        "icon-sm": "size-9 pointer-coarse:size-11",
        "icon-lg": "size-11",
      },
    },
    compoundVariants: [
      // 簽名格的字要有呼吸空間（內框不能貼字）
      { variant: "sign", size: "default", class: "px-5" },
      { variant: "sign", size: "lg", class: "px-6" },
    ],
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
