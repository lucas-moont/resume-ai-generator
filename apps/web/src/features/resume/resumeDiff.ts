import type { EducationItem, ExperienceItem, Link, ProjectItem, ResumeDocument } from '../../types/resume'
import { diffResumeSections } from './diffResumeSections'

export const SECTION_LABELS: Record<string, string> = {
  fullName: 'name',
  headline: 'headline',
  location: 'location',
  email: 'email',
  phone: 'phone',
  links: 'links',
  summary: 'summary',
  experience: 'experience',
  projects: 'projects',
  skills: 'skills',
  education: 'education',
}

export interface ResumeFieldChange {
  key: string
  label: string
  /** `null` when there's no prior resume to compare against (first generate) — the
   * field is newly added, not "changed from X". */
  before: string | null
  after: string
}

const EMPTY_PLACEHOLDER = '—'

function formatSectionValue(key: string, value: unknown): string {
  switch (key) {
    case 'links':
      return (value as Link[]).map((l) => l.label).join(', ') || EMPTY_PLACEHOLDER
    case 'experience':
      return (value as ExperienceItem[]).map((e) => `${e.title} @ ${e.company}`).join('; ') || EMPTY_PLACEHOLDER
    case 'projects':
      return (value as ProjectItem[]).map((p) => p.name).join(', ') || EMPTY_PLACEHOLDER
    case 'skills':
      return (value as string[]).join(', ') || EMPTY_PLACEHOLDER
    case 'education':
      return (
        (value as EducationItem[]).map((e) => `${e.degree}, ${e.institution}`).join('; ') || EMPTY_PLACEHOLDER
      )
    default:
      return (value as string | null | undefined) || EMPTY_PLACEHOLDER
  }
}

/**
 * Pure (before, after) -> structured diff, one entry per section
 * `diffResumeSections` flags as changed. Section-level, not line-by-line —
 * same granularity as `diffResumeSections`, just carrying the actual
 * before/after text instead of only the section's key. `before` is `null`
 * when there's no prior resume (first generate): the card renders that as
 * "added" rather than a false "changed from nothing".
 */
export function diffResume(prev: ResumeDocument | null, next: ResumeDocument): ResumeFieldChange[] {
  return diffResumeSections(prev, next).map((key) => ({
    key,
    label: SECTION_LABELS[key] ?? key,
    before: prev ? formatSectionValue(key, prev[key as keyof ResumeDocument]) : null,
    after: formatSectionValue(key, next[key as keyof ResumeDocument]),
  }))
}
