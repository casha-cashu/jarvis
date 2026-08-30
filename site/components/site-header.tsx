'use client'

import { useState } from 'react'
import { Menu, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { GithubIcon } from '@/components/github-icon'

const LOGO =
  'https://raw.githubusercontent.com/casha-cashu/jarvis/main/docs/logos/jarvis-logo.svg'

const NAV = [
  { label: 'Возможности', href: '#features' },
  { label: 'Скачать', href: '#download' },
  { label: 'Как работает', href: '#how' },
  { label: 'FAQ', href: '#faq' },
]

const RELEASES = 'https://github.com/casha-cashu/jarvis/releases/latest'
const REPO = 'https://github.com/casha-cashu/jarvis'

export function SiteHeader() {
  const [open, setOpen] = useState(false)

  return (
    <header className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-[1000px] items-center justify-between px-5">
        <a href="#top" className="flex items-center gap-2.5">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={LOGO || "/placeholder.svg"} alt="" className="size-7" />
          <span className="text-[15px] font-semibold tracking-wide">
            JARVIS
          </span>
        </a>

        <nav className="hidden items-center gap-7 md:flex">
          {NAV.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              {item.label}
            </a>
          ))}
          <a
            href={REPO}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            <GithubIcon className="size-4" />
            GitHub
          </a>
          <Button
            nativeButton={false}
            render={<a href={RELEASES} target="_blank" rel="noreferrer" />}
            size="sm"
          >
            Скачать
          </Button>
        </nav>

        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex size-9 items-center justify-center rounded-lg border border-border text-foreground md:hidden"
          aria-label={open ? 'Закрыть меню' : 'Открыть меню'}
          aria-expanded={open}
        >
          {open ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
      </div>

      {open ? (
        <div className="border-t border-border bg-background md:hidden">
          <nav className="mx-auto flex max-w-[1000px] flex-col gap-1 px-5 py-4">
            {NAV.map((item) => (
              <a
                key={item.href}
                href={item.href}
                onClick={() => setOpen(false)}
                className="rounded-lg px-2 py-2.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                {item.label}
              </a>
            ))}
            <a
              href={REPO}
              target="_blank"
              rel="noreferrer"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 rounded-lg px-2 py-2.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <GithubIcon className="size-4" />
              GitHub
            </a>
            <Button
              nativeButton={false}
              render={<a href={RELEASES} target="_blank" rel="noreferrer" />}
              className="mt-2"
            >
              Скачать v2.7.0
            </Button>
          </nav>
        </div>
      ) : null}
    </header>
  )
}
