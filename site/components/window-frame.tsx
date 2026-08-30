import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function WindowFrame({
  title,
  children,
  className,
  bodyClassName,
}: {
  title?: string
  children: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <div
      className={cn(
        'overflow-hidden rounded-xl border border-border bg-card shadow-[0_1px_0_rgba(255,255,255,0.03)_inset,0_20px_50px_-20px_rgba(0,0,0,0.8)]',
        className,
      )}
    >
      <div className="flex items-center gap-2 border-b border-border bg-[#0f0f12] px-4 py-3">
        <span className="size-3 rounded-full bg-[#3a3a40]" />
        <span className="size-3 rounded-full bg-[#3a3a40]" />
        <span className="size-3 rounded-full bg-[#3a3a40]" />
        {title ? (
          <span className="ml-3 truncate font-mono text-xs text-muted-foreground">
            {title}
          </span>
        ) : null}
      </div>
      <div className={cn('p-0', bodyClassName)}>{children}</div>
    </div>
  )
}
