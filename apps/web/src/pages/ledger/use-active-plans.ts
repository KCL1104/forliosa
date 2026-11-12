import { appToday } from "@/api"
import { useRecurringPlans } from "@/api/queries"
import type { RecurringPlan } from "@/api/types"
import { activePlansBySymbol } from "@/lib/ledger-display"

/** 持倉列上要標記的定期定額（啟用中的計畫，依代號） */
export function useActivePlans(): Map<string, RecurringPlan[]> {
  const plans = useRecurringPlans()
  return activePlansBySymbol(plans.data ?? [], appToday())
}
