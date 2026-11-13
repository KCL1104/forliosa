import * as React from "react"
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog"
import { cn } from "@/lib/utils"

import { Button } from "@/components/ui/button"

/**
 * 對話框（聯絡簿的一張表單，見 DESIGN.md「對話框」）：
 * - 白紙底（raised）、6px 方肩（和選單、popover 同一個 token）、1px 格線框；墨色遮罩，沒有背景模糊。
 * - 標題下面一條印刷線（和區塊標題同一種線），說明是內文的第一行。
 * - 頁尾用一條 1px 格線和內文分開，沒有底色；按鈕靠右排成一列，定案的那一顆是簽名格（`variant="sign"`）。
 * - 關閉是有字的「關閉」（標題那一列的右邊），不是角落的 ×。
 */
function Dialog({ ...props }: DialogPrimitive.Root.Props) {
  return <DialogPrimitive.Root data-slot="dialog" {...props} />
}

function DialogTrigger({ ...props }: DialogPrimitive.Trigger.Props) {
  return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />
}

function DialogPortal({ ...props }: DialogPrimitive.Portal.Props) {
  return <DialogPrimitive.Portal data-slot="dialog-portal" {...props} />
}

function DialogClose({ ...props }: DialogPrimitive.Close.Props) {
  return <DialogPrimitive.Close data-slot="dialog-close" {...props} />
}

function DialogOverlay({
  className,
  ...props
}: DialogPrimitive.Backdrop.Props) {
  return (
    <DialogPrimitive.Backdrop
      data-slot="dialog-overlay"
      className={cn("data-open:animate-in data-closed:animate-out data-closed:fade-out-0 data-open:fade-in-0 bg-scrim duration-150 fixed inset-0 isolate z-50", className)}
      {...props}
    />
  )
}

/** 對話框的那張紙：alert-dialog.tsx 共用同一串 */
const dialogSurface =
  "bg-raised text-ink data-open:animate-in data-closed:animate-out data-closed:fade-out-0 data-open:fade-in-0 data-closed:zoom-out-95 data-open:zoom-in-95 ring-rule fixed top-1/2 left-1/2 z-50 grid w-full max-w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 gap-4 rounded-md p-5 text-md ring-1 duration-150 outline-none"

function DialogContent({
  className,
  children,
  showCloseButton = true,
  ...props
}: DialogPrimitive.Popup.Props & {
  showCloseButton?: boolean
}) {
  return (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Popup
        data-slot="dialog-content"
        className={cn(dialogSurface, "sm:max-w-sm", className)}
        {...props}
      >
        {children}
        {showCloseButton && (
          // 有字的關閉：和標題同一列、靠右（標題右邊留了位置）；觸控時 44px 高
          <DialogPrimitive.Close
            data-slot="dialog-close"
            render={<Button variant="ghost" size="sm" className="absolute top-3.5 right-3 text-ink-2 pointer-coarse:top-2" />}
          >
            關閉
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Popup>
    </DialogPortal>
  )
}

function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-header"
      className={cn("flex flex-col gap-3", className)}
      {...props}
    />
  )
}

function DialogFooter({
  className,
  showCloseButton = false,
  children,
  ...props
}: React.ComponentProps<"div"> & {
  showCloseButton?: boolean
}) {
  return (
    <div
      data-slot="dialog-footer"
      className={cn("flex flex-wrap items-center justify-end gap-2 border-t border-rule pt-4", className)}
      {...props}
    >
      {showCloseButton && (
        <DialogPrimitive.Close render={<Button variant="outline" />}>
          關閉
        </DialogPrimitive.Close>
      )}
      {children}
    </div>
  )
}

function DialogTitle({ className, ...props }: DialogPrimitive.Title.Props) {
  return (
    <DialogPrimitive.Title
      data-slot="dialog-title"
      // 右邊留給「關閉」；底下是印刷線
      className={cn("border-b border-print pr-14 pb-3 text-lg leading-snug font-bold text-ink", className)}
      {...props}
    />
  )
}

function DialogDescription({
  className,
  ...props
}: DialogPrimitive.Description.Props) {
  return (
    <DialogPrimitive.Description
      data-slot="dialog-description"
      className={cn("text-md text-ink-2 *:[a]:underline *:[a]:underline-offset-3 *:[a]:hover:text-ink", className)}
      {...props}
    />
  )
}

export {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger,
  dialogSurface,
}
