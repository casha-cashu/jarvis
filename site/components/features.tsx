import {
  Mic,
  Monitor,
  Bot,
  MessageCircle,
  Clock,
  Stethoscope,
  type LucideIcon,
} from 'lucide-react'
import { Reveal } from '@/components/reveal'

type Feature = {
  icon: LucideIcon
  title: string
  body: string
}

const FEATURES: Feature[] = [
  {
    icon: Mic,
    title: 'Голос',
    body: 'Wake word «Джарвис», распознавание через Vosk или faster-whisper с Silero VAD, озвучка ответов Piper\u2019ом.',
  },
  {
    icon: Monitor,
    title: 'Управление системой',
    body: 'Воркспейсы, окна, скриншоты, громкость, блокировка — Hyprland, KDE, GNOME, i3, Sway, macOS.',
  },
  {
    icon: Bot,
    title: 'LLM + bash-агент',
    body: 'Ollama локально или OpenAI/Anthropic/OpenRouter. Агент выполняет реальные команды с трёхслойным approval gate.',
  },
  {
    icon: MessageCircle,
    title: 'Telegram-бот',
    body: 'Спрашивай Джарвиса из любого места — тот же мозг, тот же bash-агент, только в мессенджере.',
  },
  {
    icon: Clock,
    title: 'Напоминания и диктовка',
    body: '«Напомни через 10 минут» — и напомнит даже после перезапуска. Диктовка голосом в любое окно.',
  },
  {
    icon: Stethoscope,
    title: 'jarvis doctor',
    body: 'Диагностика окружения одной командой: конфиг, аудио, модели, LLM — приложи вывод к баг-репорту.',
  },
]

export function Features() {
  return (
    <section id="features" className="mx-auto max-w-[1000px] px-5 py-20 md:py-28">
      <Reveal className="mb-12 text-center">
        <h2 className="text-3xl font-semibold tracking-tight text-balance md:text-4xl">
          Всё, что должен уметь ассистент
        </h2>
        <p className="mx-auto mt-3 max-w-xl text-muted-foreground text-pretty">
          Голос, система, LLM и агент — в одном локальном приложении.
        </p>
      </Reveal>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map((f, i) => (
          <Reveal key={f.title} delay={(i % 3) * 80}>
            <article className="group h-full rounded-xl border border-border bg-card p-6 transition-all duration-200 hover:-translate-y-0.5 hover:border-accent/60">
              <div className="flex size-11 items-center justify-center rounded-lg border border-border bg-background text-accent transition-colors group-hover:border-accent/50">
                <f.icon className="size-5" />
              </div>
              <h3 className="mt-5 text-lg font-semibold">{f.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground text-pretty">
                {f.body}
              </p>
            </article>
          </Reveal>
        ))}
      </div>
    </section>
  )
}
