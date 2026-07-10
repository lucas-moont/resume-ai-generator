import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { temporal } from 'zundo'
import type { ResumeDocument, TemplateId } from '../../../types/resume'

export const STORAGE_KEY = 'resume-agent:resume'

interface ResumeState {
  resume: ResumeDocument | null
  template: TemplateId
  locale: string
  setResume: (resume: ResumeDocument | null) => void
  setTemplate: (template: TemplateId) => void
  setLocale: (locale: string) => void
  clearResume: () => void
}

interface PersistedResumeState {
  resume: ResumeDocument | null
  template: TemplateId
  locale: string
}

export const useResumeStore = create<ResumeState>()(
  temporal(
    persist(
      (set) => ({
        resume: null,
        template: 'modern',
        locale: 'auto',
        setResume: (resume) => set({ resume }),
        setTemplate: (template) => set({ template }),
        setLocale: (locale) => set({ locale }),
        clearResume: () => set({ resume: null }),
      }),
      {
        name: STORAGE_KEY,
        version: 1,
        storage: createJSONStorage(() => localStorage),
        partialize: (state): PersistedResumeState => ({
          resume: state.resume,
          template: state.template,
          locale: state.locale,
        }),
      },
    ),
    {
      // Undo/redo tracks resume content only — template/locale switches
      // aren't "edits" a user would expect Ctrl+Z to revert.
      limit: 50,
      partialize: (state) => ({ resume: state.resume }),
    },
  ),
)

export const useResume = () => useResumeStore((s) => s.resume)
export const useTemplate = () => useResumeStore((s) => s.template)
export const useLocale = () => useResumeStore((s) => s.locale)
