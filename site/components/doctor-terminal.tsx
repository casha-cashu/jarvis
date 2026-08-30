'use client'

import { useEffect, useRef, useState } from 'react'
import { Reveal } from '@/components/reveal'
import { WindowFrame } from '@/components/window-frame'

const LINES = [
  '$ jarvis doctor',
  '✅ Python: 3.14',
  '✅ Конфиг: config.yaml (схема ок)',
  '✅ Словари команд: commands.json + apps.json',
  '✅ DE/адаптер: OS=linux, DE=hyprland',
  '✅ STT (whisper): model_size=tiny',
  '✅ TTS (piper): бинарь + модель на месте',
  '✅ LLM (ollama): qwen2.5:3b на http://localhost:11434',
  'Итого: 8 ок, 1 предупреждений, 0 ошибок',
]

const FULL = LINES.join('\n')

function lineClass(line: string) {
  if (line.startsWith('$')) return 'text-accent-light'
  if (line.startsWith('✅')) return 'text-foreground'
  if (line.startsWith('Итого')) return 'mt-1 font-medium text-accent-light'
  return 'text-foreground'
}

export function DoctorTerminal() {
  const ref = useRef<HTMLDivElement | null>(null)
  const [count, setCount] = useState(0)
  const [started, setStarted] = useState(false)

  useEffect(() => {
    const node = ref.current
    if (!node) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setStarted(true)
          observer.disconnect()
        }
      },
      { threshold: 0.4 },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!started) return
    const reduce =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce) {
      setCount(FULL.length)
      return
    }
    if (count >= FULL.length) return
    const id = window.setTimeout(() => setCount((c) => c + 1), 25)
    return () => window.clearTimeout(id)
  }, [started, count])

  const typed = FULL.slice(0, count)
  const typedLines = typed.split('\n')
  const done = count >= FULL.length

  return (
    <section className="mx-auto max-w-[1000px] px-5 py-20 md:py-28">
      <Reveal className="mb-12 text-center">
        <h2 className="text-3xl font-semibold tracking-tight text-balance md:text-4xl">
          Живая диагностика
        </h2>
        <p className="mx-auto mt-3 max-w-xl text-muted-foreground text-pretty">
          Одна команда проверяет всё окружение — от аудио до LLM.
        </p>
      </Reveal>

      <Reveal>
        <WindowFrame title="~/jarvis — bash">
          <div
            ref={ref}
            className="min-h-[280px] bg-[#0b0b0d] p-5 font-mono text-[13px] leading-relaxed md:p-6 md:text-sm"
            aria-label="Вывод команды jarvis doctor"
          >
            {typedLines.map((line, i) => {
              const isLast = i === typedLines.length - 1
              return (
                <div key={i} className={lineClass(line)}>
                  <span className="whitespace-pre-wrap break-words">
                    {line}
                  </span>
                  {isLast && !done ? (
                    <span className="caret ml-0.5 inline-block text-accent-light">
                      ▍
                    </span>
                  ) : null}
                </div>
              )
            })}
            {done ? (
              <span className="caret mt-1 inline-block text-accent-light">
                ▍
              </span>
            ) : null}
          </div>
        </WindowFrame>
      </Reveal>
    </section>
  )
}
