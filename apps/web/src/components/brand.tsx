import { cn } from "@/lib/utils"

/**
 * 品牌章：朱泥白文方印，印面為 F。
 * 朱泥紅在本產品只用在這裡（紅色在介面上代表「漲」）。
 */
export function SealMark({ className, size = 28 }: { className?: string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden
      className={cn("shrink-0", className)}
    >
      <rect x="1" y="1" width="30" height="30" rx="5" fill="var(--seal)" />
      <rect x="4" y="4" width="24" height="24" rx="2.5" fill="none" stroke="var(--seal-foreground)" strokeWidth="1.4" opacity="0.9" />
      <path
        d="M11.5 9.5h10v3.1h-6.6v3.3h5.8v3h-5.8v5.6h-3.4z"
        fill="var(--seal-foreground)"
      />
    </svg>
  )
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <SealMark />
      <span className="text-lg font-semibold tracking-[-0.01em]">Forliosa</span>
    </span>
  )
}
