'use client'

import { useState } from 'react'
import { Plus } from 'lucide-react'
import { Reveal } from '@/components/reveal'
import { cn } from '@/lib/utils'

const FAQ_ITEMS = [
  {
    q: 'Чем это отличается от платных Джарвисов?',
    a: 'Ничем не хуже, но бесплатно и с открытым кодом: весь код на GitHub, данные не уходят никуда, никакой подписки. Локальная Ollama — вообще без интернета.',
  },
  {
    q: 'Что нужно для запуска?',
    a: 'Linux или macOS, микрофон, ~4 ГБ RAM. Для LLM — локальная Ollama либо API-ключ облачного провайдера.',
  },
  {
    q: 'Мои данные куда-то уходят?',
    a: 'Нет. Распознавание и озвучка работают локально, телеметрии в коде нет. LLM можно держать полностью офлайн.',
  },
  {
    q: 'Он выполняет команды на моём ПК — это безопасно?',
    a: 'Есть трёхслойный approval gate: опасные команды требуют подтверждения, катастрофические (rm -rf /, mkfs) заблокированы всегда — даже в самом расслабленном режиме. Все выполнения видны в интерфейсе.',
  },
  {
    q: 'Есть ли Windows?',
    a: 'Нет. Linux и macOS. Для Windows посоветуй WSL2 + AppImage — но честно: лучший опыт на Linux.',
  },
  {
    q: 'Сколько это стоит?',
    a: 'Ноль. Всё бесплатное: код открыт, модели локальные, нейросети, которыми он собран, — тоже халявные.',
  },
]

export function Faq() {
  const [open, setOpen] = useState<number | null>(0)

  return (
    <section id="faq" className="mx-auto max-w-[760px] px-5 py-20 md:py-28">
      <Reveal className="mb-12 text-center">
        <h2 className="text-3xl font-semibold tracking-tight text-balance md:text-4xl">
          Частые вопросы
        </h2>
      </Reveal>

      <Reveal className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
        {FAQ_ITEMS.map((item, i) => {
          const isOpen = open === i
          return (
            <div key={item.q}>
              <h3>
                <button
                  type="button"
                  onClick={() => setOpen(isOpen ? null : i)}
                  aria-expanded={isOpen}
                  className="flex w-full items-center justify-between gap-4 px-5 py-5 text-left transition-colors hover:bg-muted/50"
                >
                  <span className="text-[15px] font-medium text-pretty">
                    {item.q}
                  </span>
                  <Plus
                    className={cn(
                      'size-5 shrink-0 text-muted-foreground transition-transform duration-200',
                      isOpen && 'rotate-45 text-accent',
                    )}
                  />
                </button>
              </h3>
              <div
                className={cn(
                  'grid transition-all duration-300 ease-out',
                  isOpen
                    ? 'grid-rows-[1fr] opacity-100'
                    : 'grid-rows-[0fr] opacity-0',
                )}
              >
                <div className="overflow-hidden">
                  <p className="px-5 pb-5 text-sm leading-relaxed text-muted-foreground text-pretty">
                    {item.a}
                  </p>
                </div>
              </div>
            </div>
          )
        })}
      </Reveal>
    </section>
  )
}
