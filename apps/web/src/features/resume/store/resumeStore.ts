import { create, useStore } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { temporal } from 'zundo'
import type { ResumeDocument, TemplateId } from '../../../types/resume'
import { validateResumeDocument } from '../schema/resume'

export const STORAGE_KEY = 'resume-agent:resume'

interface ResumeState {
  resume: ResumeDocument | null
  template: TemplateId
  locale: string
  /** Non-blocking zod findings for the current `resume` — see schema/resume.ts.
   * Recomputed by setResume, which is the single choke point both the chat
   * SSE "done" event AND every inline-edit commit write through, so this one
   * spot covers both without touching the chat hook or the editing wrappers. */
  validationIssues: string[]
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
        validationIssues: [],
        setResume: (resume) =>
          set({ resume, validationIssues: resume ? validateResumeDocument(resume).issues : [] }),
        setTemplate: (template) => set({ template }),
        setLocale: (locale) => set({ locale }),
        clearResume: () => set({ resume: null, validationIssues: [] }),
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
export const useValidationIssues = () => useResumeStore((s) => s.validationIssues)

/** Reactive access to zundo's temporal store (pastStates/futureStates/undo/redo)
 * — `useResumeStore.temporal` is a vanilla store on its own, so it needs
 * zustand's generic `useStore` to subscribe a component to it. */
export const useResumeTemporal = () => useStore(useResumeStore.temporal)
