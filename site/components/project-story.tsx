import { Reveal } from '@/components/reveal'

export function ProjectStory() {
  return (
    <section className="mx-auto max-w-[720px] px-5 py-20 md:py-24">
      <Reveal className="rounded-xl border border-border bg-card p-8 text-center md:p-12">
        <p className="text-base leading-relaxed text-muted-foreground text-pretty md:text-lg">
          Проект начался с одного файла, сгенерированного нейросетью, — после
          того как в тиктоке попался платный Джарвис с конским ценником. За 3
          месяца, в 15 лет, бесплатными нейросетями и без единой строки кода
          руками — получился вот этот продукт.
        </p>
        <p className="mt-6 text-sm font-medium text-accent-light">
          Собран при помощи OpenCode
        </p>
      </Reveal>
    </section>
  )
}
