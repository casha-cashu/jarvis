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
    file: 'screenshots/chat.png',
    caption: 'Чат с ассистентом',
    icon: MessageSquare,
  },
  {
    title: 'jarvis — настройки',
    file: 'screenshots/settings.png',
    caption: 'Настройки и модели',
    icon: Settings,
  },
  {
    title: 'jarvis — статус',
    file: 'screenshots/status.png',
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
              <div className="flex h-full flex-col">
                <div className="relative aspect-[4/3] overflow-hidden">
                  <img
                    src={shot.file}
                    alt={shot.caption}
                    loading="lazy"
                    className="absolute inset-0 h-full w-full object-cover object-top"
                  />
                </div>
                <div className="flex items-center gap-2 border-t border-border px-4 py-2.5">
                  <shot.icon className="size-3.5 text-muted-foreground" />
                  <span className="text-xs text-muted-foreground">
                    {shot.caption}
                  </span>
                </div>
              </div>
            </WindowFrame>
          </Reveal>
        ))}
      </div>
    </section>
  )
}
