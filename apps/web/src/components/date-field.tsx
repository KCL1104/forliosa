import { CalendarIcon, ChevronDownIcon, ChevronLeftIcon, ChevronRightIcon } from "lucide-react"
import { useState } from "react"
import { DayPicker, type ChevronProps } from "react-day-picker"
import { zhTW } from "react-day-picker/locale"
import { appToday } from "@/api"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { formatDateLong } from "@/lib/format"
import { cn } from "@/lib/utils"

/**
 * 日期欄位（產品負責人 2026-11-14，參考 Google 財經的「購買日期」）：看起來是一個欄位（日曆圖示＋日期或提示字），
 * 點了跳出月曆。月曆的年、月是下拉選單（記好幾年前買的不用一個月一個月翻），`max` 以後的日子不能選，
 * 底下「今天」一鍵選今天。值是 `YYYY-MM-DD`，空字串是還沒選。
 * 抽屜（手機）裡的月曆開在抽屜裡面（`PopoverContent` 讀 `PortalContainer`），不會被抽屜蓋住或點不到。
 */
export function DateField({
  id,
  value,
  onChange,
  max = appToday(),
  min,
  placeholder = "選擇日期",
  label,
  invalid,
  describedBy,
  className,
}: {
  id?: string
  value: string
  onChange: (value: string) => void
  /** 最晚可以選的日期（預設今天：買進、賣出都不會在未來） */
  max?: string
  min?: string
  placeholder?: string
  /** 欄位的無障礙名稱（外面的 label 用 htmlFor 指到 `id` 時可以不給） */
  label?: string
  invalid?: boolean
  describedBy?: string
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const selected = value ? toDate(value) : undefined
  const maxDate = toDate(max)
  const minDate = min ? toDate(min) : new Date(1990, 0, 1)
  const today = appToday()
  const todayOk = today <= max && (!min || today >= min)
  const pick = (d: Date | undefined) => {
    if (!d) return
    onChange(toIso(d))
    setOpen(false)
  }
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        id={id}
        aria-label={label ? `${label}${value ? `：${formatDateLong(value)}` : "，還沒選"}` : undefined}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        className={cn(
          "flex h-10 w-full min-w-0 items-center gap-2 rounded-sm border border-input bg-raised px-3 text-left text-base transition-colors outline-none md:text-md pointer-coarse:h-11 pointer-coarse:text-[1rem]",
          "hover:border-ctl focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 data-[popup-open]:border-ring",
          "aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40",
          className,
        )}
      >
        <CalendarIcon aria-hidden className="size-4 shrink-0 text-ink-2" />
        {value ? <span className="num min-w-0 truncate">{formatDateLong(value)}</span> : <span className="min-w-0 truncate text-muted-foreground">{placeholder}</span>}
      </PopoverTrigger>
      <PopoverContent align="start" className="w-auto gap-0 p-3">
        <DayPicker
          mode="single"
          required
          autoFocus
          locale={zhTW}
          weekStartsOn={0}
          captionLayout="dropdown"
          showOutsideDays
          fixedWeeks
          selected={selected}
          onSelect={pick}
          // 「今天」用台北的日期（appToday），不是瀏覽器所在時區的
          today={toDate(today)}
          defaultMonth={selected ?? (todayOk ? toDate(today) : maxDate)}
          startMonth={minDate}
          endMonth={maxDate}
          disabled={[{ after: maxDate }, { before: minDate }]}
          formatters={{
            formatWeekdayName: (d) => WEEKDAYS[d.getDay()]!,
            formatMonthDropdown: (d) => `${d.getMonth() + 1} 月`,
            formatYearDropdown: (d) => `${d.getFullYear()} 年`,
          }}
          labels={{
            labelPrevious: () => "上個月",
            labelNext: () => "下個月",
            labelMonthDropdown: () => "月份",
            labelYearDropdown: () => "年份",
            labelDayButton: (d, m) => `${d.getFullYear()} 年 ${d.getMonth() + 1} 月 ${d.getDate()} 日（${WEEKDAYS[d.getDay()]}）${m.today ? "，今天" : ""}${m.selected ? "，已選" : ""}`,
            labelGrid: (d) => `${d.getFullYear()} 年 ${d.getMonth() + 1} 月`,
          }}
          components={{ Chevron }}
          classNames={{
            root: "relative select-none text-md",
            months: "flex flex-col",
            month: "flex flex-col gap-2",
            month_caption: "flex h-9 items-center pr-20",
            dropdowns: "flex items-center gap-1.5",
            dropdown_root:
              "relative inline-flex h-8 items-center rounded-sm border border-ctl pl-2.5 pr-1.5 hover:bg-hov has-[select:focus-visible]:border-ring has-[select:focus-visible]:ring-3 has-[select:focus-visible]:ring-ring/50 pointer-coarse:h-10",
            dropdown: "absolute inset-0 z-10 w-full cursor-pointer appearance-none opacity-0",
            caption_label: "num inline-flex items-center gap-1 font-medium whitespace-nowrap",
            nav: "absolute top-0 right-0 flex h-9 items-center gap-1",
            button_previous:
              "grid size-8 place-items-center rounded-sm text-ink outline-none hover:bg-hov focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-35 pointer-coarse:size-10",
            button_next:
              "grid size-8 place-items-center rounded-sm text-ink outline-none hover:bg-hov focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-35 pointer-coarse:size-10",
            month_grid: "border-collapse",
            weekdays: "",
            weekday: "h-8 w-9 text-xs font-normal text-ink-2 pointer-coarse:w-10",
            week: "",
            day: "p-0 text-center",
            day_button:
              "num mx-auto grid size-9 place-items-center rounded-sm text-md outline-none hover:bg-hov focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:hover:bg-transparent pointer-coarse:size-10",
            selected:
              "[&>button]:bg-on-bg [&>button]:font-medium [&>button]:text-on-fg [&>button]:shadow-[inset_0_0_0_1px_var(--on-ring)] [&>button]:hover:bg-on-bg",
            today: "[&>button]:font-semibold [&>button]:underline [&>button]:decoration-1 [&>button]:underline-offset-4",
            outside: "[&>button]:text-ink-2",
            disabled: "[&>button]:text-ink-2/45",
            hidden: "invisible",
          }}
        />
        {todayOk && (
          <div className="mt-2 flex justify-end border-t border-rule pt-2">
            <button
              type="button"
              onClick={() => pick(toDate(today))}
              className="inline-flex min-h-8 items-center rounded-sm px-2 text-sm font-medium text-ink outline-none hover:bg-hov focus-visible:ring-3 focus-visible:ring-ring/50 pointer-coarse:min-h-10"
            >
              今天
            </button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  )
}

const WEEKDAYS = ["日", "一", "二", "三", "四", "五", "六"]

function Chevron({ orientation, className }: ChevronProps) {
  const Icon = orientation === "left" ? ChevronLeftIcon : orientation === "right" ? ChevronRightIcon : ChevronDownIcon
  return <Icon aria-hidden className={cn(orientation === "down" ? "size-3.5 text-ink-2" : "size-4", className)} />
}

/** `YYYY-MM-DD` → 當地時間那一天的 0 點（月曆用；不經過 UTC，日期不會差一天） */
function toDate(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number)
  return new Date(y!, m! - 1, d!)
}

function toIso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}
