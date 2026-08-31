'use client'

import useSWR from 'swr'
import type { ReleaseData } from '@/lib/github-release'

/** A payload is only usable if it actually carries a rows array to render. */
function isValidRelease(data: unknown): data is ReleaseData {
  return (
    !!data &&
    typeof data === 'object' &&
    Array.isArray((data as ReleaseData).rows) &&
    typeof (data as ReleaseData).version === 'string'
  )
}

const fetcher = async (url: string): Promise<ReleaseData> => {
  const r = await fetch(url)
  if (!r.ok) throw new Error('Failed to load release')
  const data = await r.json()
  if (!isValidRelease(data)) throw new Error('Malformed release payload')
  return data
}

/**
 * Returns the latest release, seeded with server-rendered data for an instant
 * first paint, then revalidated against the API so a new GitHub release shows
 * up without a redeploy. Refreshes on focus and reconnect.
 */
export function useRelease(initial: ReleaseData): ReleaseData {
  const { data } = useSWR<ReleaseData>('/api/latest-release', fetcher, {
    fallbackData: initial,
    revalidateOnFocus: true,
    revalidateOnReconnect: true,
    // Keep showing the last good data if a refresh fails.
    keepPreviousData: true,
  })

  // Never hand a partial/undefined payload back to consumers that call
  // `rows.map(...)` — always guarantee a renderable ReleaseData.
  return isValidRelease(data) ? data : initial
}
