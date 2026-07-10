import { TEMPLATE_REGISTRY, type TemplateId } from '../resume/templates/registry'

export type ParsedCommand =
  | { kind: 'switch-template'; templateId: TemplateId }
  | { kind: 'export-pdf' }

const COMBINING_DIACRITICS = /[̀-ͯ]/g

function normalize(message: string): string {
  return message
    .normalize('NFD')
    .replace(COMBINING_DIACRITICS, '') // strip accents (á -> a, ç -> c, ...)
    .trim()
    .toLowerCase()
    .replace(/[.!?]+$/, '') // tolerate trailing sentence punctuation
    .replace(/\s+/g, ' ')
    .trim()
}

// English/Portuguese names recognized for each template id. Deliberately a
// closed, enumerable list (not free-form NLP) so every phrase is testable.
const TEMPLATE_ALIASES: Record<TemplateId, string[]> = {
  modern: ['modern', 'moderno', 'moderna'],
  classic: ['classic', 'classico', 'classica'],
  minimal: ['minimal', 'minimalista'],
  compact: ['compact', 'compacto', 'compacta'],
  'ats-plain': ['ats plain', 'ats-plain', 'plain ats', 'ats simples', 'ats plano'],
  'two-column-ats': [
    'two column ats',
    'two-column ats',
    'two-column-ats',
    '2 column ats',
    '2-column ats',
    'duas colunas ats',
    'ats duas colunas',
    '2 colunas ats',
  ],
}

const EN_SWITCH_VERBS = ['use', 'switch to', 'change to']
const EN_ARTICLES = ['', 'the ']
const EN_NOUN_SUFFIXES = ['', ' template', ' layout']

// Portuguese puts the noun (layout/template) BEFORE the template name, unlike
// English ("troca pro layout moderno" vs "use the modern template").
const PT_SWITCH_VERBS = ['usa', 'troca pro', 'troca para', 'muda pra', 'muda para']
const PT_NOUN_PREFIXES = ['', 'o layout ', 'layout ', 'o template ', 'template ']

const SWITCH_TEMPLATE_PHRASES = new Map<string, TemplateId>()

for (const template of TEMPLATE_REGISTRY) {
  for (const alias of TEMPLATE_ALIASES[template.id]) {
    for (const verb of EN_SWITCH_VERBS) {
      for (const article of EN_ARTICLES) {
        for (const noun of EN_NOUN_SUFFIXES) {
          SWITCH_TEMPLATE_PHRASES.set(normalize(`${verb} ${article}${alias}${noun}`), template.id)
        }
      }
    }
    for (const verb of PT_SWITCH_VERBS) {
      for (const nounPrefix of PT_NOUN_PREFIXES) {
        SWITCH_TEMPLATE_PHRASES.set(normalize(`${verb} ${nounPrefix}${alias}`), template.id)
      }
    }
  }
}

const EXPORT_PDF_PHRASES = new Set(
  [
    'export pdf',
    'export the pdf',
    'download pdf',
    'download the pdf',
    'export as pdf',
    'exporta o pdf',
    'exporta pdf',
    'baixa o pdf',
    'baixa pdf',
    'baixar o pdf',
    'download do pdf',
  ].map(normalize),
)

/**
 * Deterministic, client-side command parser: recognizes template switches and
 * PDF export requests only when the ENTIRE message is the command — never a
 * substring match. Anything else (ambiguous phrasing, negations, questions,
 * regular content) returns null, so the caller routes the message to the LLM
 * instead of silently swallowing it.
 */
export function parseCommand(message: string): ParsedCommand | null {
  const normalized = normalize(message)
  if (!normalized) return null

  if (EXPORT_PDF_PHRASES.has(normalized)) {
    return { kind: 'export-pdf' }
  }

  const templateId = SWITCH_TEMPLATE_PHRASES.get(normalized)
  if (templateId) {
    return { kind: 'switch-template', templateId }
  }

  return null
}
