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
import { getLatestRelease } from '@/lib/github-release'

export default async function Page() {
  const release = await getLatestRelease()

  return (
    <div className="min-h-screen bg-background">
      <SiteHeader />
      <main>
        <Hero version={release.version} />
        <Features />
        <Screenshots />
        <HowItWorks />
        <DoctorTerminal />
        <Faq />
        <ProjectStory />
        <DownloadTable release={release} />
      </main>
      <SiteFooter />
    </div>
  )
}
