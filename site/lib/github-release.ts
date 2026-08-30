const REPO = 'casha-cashu/jarvis'
export const REPO_URL = `https://github.com/${REPO}`
export const RELEASES_URL = `${REPO_URL}/releases/latest`

export type DownloadRow = {
  platform: string
  file: string
  cmd: string
  /** Direct asset download URL, or the releases page if no matching asset was found. */
  url: string
}

export type ReleaseData = {
  /** Version label for display, always prefixed with "v" (e.g. "v2.7.0"). */
  version: string
  /** ISO date the release was published, or null if unknown. */
  publishedAt: string | null
  rows: DownloadRow[]
  /** True when data came from the live GitHub API, false when using the fallback. */
  live: boolean
}

type GithubAsset = { name: string; browser_download_url: string }
type GithubRelease = {
  tag_name?: string
  published_at?: string
  assets?: GithubAsset[]
}

/** Platform matchers, in display order. `cmd` receives the matched file name. */
const PLATFORMS: {
  platform: string
  match: (name: string) => boolean
  cmd: (file: string) => string
  fallbackFile: (v: string) => string
}[] = [
  {
    platform: 'Debian / Ubuntu',
    match: (n) => n.endsWith('.deb'),
    cmd: (f) => `sudo apt install ./${f}`,
    fallbackFile: (v) => `jarvis_${v}_amd64.deb`,
  },
  {
    platform: 'Fedora',
    match: (n) => n.endsWith('.rpm'),
    cmd: (f) => `sudo dnf install ./${f}`,
    fallbackFile: (v) => `jarvis-${v}.rpm`,
  },
  {
    platform: 'Arch / CachyOS',
    match: (n) => n.endsWith('.pkg.tar.zst'),
    cmd: (f) => `sudo pacman -U ${f}`,
    fallbackFile: (v) => `jarvis-${v}.pkg.tar.zst`,
  },
  {
    platform: 'Любой дистрибутив',
    match: (n) => n.toLowerCase().endsWith('.appimage'),
    cmd: (f) => `chmod +x ${f} && ./${f}`,
    fallbackFile: (v) => `Jarvis-${v}.AppImage`,
  },
  {
    platform: 'macOS (ARM)',
    match: (n) => /\.dmg$/i.test(n) && /(arm64|aarch64)/i.test(n),
    cmd: (f) => `open ${f}`,
    fallbackFile: (v) => `Jarvis-${v}-arm64.dmg`,
  },
  {
    platform: 'macOS (Intel)',
    match: (n) => /\.dmg$/i.test(n) && /(x64|x86_64|intel)/i.test(n),
    cmd: (f) => `open ${f}`,
    fallbackFile: (v) => `Jarvis-${v}-x64.dmg`,
  },
]

const FALLBACK_VERSION = '2.7.0'

function normalizeVersion(tag: string): string {
  const v = tag.trim()
  return v.startsWith('v') ? v : `v${v}`
}

function buildFallback(): ReleaseData {
  return {
    version: normalizeVersion(FALLBACK_VERSION),
    publishedAt: null,
    live: false,
    rows: PLATFORMS.map((p) => {
      const file = p.fallbackFile(FALLBACK_VERSION)
      return { platform: p.platform, file, cmd: p.cmd(file), url: RELEASES_URL }
    }),
  }
}

export async function getLatestRelease(): Promise<ReleaseData> {
  try {
    const res = await fetch(
      `https://api.github.com/repos/${REPO}/releases/latest`,
      {
        headers: {
          Accept: 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
        },
        // Revalidate hourly so new releases appear automatically.
        next: { revalidate: 3600 },
      },
    )

    if (!res.ok) return buildFallback()

    const data = (await res.json()) as GithubRelease
    if (!data.tag_name) return buildFallback()

    const bareVersion = data.tag_name.replace(/^v/, '')
    const assets = data.assets ?? []

    const rows: DownloadRow[] = PLATFORMS.map((p) => {
      const asset = assets.find((a) => p.match(a.name))
      const file = asset?.name ?? p.fallbackFile(bareVersion)
      return {
        platform: p.platform,
        file,
        cmd: p.cmd(file),
        url: asset?.browser_download_url ?? RELEASES_URL,
      }
    })

    return {
      version: normalizeVersion(data.tag_name),
      publishedAt: data.published_at ?? null,
      live: true,
      rows,
    }
  } catch {
    return buildFallback()
  }
}
