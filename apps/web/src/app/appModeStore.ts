import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

/** v5 ticket f1: the top-level area the user is in. 'resume' is the original chat + A4 preview
 * flow; 'analysis' is the Profile Analysis area. Persisted so the choice survives a reload,
 * same discipline as the active-session id and the theme. */
export type AppMode = 'resume' | 'analysis'

export const APP_MODE_STORAGE_KEY = 'resume-agent:app-mode'

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
      version: 1,
      storage: createJSONStorage(() => localStorage),
    },
  ),
)
