const BAR_COUNT = 40

export function AudioWave() {
  return (
    <div
      className="flex h-16 items-center justify-center gap-[3px]"
      aria-hidden="true"
    >
      {Array.from({ length: BAR_COUNT }).map((_, i) => {
        // Phase-shifted sine so bars ripple like a continuous waveform.
        const phase = (i / BAR_COUNT) * Math.PI * 2
        const delay = -(Math.sin(phase) * 0.5 + 0.5) * 1.2
        const duration = 1.1 + (i % 5) * 0.08
        return (
          <span
            key={i}
            className="wave-bar w-[3px] rounded-full"
            style={{
              height: '100%',
              animationDelay: `${delay.toFixed(2)}s`,
              animationDuration: `${duration.toFixed(2)}s`,
              background:
                'linear-gradient(to top, var(--accent), var(--accent-light))',
            }}
          />
        )
      })}
    </div>
  )
}
