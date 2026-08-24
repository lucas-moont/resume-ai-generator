export interface Link {
  label: string
  url: string
}

export interface ExperienceItem {
  company: string
  title: string
  location?: string | null
  start: string
  end?: string | null
  highlights: string[]
  /**
   * Key Technologies — the per-role keyword line (v7). Plain technology names
   * only, like `skills`; rendered under the bullets when non-empty.
   *
   * OPTIONAL on purpose, unlike `highlights`. The API always sends it (the
   * Pydantic model defaults it to `[]`), but resumeStore persists the whole
   * document to localStorage, so a resume saved before this field existed
   * rehydrates without the key and there is no migration that backfills it.
   * Declaring it required would be a compile-time claim the runtime cannot
   * keep — every read site guards with `?.length` instead.
   */
  keyTechnologies?: string[]
}

export interface ProjectItem {
  name: string
  description: string
}

export interface EducationItem {
  institution: string
  degree: string
  end?: string | null
  details?: string | null
}

// Derived from the templates registry — see features/resume/templates/registry.ts.
export type { TemplateId } from '../features/resume/templates/registry'

export interface ResumeDocument {
  fullName: string
  headline: string
  location?: string | null
  email?: string | null
  phone?: string | null
  links: Link[]
  summary: string
  experience: ExperienceItem[]
  projects: ProjectItem[]
  skills: string[]
  education: EducationItem[]
  locale: string
}

export interface ProfileMaster extends ResumeDocument {
  githubUsername?: string | null
}
