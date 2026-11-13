import { ArrowLeftIcon } from "lucide-react"
import { PlainLink } from "@/app/links"
import type { Origin } from "./origin"

const BACK = "-ml-1 inline-flex h-9 items-center gap-1 rounded-sm px-1 text-ink hover:bg-hov pointer-coarse:h-11"

/** 連到來源的連結（內文裡的站內連結：`PlainLink`，不標 `aria-current`） */
export function OriginLink({ origin, className, children }: { origin: Origin; className?: string; children: React.ReactNode }) {
  if (origin.kind === "group") {
    return (
      <PlainLink to="/groups/$groupId" params={{ groupId: origin.id }} search={{ tab: "discussions" }} className={className}>
        {children}
      </PlainLink>
    )
  }
  if (origin.kind === "stock") {
    return (
      <PlainLink to="/stock/$symbol" params={{ symbol: origin.symbol }} search={{ tab: "discussions" }} className={className}>
        {children}
      </PlainLink>
    )
  }
  return (
    <PlainLink to="/discussions" search={origin.search} className={className}>
      {children}
    </PlainLink>
  )
}

/** 麵包屑：「← 討論」「← 群組名」「← 股票名」（和群組頁、個股頁同一種） */
export function BackLink({ origin }: { origin: Origin }) {
  return (
    <OriginLink origin={origin} className={BACK}>
      <ArrowLeftIcon aria-hidden className="size-4 shrink-0" />
      <span className="max-w-[16rem] truncate">{origin.kind === "list" ? "討論" : origin.name}</span>
    </OriginLink>
  )
}
