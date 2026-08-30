import { Download } from 'lucide-react'
import { Reveal } from '@/components/reveal'

const RELEASES = 'https://github.com/casha-cashu/jarvis/releases/latest'

const ROWS = [
  {
    platform: 'Debian / Ubuntu',
    file: 'jarvis_2.7.0_amd64.deb',
    cmd: 'sudo apt install ./jarvis_2.7.0_amd64.deb',
  },
  {
    platform: 'Fedora',
    file: 'jarvis-2.7.0.rpm',
    cmd: 'sudo dnf install ./jarvis-2.7.0.rpm',
  },
  {
    platform: 'Arch / CachyOS',
    file: 'jarvis-2.7.0.pkg.tar.zst',
    cmd: 'sudo pacman -U jarvis-2.7.0.pkg.tar.zst',
  },
  {
    platform: 'Любой дистрибутив',
    file: 'Jarvis-2.7.0.AppImage',
    cmd: 'chmod +x Jarvis-2.7.0.AppImage && ./Jarvis-2.7.0.AppImage',
  },
  {
    platform: 'macOS (ARM)',
    file: 'Jarvis-2.7.0-arm64.dmg',
    cmd: 'open Jarvis-2.7.0-arm64.dmg',
  },
  {
    platform: 'macOS (Intel)',
    file: 'Jarvis-2.7.0-x64.dmg',
    cmd: 'open Jarvis-2.7.0-x64.dmg',
  },
]

export function DownloadTable() {
  return (
    <section id="download" className="mx-auto max-w-[1000px] px-5 py-20 md:py-28">
      <Reveal className="mb-12 text-center">
        <h2 className="text-3xl font-semibold tracking-tight text-balance md:text-4xl">
          Скачать v2.7.0
        </h2>
        <p className="mx-auto mt-3 max-w-xl text-muted-foreground text-pretty">
          Выбери платформу — все сборки в релизах на GitHub.
        </p>
      </Reveal>

      {/* Desktop table */}
      <Reveal className="hidden overflow-hidden rounded-xl border border-border bg-card md:block">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
              <th className="px-5 py-4 font-medium">Платформа</th>
              <th className="px-5 py-4 font-medium">Файл</th>
              <th className="px-5 py-4 font-medium">Установка</th>
              <th className="px-5 py-4" />
            </tr>
          </thead>
          <tbody>
            {ROWS.map((row) => (
              <tr
                key={row.platform}
                className="border-b border-border last:border-0 transition-colors hover:bg-muted/40"
              >
                <td className="px-5 py-4 font-medium whitespace-nowrap">
                  {row.platform}
                </td>
                <td className="px-5 py-4 font-mono text-xs text-muted-foreground">
                  {row.file}
                </td>
                <td className="px-5 py-4 font-mono text-xs text-muted-foreground">
                  {row.cmd}
                </td>
                <td className="px-5 py-4 text-right">
                  <a
                    href={RELEASES}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-accent/60 hover:text-accent-light"
                  >
                    <Download className="size-3.5" />
                    Скачать
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Reveal>

      {/* Mobile cards */}
      <div className="grid gap-3 md:hidden">
        {ROWS.map((row, i) => (
          <Reveal key={row.platform} delay={i * 60}>
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium">{row.platform}</span>
                <a
                  href={RELEASES}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:border-accent/60 hover:text-accent-light"
                >
                  <Download className="size-3.5" />
                  Скачать
                </a>
              </div>
              <p className="mt-3 font-mono text-xs text-muted-foreground break-all">
                {row.file}
              </p>
              <p className="mt-2 rounded-lg bg-background p-3 font-mono text-xs text-muted-foreground break-all">
                {row.cmd}
              </p>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  )
}
