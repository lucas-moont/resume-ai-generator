import type { EducationItem, ExperienceItem, ResumeDocument } from '../../../types/resume'

/**
 * Dot-path field editing over a ResumeDocument (`applyFieldEdit(doc,
 * "experience.2.highlights.1", value)`), plus add/remove for the three lists
 * the preview exposes +/- buttons for (skills, per-experience highlights,
 * education). Pure and immutable: every function returns either the SAME
 * document reference (path didn't resolve — a no-op, never a throw, since
 * these run from a contenteditable's onBlur where crashing the edit
 * interaction is worse than silently ignoring a stale/invalid path) or a NEW
 * document with only the touched branch replaced (siblings keep their
 * original references, which lets React skip re-rendering unrelated items).
 */

type TopLevelStringField = 'fullName' | 'headline' | 'summary' | 'location' | 'email' | 'phone'

const TOP_LEVEL_STRING_FIELDS = new Set<TopLevelStringField>([
  'fullName',
  'headline',
  'summary',
  'location',
  'email',
  'phone',
])

const EXPERIENCE_STRING_FIELDS = new Set<keyof ExperienceItem>(['company', 'title', 'location', 'start', 'end'])
const PROJECT_STRING_FIELDS = new Set(['name', 'description'] as const)
const EDUCATION_STRING_FIELDS = new Set<keyof EducationItem>(['institution', 'degree', 'end', 'details'])

const ITEM_ARRAY_FIELDS = {
  experience: EXPERIENCE_STRING_FIELDS,
  projects: PROJECT_STRING_FIELDS,
  education: EDUCATION_STRING_FIELDS,
} as const

type ItemArrayKey = keyof typeof ITEM_ARRAY_FIELDS

function isItemArrayKey(key: string): key is ItemArrayKey {
  return key in ITEM_ARRAY_FIELDS
}

/** Strict non-negative integer — rejects "-1", "abc", "1.5", "" etc. */
function parseIndex(segment: string | undefined): number | null {
  if (segment === undefined || !/^\d+$/.test(segment)) return null
  const n = Number(segment)
  return Number.isSafeInteger(n) ? n : null
}

function setAt<T>(arr: readonly T[], index: number, value: T): T[] {
  return arr.map((item, i) => (i === index ? value : item))
}

export function applyFieldEdit(doc: ResumeDocument, path: string, value: string): ResumeDocument {
  const segments = path.split('.').filter((s) => s.length > 0)

  if (segments.length === 1) {
    const [key] = segments
    if (TOP_LEVEL_STRING_FIELDS.has(key as TopLevelStringField)) {
      return { ...doc, [key]: value }
    }
    return doc
  }

  if (segments.length === 2) {
    // Only the flat "skills.<index>" string list is addressable at this depth.
    const [key, idxSeg] = segments
    if (key !== 'skills') return doc
    const idx = parseIndex(idxSeg)
    if (idx === null || idx < 0 || idx >= doc.skills.length) return doc
    return { ...doc, skills: setAt(doc.skills, idx, value) }
  }

  if (segments.length === 3) {
    const [key, idxSeg, field] = segments
    if (!isItemArrayKey(key)) return doc
    const idx = parseIndex(idxSeg)
    const items = doc[key] as unknown as readonly Record<string, unknown>[]
    if (idx === null || idx < 0 || idx >= items.length) return doc
    const allowedFields = ITEM_ARRAY_FIELDS[key] as ReadonlySet<string>
    if (!allowedFields.has(field)) return doc
    const nextItem = { ...items[idx], [field]: value }
    return { ...doc, [key]: setAt(items, idx, nextItem) } as ResumeDocument
  }

  if (segments.length === 4) {
    // Only "experience.<index>.highlights.<index>" exists at this depth today.
    const [key, idxSeg, nestedKey, nestedIdxSeg] = segments
    if (key !== 'experience' || nestedKey !== 'highlights') return doc
    const idx = parseIndex(idxSeg)
    if (idx === null || idx < 0 || idx >= doc.experience.length) return doc
    const item = doc.experience[idx]
    const nestedIdx = parseIndex(nestedIdxSeg)
    if (nestedIdx === null || nestedIdx < 0 || nestedIdx >= item.highlights.length) return doc
    const nextItem: ExperienceItem = { ...item, highlights: setAt(item.highlights, nestedIdx, value) }
    return { ...doc, experience: setAt(doc.experience, idx, nextItem) }
  }

  return doc
}

// --- add/remove for the three lists the preview exposes +/- buttons for ---

function blankEducationItem(): EducationItem {
  return { institution: '', degree: '', end: null, details: null }
}

const TOP_LEVEL_LIST_FACTORIES = {
  skills: () => '',
  education: blankEducationItem,
} as const

type TopLevelListKey = keyof typeof TOP_LEVEL_LIST_FACTORIES

function isTopLevelListKey(key: string): key is TopLevelListKey {
  return key in TOP_LEVEL_LIST_FACTORIES
}

const HIGHLIGHTS_PATH = /^experience\.(\d+)\.highlights$/

export function addListItem(doc: ResumeDocument, path: string): ResumeDocument {
  if (isTopLevelListKey(path)) {
    const current = doc[path]
    if (!Array.isArray(current)) return doc
    return { ...doc, [path]: [...current, TOP_LEVEL_LIST_FACTORIES[path]()] }
  }

  const match = HIGHLIGHTS_PATH.exec(path)
  if (match) {
    const idx = Number(match[1])
    if (idx < 0 || idx >= doc.experience.length) return doc
    const item = doc.experience[idx]
    const nextItem: ExperienceItem = { ...item, highlights: [...item.highlights, ''] }
    return { ...doc, experience: setAt(doc.experience, idx, nextItem) }
  }

  return doc
}

export function removeListItem(doc: ResumeDocument, path: string, index: number): ResumeDocument {
  if (isTopLevelListKey(path)) {
    const current = doc[path]
    if (!Array.isArray(current) || index < 0 || index >= current.length) return doc
    return { ...doc, [path]: current.filter((_, i) => i !== index) }
  }

  const match = HIGHLIGHTS_PATH.exec(path)
  if (match) {
    const idx = Number(match[1])
    if (idx < 0 || idx >= doc.experience.length) return doc
    const item = doc.experience[idx]
    if (index < 0 || index >= item.highlights.length) return doc
    const nextItem: ExperienceItem = { ...item, highlights: item.highlights.filter((_, i) => i !== index) }
    return { ...doc, experience: setAt(doc.experience, idx, nextItem) }
  }

  return doc
}
