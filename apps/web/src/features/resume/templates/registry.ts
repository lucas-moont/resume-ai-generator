export interface TemplateDefinition {
  id: string
  label: string
  description: string
  tags: readonly string[]
}

/**
 * Single source of truth for which resume templates exist on the web side.
 * `TemplateId` is derived from this list (not hand-written), and
 * `apps/api/app/services/pdf_export.py`'s `_ALLOWED_TEMPLATES` must contain
 * the same ids — enforced by a contract test.
 */
export const TEMPLATE_REGISTRY = [
  {
    id: 'modern',
    label: 'Modern',
    description: 'Sidebar · indigo accent',
    tags: ['colorful', 'two-column'],
  },
  {
    id: 'classic',
    label: 'Classic',
    description: 'Serif · single column',
    tags: ['single-column', 'serif', 'conservative'],
  },
  {
    id: 'minimal',
    label: 'Minimal',
    description: 'Airy · monochrome',
    tags: ['single-column', 'monochrome', 'airy'],
  },
  {
    id: 'compact',
    label: 'Compact',
    description: 'Dense · content-rich',
    tags: ['two-column', 'dense'],
  },
  {
    id: 'ats-plain',
    label: 'ATS Plain',
    description: 'Single column · no color · max ATS compatibility',
    tags: ['ats-friendly', 'single-column', 'monochrome'],
  },
  {
    id: 'two-column-ats',
    label: 'Two-Column ATS',
    description: '2 columns · linear DOM order · ATS-safe',
    tags: ['ats-friendly', 'two-column', 'monochrome'],
  },
] as const satisfies readonly TemplateDefinition[]

export type TemplateId = (typeof TEMPLATE_REGISTRY)[number]['id']

export const TEMPLATE_IDS: readonly TemplateId[] = TEMPLATE_REGISTRY.map((t) => t.id)

export function isTemplateId(value: string): value is TemplateId {
  return (TEMPLATE_IDS as readonly string[]).includes(value)
}
