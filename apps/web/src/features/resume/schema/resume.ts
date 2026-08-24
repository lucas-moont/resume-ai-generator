import { z } from 'zod'

/**
 * Runtime validation for ResumeDocument, parallel to (not replacing) the
 * hand-written TS types in `types/resume.ts` — that file stays the source of
 * truth for the TS shape; this schema only exists to produce a non-blocking,
 * human-readable list of issues after the done event of a chat SSE turn and
 * after every inline-edit commit (ticket 08). It is deliberately never used
 * to reject/replace data — see `validateResumeDocument`.
 */

const linkSchema = z.object({
  label: z.string(),
  url: z.string(),
})

const experienceItemSchema = z.object({
  company: z.string().min(1, 'Company is required'),
  title: z.string().min(1, 'Title is required'),
  location: z.string().nullish(),
  start: z.string().min(1, 'Start date is required'),
  end: z.string().nullish(),
  highlights: z.array(z.string()),
  // `.optional()`, not a plain array — see the ExperienceItem doc comment in
  // types/resume.ts. A resume rehydrated from localStorage predates the field,
  // and reporting "keyTechnologies: Required" on every one of those would turn
  // this advisory list into noise for data that is perfectly valid.
  keyTechnologies: z.array(z.string()).optional(),
})

const projectItemSchema = z.object({
  name: z.string().min(1, 'Project name is required'),
  description: z.string(),
})

const educationItemSchema = z.object({
  institution: z.string().min(1, 'Institution is required'),
  degree: z.string().min(1, 'Degree is required'),
  end: z.string().nullish(),
  details: z.string().nullish(),
})

const EMAIL_PATTERN = /^\S+@\S+\.\S+$/

export const resumeDocumentSchema = z.object({
  fullName: z.string().min(1, 'Full name is required'),
  headline: z.string(),
  location: z.string().nullish(),
  email: z
    .string()
    .nullish()
    .refine((value) => !value || EMAIL_PATTERN.test(value), { message: 'Email looks invalid' }),
  phone: z.string().nullish(),
  links: z.array(linkSchema),
  summary: z.string(),
  experience: z.array(experienceItemSchema),
  projects: z.array(projectItemSchema),
  skills: z.array(z.string()),
  education: z.array(educationItemSchema),
  locale: z.string(),
})

export interface ValidationResult {
  valid: boolean
  issues: string[]
}

/** Never throws — garbage input just comes back as `{ valid: false, issues: [...] }`. */
export function validateResumeDocument(doc: unknown): ValidationResult {
  const result = resumeDocumentSchema.safeParse(doc)
  if (result.success) return { valid: true, issues: [] }
  const issues = result.error.issues.map((issue) => {
    const path = issue.path.join('.')
    return path ? `${path}: ${issue.message}` : issue.message
  })
  return { valid: false, issues }
}
