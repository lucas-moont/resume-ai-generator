import type { ResumeDocument } from '../../types/resume'

/** A contact detail a finished resume is expected to carry. Ordered by how much a recruiter
 * misses it: without a phone or an email nobody can reach the candidate at all. */
export type ContactGap = 'phone' | 'email' | 'location' | 'profileLink'

const GAP_ORDER: ContactGap[] = ['phone', 'email', 'location', 'profileLink']

function isBlank(value: string | null | undefined): boolean {
  return typeof value !== 'string' || value.trim() === ''
}

/**
 * Which contact details this resume is missing.
 *
 * Deliberately computed HERE — in code, on the document the user is looking at — and never fed
 * to the LLM as a quality issue. `app/domain/quality.py`'s issues become instructions for the
 * auto-improve refine pass, and "add a phone number" handed to a model that does not have the
 * number produces an invented one; the anchor exists precisely to stop that. A gap is something
 * to TELL THE USER about, because only they can fill it.
 *
 * Front-end rather than an SSE field for one concrete reason: this has to hold for a resume
 * rehydrated from an old session too, and a rehydrated document never replays the generation
 * events. Reading the store covers every path that puts a resume on screen — generate, refine,
 * inline edit, reload — and re-evaluates the moment the user types the missing value in.
 *
 * `profileLink` is satisfied by ANY link, since a resume with a LinkedIn but no GitHub (or the
 * reverse) is complete enough; it flags only the case of no links at all.
 */
export function contactGaps(resume: ResumeDocument | null | undefined): ContactGap[] {
  if (!resume) return []
  const missing = new Set<ContactGap>()
  if (isBlank(resume.phone)) missing.add('phone')
  if (isBlank(resume.email)) missing.add('email')
  if (isBlank(resume.location)) missing.add('location')
  const hasUsableLink = (resume.links ?? []).some(
    (link) => !isBlank(link?.url) && !isBlank(link?.label),
  )
  if (!hasUsableLink) missing.add('profileLink')
  return GAP_ORDER.filter((gap) => missing.has(gap))
}

const LABELS: Record<string, Record<ContactGap, string>> = {
  'pt-BR': {
    phone: 'telefone',
    email: 'e-mail',
    location: 'localização',
    profileLink: 'link de perfil (LinkedIn/GitHub)',
  },
  en: {
    phone: 'phone',
    email: 'email',
    location: 'location',
    profileLink: 'profile link (LinkedIn/GitHub)',
  },
}

/** Human-readable gap names in the resume's own locale. Locale detection mirrors
 * ResumePreview's own `(resume.locale || '').toLowerCase().startsWith('pt')` rather than testing
 * `=== 'pt-BR'`, so a document stored as `pt`, `PT-BR` or `pt_BR` gets the same labels the
 * preview beside it is already using. */
export function contactGapLabels(gaps: ContactGap[], locale: string | undefined): string[] {
  const isPt = (locale || '').toLowerCase().startsWith('pt')
  const dict = isPt ? LABELS['pt-BR'] : LABELS.en
  return gaps.map((gap) => dict[gap])
}
