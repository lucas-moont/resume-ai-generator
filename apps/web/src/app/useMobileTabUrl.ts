import { useCallback, useEffect, useState } from 'react'

export type MobileTab = 'sessions' | 'chat' | 'preview'

const MOBILE_TABS: readonly MobileTab[] = ['sessions', 'chat', 'preview']
const TAB_PARAM = 'tab'
const DEFAULT_TAB: MobileTab = 'chat'

function isMobileTab(value: string | null): value is MobileTab {
  return value !== null && (MOBILE_TABS as readonly string[]).includes(value)
}

function readTabFromLocation(): MobileTab {
  const value = new URLSearchParams(window.location.search).get(TAB_PARAM)
  return isMobileTab(value) ? value : DEFAULT_TAB
}

/**
 * Mirrors the active mobile tab (v3 debt d) in the URL's `?tab=` search
 * param via plain history.pushState/popstate — no router is installed
 * (package.json), and one piece of view state doesn't justify adding one.
 * A reload or a direct link with `?tab=preview` opens straight to that tab;
 * each tab switch pushes a history entry, so back/forward works too.
 */
export function useMobileTabUrl(): [MobileTab, (tab: MobileTab) => void] {
  const [tab, setTab] = useState<MobileTab>(() => readTabFromLocation())

  useEffect(() => {
    const onPopState = () => setTab(readTabFromLocation())
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const setMobileTab = useCallback((next: MobileTab) => {
    setTab((current) => {
      if (current === next) return current
      const url = new URL(window.location.href)
      url.searchParams.set(TAB_PARAM, next)
      window.history.pushState(null, '', url)
      return next
    })
  }, [])

  return [tab, setMobileTab]
}
