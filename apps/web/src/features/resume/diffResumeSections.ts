import type { ResumeDocument } from '../../types/resume'

const RESUME_SECTION_KEYS = [
  'fullName',
  'headline',
  'location',
  'email',
  'phone',
  'links',
  'summary',
  'experience',
  'projects',
  'skills',
  'education',
] as const satisfies readonly (keyof ResumeDocument)[]

/**
 * Shallow, section-level diff (not line-by-line) between two resumes, used by
 * ResumeUpdatedCard to show "changed: summary, skills" after a generate/refine
 * turn. When there's no previous resume (first generate), every non-empty
 * section counts as "changed".
 */
export function diffResumeSections(
  prev: ResumeDocument | null,
  next: ResumeDocument,
): string[] {
  if (!prev) {
    return RESUME_SECTION_KEYS.filter((key) => {
      const value = next[key]
      return Array.isArray(value) ? value.length > 0 : Boolean(value)
    })
  }
  return RESUME_SECTION_KEYS.filter((key) => JSON.stringify(prev[key]) !== JSON.stringify(next[key]))
}
