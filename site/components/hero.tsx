import { ArrowRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { AudioWave } from '@/components/audio-wave'
import { GithubIcon } from '@/components/github-icon'
import { RELEASES_URL, REPO_URL } from '@/lib/github-release'

export function Hero({ version }: { version: string }) {
  return (
    <section id="top" className="relative overflow-hidden">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[420px] bg-[radial-gradient(60%_100%_at_50%_0%,rgba(59,130,246,0.12),transparent_70%)]" />
      <div className="mx-auto max-w-[1000px] px-5 pt-20 pb-16 text-center md:pt-28 md:pb-24">
        <span className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs text-muted-foreground">
          <span className="size-1.5 rounded-full bg-accent" />
          Открытый код · Linux &amp; macOS
        </span>

        <h1 className="mx-auto mt-6 max-w-3xl text-4xl font-semibold tracking-tight text-balance md:text-6xl">
          Личный <span className="text-accent">Джарвис</span>. Бесплатно.
          Локально. Твой.
        </h1>

        <p className="mx-auto mt-5 max-w-2xl text-base leading-relaxed text-muted-foreground text-pretty md:text-lg">
          Голосовой ИИ-ассистент с открытым кодом: управляет рабочим столом,
          выполняет команды, отвечает через LLM и делает всё это голосом — без
          подписок.
        </p>

        <div className="mx-auto mt-10 max-w-md">
          <AudioWave />
        </div>

        <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <Button
            nativeButton={false}
            render={<a href={RELEASES_URL} target="_blank" rel="noreferrer" />}
            size="lg"
            className="h-11 px-5 text-[15px]"
          >
            Скачать {version}
            <ArrowRight className="size-4" />
          </Button>
          <Button
            nativeButton={false}
            render={<a href={REPO_URL} target="_blank" rel="noreferrer" />}
            variant="outline"
            size="lg"
            className="h-11 px-5 text-[15px]"
          >
            <GithubIcon className="size-4" />
            GitHub
          </Button>
        </div>

        <p className="mt-6 font-mono text-xs text-muted-foreground">
          Debian · Fedora · Arch · AppImage · macOS (ARM + Intel)
        </p>
      </div>
    </section>
  )
}
