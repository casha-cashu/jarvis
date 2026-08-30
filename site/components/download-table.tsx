import { Download } from 'lucide-react'
import { Reveal } from '@/components/reveal'
import { RELEASES_URL, type ReleaseData } from '@/lib/github-release'

const dateFmt = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
})

export function DownloadTable({ release }: { release: ReleaseData }) {
  const { version, rows, publishedAt } = release
  const published = publishedAt ? dateFmt.format(new Date(publishedAt)) : null

  return (
    <section id="download" className="mx-auto max-w-[1000px] px-5 py-20 md:py-28">
      <Reveal className="mb-12 text-center">
        <h2 className="text-3xl font-semibold tracking-tight text-balance md:text-4xl">
          Скачать {version}
        </h2>
        <p className="mx-auto mt-3 max-w-xl text-muted-foreground text-pretty">
          Выбери платформу — все сборки в релизах на GitHub.
          {published ? ` Обновлено ${published}.` : ''}
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
            {rows.map((row) => (
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
                    href={row.url}
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
        {rows.map((row, i) => (
          <Reveal key={row.platform} delay={i * 60}>
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium">{row.platform}</span>
                <a
                  href={row.url}
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

      <p className="mt-8 text-center text-xs text-muted-foreground">
        Все релизы и changelog —{' '}
        <a
          href={RELEASES_URL}
          target="_blank"
          rel="noreferrer"
          className="text-accent-light underline underline-offset-4 hover:text-accent"
        >
          на GitHub
        </a>
        .
      </p>
    </section>
  )
}
