const LOGO =
  'https://raw.githubusercontent.com/casha-cashu/jarvis/main/docs/logos/jarvis-logo.svg'
const REPO = 'https://github.com/casha-cashu/jarvis'

const LINKS = [
  { label: 'GitHub', href: REPO },
  { label: 'Issues', href: `${REPO}/issues` },
  { label: 'Discussions', href: `${REPO}/discussions` },
  { label: 'MIT', href: `${REPO}/blob/main/LICENSE` },
]

export function SiteFooter() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-[1000px] flex-col items-center gap-6 px-5 py-12 text-center md:flex-row md:justify-between md:text-left">
        <div className="flex items-center gap-2.5">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={LOGO || "/placeholder.svg"} alt="" className="size-6" />
          <span className="text-sm font-semibold tracking-wide">JARVIS</span>
        </div>

        <nav className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2">
          {LINKS.map((link) => (
            <a
              key={link.label}
              href={link.href}
              target="_blank"
              rel="noreferrer"
              className="text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              {link.label}
            </a>
          ))}
        </nav>
      </div>
      <div className="border-t border-border">
        <p className="mx-auto max-w-[1000px] px-5 py-5 text-center text-xs text-muted-foreground">
          MIT · сделано 15-летним пацаном и бесплатными нейросетями
        </p>
      </div>
    </footer>
  )
}
