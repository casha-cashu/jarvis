import {
  Mic,
  Ear,
  AudioLines,
  Command,
  BrainCircuit,
  Volume2,
  ShieldCheck,
  KeyRound,
  WifiOff,
  ChevronRight,
  type LucideIcon,
} from 'lucide-react'
import { Reveal } from '@/components/reveal'

type Step = { icon: LucideIcon; label: string }

const STEPS: Step[] = [
  { icon: Mic, label: 'Микрофон' },
  { icon: Ear, label: 'Wake word' },
  { icon: AudioLines, label: 'STT' },
  { icon: Command, label: 'Команды / NLU' },
  { icon: BrainCircuit, label: 'LLM (+агент)' },
  { icon: Volume2, label: 'TTS' },
]

type Trust = { icon: LucideIcon; title: string; body: string }

const TRUST: Trust[] = [
  {
    icon: ShieldCheck,
    title: 'Approval gate',
    body: 'Опасные команды требуют подтверждения, катастрофические заблокированы всегда.',
  },
  {
    icon: KeyRound,
    title: 'Санитайзер окружения',
    body: 'API-ключи не попадают в дочерние процессы.',
  },
  {
    icon: WifiOff,
    title: 'Локальность',
    body: 'Ollama работает без интернета, телеметрии нет.',
  },
]

export function HowItWorks() {
  return (
    <section id="how" className="mx-auto max-w-[1000px] px-5 py-20 md:py-28">
      <Reveal className="mb-12 text-center">
        <h2 className="text-3xl font-semibold tracking-tight text-balance md:text-4xl">
          Как это работает
        </h2>
        <p className="mx-auto mt-3 max-w-xl text-muted-foreground text-pretty">
          От звука в микрофоне до озвученного ответа — шесть шагов.
        </p>
      </Reveal>

      <Reveal className="rounded-xl border border-border bg-card p-5 md:p-8">
        <ol className="flex flex-col items-stretch gap-3 md:flex-row md:items-center">
          {STEPS.map((step, i) => (
            <li
              key={step.label}
              className="flex items-center gap-3 md:flex-1 md:flex-col md:gap-3"
            >
              <div className="flex w-full items-center gap-3 md:w-auto md:flex-col">
                <div className="flex size-11 shrink-0 items-center justify-center rounded-lg border border-border bg-background text-accent">
                  <step.icon className="size-5" />
                </div>
                <span className="text-sm font-medium md:text-center">
                  {step.label}
                </span>
              </div>
              {i < STEPS.length - 1 ? (
                <ChevronRight className="ml-auto size-4 shrink-0 rotate-90 text-muted-foreground md:ml-0 md:rotate-0" />
              ) : null}
            </li>
          ))}
        </ol>
      </Reveal>

      <div className="mt-4 grid gap-4 md:grid-cols-3">
        {TRUST.map((t, i) => (
          <Reveal key={t.title} delay={i * 80}>
            <article className="group h-full rounded-xl border border-border bg-card p-6 transition-all duration-200 hover:-translate-y-0.5 hover:border-accent/60">
              <div className="flex size-10 items-center justify-center rounded-lg border border-border bg-background text-accent">
                <t.icon className="size-5" />
              </div>
              <h3 className="mt-4 text-base font-semibold">{t.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground text-pretty">
                {t.body}
              </p>
            </article>
          </Reveal>
        ))}
      </div>
    </section>
  )
}
