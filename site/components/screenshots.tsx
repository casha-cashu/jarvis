import { MessageSquare, Settings, Activity, type LucideIcon } from 'lucide-react'
import { Reveal } from '@/components/reveal'
import { WindowFrame } from '@/components/window-frame'

type Shot = {
  title: string
  file: string
  caption: string
  icon: LucideIcon
}

const SHOTS: Shot[] = [
  {
    title: 'jarvis — чат',
    file: 'docs/screenshots/chat.png',
    caption: 'Чат с ассистентом',
    icon: MessageSquare,
  },
  {
    title: 'jarvis — настройки',
    file: 'docs/screenshots/settings.png',
    caption: 'Настройки и модели',
    icon: Settings,
  },
  {
    title: 'jarvis — статус',
    file: 'docs/screenshots/status.png',
    caption: 'Статус и диагностика',
    icon: Activity,
  },
]

export function Screenshots() {
  return (
    <section className="mx-auto max-w-[1000px] px-5 py-20 md:py-28">
      <Reveal className="mb-12 text-center">
        <h2 className="text-3xl font-semibold tracking-tight text-balance md:text-4xl">
          Интерфейс
        </h2>
        <p className="mx-auto mt-3 max-w-xl text-muted-foreground text-pretty">
          Настольное приложение с чатом, настройками и статусом окружения.
        </p>
      </Reveal>

      <div className="grid gap-4 md:grid-cols-3">
        {SHOTS.map((shot, i) => (
          <Reveal key={shot.title} delay={i * 90}>
            <WindowFrame title={shot.title} className="h-full">
              <div className="flex aspect-[4/3] flex-col items-center justify-center gap-3 bg-[radial-gradient(70%_70%_at_50%_30%,rgba(59,130,246,0.06),transparent)] p-6 text-center">
                <div className="flex size-12 items-center justify-center rounded-xl border border-border bg-background text-muted-foreground">
                  <shot.icon className="size-6" />
                </div>
                <p className="text-sm font-medium text-foreground">
                  {shot.caption}
                </p>
                <p className="font-mono text-xs text-muted-foreground">
                  {shot.file}
                </p>
              </div>
            </WindowFrame>
          </Reveal>
        ))}
      </div>
    </section>
  )
}
