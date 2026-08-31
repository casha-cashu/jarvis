'use client'

import { useEffect, useState } from 'react'
import type { ReleaseData } from '@/lib/github-release'

const REPO = 'casha-cashu/jarvis'
const API = `https://api.github.com/repos/${REPO}/releases/latest`

function normalizeVersion(tag: string): string {
  const v = tag.trim()
  return v.startsWith('v') ? v : `v${v}`
}

function buildFallback(): ReleaseData {
  return { version: 'v2.8.0', publishedAt: null, live: false, rows: [] }
}

async function fetchRelease(): Promise<ReleaseData> {
  const res = await fetch(API, {
    headers: {
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
  })
  if (!res.ok) return buildFallback()
  const data = (await res.json()) as {
    tag_name?: string
    published_at?: string
    assets?: { name: string; browser_download_url: string }[]
  }
  if (!data?.tag_name) return buildFallback()

  const bareVersion = data.tag_name.replace(/^v/, '')
  return {
    version: normalizeVersion(data.tag_name),
    publishedAt: data.published_at ?? null,
    live: true,
    rows: [
      {
        platform: 'Debian / Ubuntu',
        file: `jarvis_${bareVersion}_amd64.deb`,
        cmd: `sudo apt install ./jarvis_${bareVersion}_amd64.deb`,
        url: data.assets?.find((a) => a.name.endsWith('.deb'))?.browser_download_url ?? `https://github.com/${REPO}/releases/latest`,
      },
      {
        platform: 'Fedora',
        file: `jarvis-${bareVersion}.rpm`,
        cmd: `sudo dnf install ./jarvis-${bareVersion}.rpm`,
        url: data.assets?.find((a) => a.name.endsWith('.rpm'))?.browser_download_url ?? `https://github.com/${REPO}/releases/latest`,
      },
      {
        platform: 'Arch / CachyOS',
        file: `jarvis-${bareVersion}.pkg.tar.zst`,
        cmd: `sudo pacman -U jarvis-${bareVersion}.pkg.tar.zst`,
        url: data.assets?.find((a) => a.name.endsWith('.pkg.tar.zst'))?.browser_download_url ?? `https://github.com/${REPO}/releases/latest`,
      },
      {
        platform: 'Любой дистрибутив',
        file: `Jarvis-${bareVersion}.AppImage`,
        cmd: `chmod +x Jarvis-${bareVersion}.AppImage && ./Jarvis-${bareVersion}.AppImage`,
        url: data.assets?.find((a) => a.name.toLowerCase().endsWith('.appimage'))?.browser_download_url ?? `https://github.com/${REPO}/releases/latest`,
      },
      {
        platform: 'macOS (ARM)',
        file: `Jarvis-${bareVersion}-arm64.dmg`,
        cmd: `open Jarvis-${bareVersion}-arm64.dmg`,
        url: data.assets?.find((a) => a.name.includes('arm64') && a.name.endsWith('.dmg'))?.browser_download_url ?? `https://github.com/${REPO}/releases/latest`,
      },
      {
        platform: 'macOS (Intel)',
        file: `Jarvis-${bareVersion}-x64.dmg`,
        cmd: `open Jarvis-${bareVersion}-x64.dmg`,
        url: data.assets?.find((a) => (a.name.includes('x64') || a.name.includes('x86_64')) && a.name.endsWith('.dmg'))?.browser_download_url ?? `https://github.com/${REPO}/releases/latest`,
      },
    ],
  }
}

export function useRelease(initial: ReleaseData): ReleaseData {
  const [release, setRelease] = useState<ReleaseData>(initial)

  useEffect(() => {
    // Свежий релиз при каждой загрузке страницы
    fetchRelease().then(setRelease).catch(() => {/* оставляем initial */})
  }, [])

  return release
}
