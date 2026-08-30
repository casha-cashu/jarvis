import { Analytics } from '@vercel/analytics/next'
import type { Metadata, Viewport } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'

const inter = Inter({
  subsets: ['latin', 'cyrillic'],
  variable: '--font-inter',
  display: 'swap',
})

const LOGO =
  'https://raw.githubusercontent.com/casha-cashu/jarvis/main/docs/logos/jarvis-logo.svg'
const BANNER =
  'https://raw.githubusercontent.com/casha-cashu/jarvis/main/docs/logos/jarvis-banner.png'

export const metadata: Metadata = {
  title: 'JARVIS — голосовой ИИ-ассистент с открытым кодом',
  description:
    'JARVIS — голосовой ИИ-ассистент с открытым кодом для Linux и macOS: управляет рабочим столом, выполняет команды и отвечает через LLM. Локально, бесплатно, без подписок.',
  generator: 'v0.app',
  keywords: [
    'JARVIS',
    'голосовой ассистент',
    'open source',
    'Linux',
    'macOS',
    'Ollama',
    'LLM',
    'Whisper',
    'Piper',
  ],
  icons: {
    icon: [{ url: LOGO, type: 'image/svg+xml' }],
    shortcut: [{ url: LOGO, type: 'image/svg+xml' }],
  },
  openGraph: {
    title: 'JARVIS — личный Джарвис. Бесплатно. Локально. Твой.',
    description:
      'Голосовой ИИ-ассистент с открытым кодом для Linux и macOS. Без подписок, локально, с открытым исходным кодом.',
    type: 'website',
    locale: 'ru_RU',
    images: [{ url: BANNER, alt: 'JARVIS' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'JARVIS — личный Джарвис. Бесплатно. Локально. Твой.',
    description:
      'Голосовой ИИ-ассистент с открытым кодом для Linux и macOS.',
    images: [BANNER],
  },
}

export const viewport: Viewport = {
  colorScheme: 'dark',
  themeColor: '#0a0a0b',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="ru" className={`${inter.variable} bg-background`}>
      <body className="font-sans">
        {children}
        {process.env.NODE_ENV === 'production' && <Analytics />}
      </body>
    </html>
  )
}
