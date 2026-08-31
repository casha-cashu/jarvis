'use client'

import { useEffect, useState } from 'react'
import { SiteHeader } from '@/components/site-header'
import { Hero } from '@/components/hero'
import { Features } from '@/components/features'
import { Screenshots } from '@/components/screenshots'
import { HowItWorks } from '@/components/how-it-works'
import { DoctorTerminal } from '@/components/doctor-terminal'
import { Faq } from '@/components/faq'
import { ProjectStory } from '@/components/project-story'
import { DownloadTable } from '@/components/download-table'
import { SiteFooter } from '@/components/site-footer'
import { getLatestRelease, type ReleaseData } from '@/lib/github-release'

const FALLBACK: ReleaseData = {
  version: 'v2.8.0',
  publishedAt: null,
  live: false,
  rows: [],
}

export default function Page() {
  const [release, setRelease] = useState<ReleaseData | null>(null)

  useEffect(() => {
    getLatestRelease().then(setRelease).catch(() => setRelease(FALLBACK))
  }, [])

  return (
    <div className="min-h-screen bg-background">
      <SiteHeader />
      <main>
        <Hero version={release?.version ?? '...'} />
        <Features />
        <Screenshots />
        <HowItWorks />
        <DoctorTerminal />
        <Faq />
        <ProjectStory />
        {release ? <DownloadTable release={release} /> : null}
      </main>
      <SiteFooter />
    </div>
  )
}
