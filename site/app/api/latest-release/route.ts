import { NextResponse } from 'next/server'
import { getLatestRelease } from '@/lib/github-release'

// Always re-evaluate on request; getLatestRelease itself caches the
// upstream GitHub call for 60s, so this stays under the rate limit.
export const dynamic = 'force-dynamic'

export async function GET() {
  const release = await getLatestRelease()
  return NextResponse.json(release)
}
