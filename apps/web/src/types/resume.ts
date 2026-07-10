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
