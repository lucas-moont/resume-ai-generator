import manifest from '@resume-templates/templates.json'

/**
 * TypeScript-only literal union (no separate runtime value): JSON module
 * imports widen string literals to `string`, so there's no way to recover a
 * literal-typed union straight from the manifest below. This exists so call
 * sites like `Record<TemplateId, ...>` (e.g. features/chat/commands.ts's
 * TEMPLATE_ALIASES) get compile-time exhaustiveness — a missing template
 * case is a type error, not a silent gap. It cannot silently drift from the
 * manifest: registry.test.ts asserts the two contain exactly the same ids.
 */
export type TemplateId =
  | 'modern'
  | 'classic'
  | 'minimal'
  | 'compact'
  | 'ats-plain'
  | 'two-column-ats'
  | 'executive'
  | 'tech'

export interface TemplateDefinition {
  id: TemplateId
  label: string
  description: string
  tags: readonly string[]
}

/**
 * packages/resume-templates/templates.json is the single source of truth for
 * template identity (ids + metadata) — this array is a direct projection of
 * it, not hand-written (the `as` cast only re-attaches the literal `TemplateId`
 * type that JSON imports otherwise widen to `string`; the actual values come
 * straight from the manifest). apps/api/app/services/pdf_export.py reads the
 * same file; apps/api/tests/unit/test_pdf_export_templates.py and
 * test_shared_template_source_guard.py assert both sides load the identical
 * set of ids.
 */
export const TEMPLATE_REGISTRY = manifest.templates as readonly TemplateDefinition[]

export const TEMPLATE_IDS: readonly TemplateId[] = TEMPLATE_REGISTRY.map((t) => t.id)

export function isTemplateId(value: string): value is TemplateId {
  return (TEMPLATE_IDS as readonly string[]).includes(value)
}
