import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

/** v5 ticket f1: the top-level area the user is in. 'resume' is the original chat + A4 preview
 * flow; 'analysis' is the Profile Analysis area. v7 ticket 11 adds 'jobs', the Job Monitor.
 * Persisted so the choice survives a reload, same discipline as the active-session id and the
 * theme. */
export type AppMode = 'resume' | 'analysis' | 'jobs'

export const APP_MODE_STORAGE_KEY = 'resume-agent:app-mode'

/** The single source of truth for what a persisted `mode` may be — `AppMode` itself is erased at
 * runtime, and `migrate` needs to check a value that came from localStorage. */
const APP_MODES: readonly AppMode[] = ['resume', 'analysis', 'jobs']

export function isAppMode(value: unknown): value is AppMode {
  return typeof value === 'string' && (APP_MODES as readonly string[]).includes(value)
}

interface AppModeState {
  mode: AppMode
  setMode: (mode: AppMode) => void
}

export const useAppModeStore = create<AppModeState>()(
  persist(
    (set) => ({
      mode: 'resume',
      setMode: (mode) => set({ mode }),
    }),
    {
      name: APP_MODE_STORAGE_KEY,
      // v7 ticket 11: bumped from 1 when 'jobs' joined AppMode. Widening is backwards
      // compatible, so `migrate` deliberately KEEPS a v1 value instead of resetting the user to
      // 'resume' — the version bump exists to give the store a hook for the case that is NOT
      // safe (a mode being retired), which the guard below already covers: anything that is not
      // a current AppMode falls back to 'resume' rather than rendering nothing.
      version: 2,
      migrate: (persisted) => {
        const mode = (persisted as Partial<AppModeState> | undefined)?.mode
        return { mode: isAppMode(mode) ? mode : 'resume' } as AppModeState
      },
      storage: createJSONStorage(() => localStorage),
    },
  ),
)
