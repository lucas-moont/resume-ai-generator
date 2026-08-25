import { useCallback, useEffect, useState } from 'react'

export type MobileTab = 'sessions' | 'chat' | 'preview'

const MOBILE_TABS: readonly MobileTab[] = ['sessions', 'chat', 'preview']
const TAB_PARAM = 'tab'
const DEFAULT_TAB: MobileTab = 'chat'

function readTabFromLocation<T extends string>(tabs: readonly T[], defaultTab: T): T {
  const value = new URLSearchParams(window.location.search).get(TAB_PARAM)
  return value !== null && (tabs as readonly string[]).includes(value) ? (value as T) : defaultTab
}

/**
 * Mirrors the active mobile tab (v3 debt d) in the URL's `?tab=` search
 * param via plain history.pushState/popstate — no router is installed
 * (package.json), and one piece of view state doesn't justify adding one.
 * A reload or a direct link with `?tab=preview` opens straight to that tab;
 * each tab switch pushes a history entry, so back/forward works too.
 *
 * v7 ticket 12: generalized over the tab NAMES because the Job Monitor area has its own
 * two (`busca` / `vagas`) while sharing the one `?tab=` param — an app mode only ever shows
 * its own tabs, so a value belonging to another mode simply reads as unrecognized and falls
 * back to that mode's default. `tabs` and `defaultTab` are expected to be module-level
 * constants: they are effect dependencies, so a fresh array literal per render would
 * resubscribe the popstate listener on every render.
 */
export function useTabUrl<T extends string>(
  tabs: readonly T[],
  defaultTab: T,
): [T, (tab: T) => void] {
  const [tab, setTab] = useState<T>(() => readTabFromLocation(tabs, defaultTab))

  useEffect(() => {
    const onPopState = () => setTab(readTabFromLocation(tabs, defaultTab))
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [tabs, defaultTab])

  const setTabUrl = useCallback((next: T) => {
    setTab((current) => {
      if (current === next) return current
      const url = new URL(window.location.href)
      url.searchParams.set(TAB_PARAM, next)
      window.history.pushState(null, '', url)
      return next
    })
  }, [])

  return [tab, setTabUrl]
}

/** The resume flow's three mobile tabs. */
export function useMobileTabUrl(): [MobileTab, (tab: MobileTab) => void] {
  return useTabUrl(MOBILE_TABS, DEFAULT_TAB)
}
