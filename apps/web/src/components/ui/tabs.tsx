import { Tabs as TabsPrimitive } from "@base-ui/react/tabs"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

function Tabs({
  className,
  orientation = "horizontal",
  ...props
}: TabsPrimitive.Root.Props) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      data-orientation={orientation}
      className={cn(
        "gap-2 group/tabs flex data-horizontal:flex-col",
        className
      )}
      {...props}
    />
  )
}

/**
 * 分頁列（聯絡簿）：
 * - line（預設）：文字分頁，選取語法 (a)——墨色、700、2px 墨色底線；底下一條格線
 * - default 以外的 `segmented`：1px 鉛筆灰外框的分段，選取語法 (b)
 */
const tabsListVariants = cva(
  "group/tabs-list inline-flex w-fit items-center text-ink-2 group-data-vertical/tabs:h-fit group-data-vertical/tabs:flex-col",
  {
    variants: {
      variant: {
        default: "gap-1 border-b border-rule",
        line: "gap-1 border-b border-rule",
        segmented: "gap-1 rounded-md border border-ctl p-1",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function TabsList({
  className,
  variant = "default",
  ...props
}: TabsPrimitive.List.Props & VariantProps<typeof tabsListVariants>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      data-variant={variant}
      className={cn(tabsListVariants({ variant }), className)}
      {...props}
    />
  )
}

function TabsTrigger({ className, ...props }: TabsPrimitive.Tab.Props) {
  return (
    <TabsPrimitive.Tab
      data-slot="tabs-trigger"
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap text-base text-ink-2 outline-none disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        // (a) 文字分頁：底線壓在分頁列的格線上
        "group-data-[variant=default]/tabs-list:sel-tab group-data-[variant=line]/tabs-list:sel-tab group-data-[variant=default]/tabs-list:-mb-px group-data-[variant=line]/tabs-list:-mb-px group-data-[variant=default]/tabs-list:h-12 group-data-[variant=line]/tabs-list:h-12 group-data-[variant=default]/tabs-list:px-3 group-data-[variant=line]/tabs-list:px-3",
        // (b) 分段
        "group-data-[variant=segmented]/tabs-list:sel-chip group-data-[variant=segmented]/tabs-list:h-[34px] group-data-[variant=segmented]/tabs-list:rounded-sm group-data-[variant=segmented]/tabs-list:px-4",
        className
      )}
      {...props}
    />
  )
}

function TabsContent({ className, ...props }: TabsPrimitive.Panel.Props) {
  return (
    <TabsPrimitive.Panel
      data-slot="tabs-content"
      className={cn("text-sm flex-1 outline-none", className)}
      {...props}
    />
  )
}

export { Tabs, TabsList, TabsTrigger, TabsContent, tabsListVariants }
