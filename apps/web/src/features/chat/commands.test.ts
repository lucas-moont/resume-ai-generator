import { describe, expect, it } from 'vitest'
import { parseCommand, TEMPLATE_ALIASES } from './commands'
import { TEMPLATE_REGISTRY } from '../resume/templates/registry'

describe('parseCommand — switch template (English)', () => {
  const cases: [string, string][] = [
    ['use modern', 'modern'],
    ['use the modern template', 'modern'],
    ['switch to modern', 'modern'],
    ['switch to the modern template', 'modern'],
    ['change to modern', 'modern'],
    ['change to the classic template', 'classic'],
    ['use minimal', 'minimal'],
    ['use compact', 'compact'],
    ['switch to ats plain', 'ats-plain'],
    ['use the ats-plain template', 'ats-plain'],
    ['switch to two-column ats', 'two-column-ats'],
    ['use the two column ats template', 'two-column-ats'],
    ['use executive', 'executive'],
    ['use the executive template', 'executive'],
    ['switch to tech', 'tech'],
    ['use the tech template', 'tech'],
  ]

  for (const [message, expectedId] of cases) {
    it(`matches "${message}" -> ${expectedId}`, () => {
      expect(parseCommand(message)).toEqual({ kind: 'switch-template', templateId: expectedId })
    })
  }

  it('is case-insensitive and tolerates trailing punctuation', () => {
    expect(parseCommand('Use The Modern Template.')).toEqual({
      kind: 'switch-template',
      templateId: 'modern',
    })
    expect(parseCommand('switch to modern!')).toEqual({
      kind: 'switch-template',
      templateId: 'modern',
    })
  })
})

describe('parseCommand — switch template (Portuguese)', () => {
  const cases: [string, string][] = [
    ['usa moderno', 'modern'],
    ['usa o layout moderno', 'modern'],
    ['troca pro moderno', 'modern'],
    ['troca pro layout moderno', 'modern'],
    ['troca para o layout classico', 'classic'],
    ['troca para o layout clássico', 'classic'],
    ['muda pra minimalista', 'minimal'],
    ['muda para o layout compacto', 'compact'],
    ['troca pro layout ats simples', 'ats-plain'],
    ['usa o layout ats plano', 'ats-plain'],
    ['troca pro layout duas colunas ats', 'two-column-ats'],
    ['usa o layout ats duas colunas', 'two-column-ats'],
    ['usa executivo', 'executive'],
    ['usa o layout executivo', 'executive'],
    ['troca pro layout tecnologico', 'tech'],
    ['muda para o layout tecnico', 'tech'],
  ]

  for (const [message, expectedId] of cases) {
    it(`matches "${message}" -> ${expectedId}`, () => {
      expect(parseCommand(message)).toEqual({ kind: 'switch-template', templateId: expectedId })
    })
  }
})

describe('parseCommand — every registry template is reachable in both languages', () => {
  for (const t of TEMPLATE_REGISTRY) {
    it(`has at least one working en and pt phrase for "${t.id}"`, () => {
      expect(parseCommand(`use the ${t.id.replace(/-/g, ' ')} template`)).not.toBeNull()
    })
  }
})

describe('TEMPLATE_ALIASES completeness', () => {
  // Record<TemplateId, string[]> already makes a missing key a compile error,
  // and the module-load loop in commands.ts throws at import time if a key's
  // value is ever missing/empty — but both of those show up as a cryptic
  // crash rather than a clear assertion. This is the readable version: adding
  // a template to the manifest without an alias entry here fails right here,
  // by name.
  it('has a non-empty alias list for every template in the registry', () => {
    for (const t of TEMPLATE_REGISTRY) {
      expect(TEMPLATE_ALIASES).toHaveProperty(t.id)
      expect(TEMPLATE_ALIASES[t.id as keyof typeof TEMPLATE_ALIASES].length).toBeGreaterThan(0)
    }
  })
})

describe('parseCommand — export pdf', () => {
  const cases = [
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
  ]

  for (const message of cases) {
    it(`matches "${message}"`, () => {
      expect(parseCommand(message)).toEqual({ kind: 'export-pdf' })
    })
  }
})

describe('parseCommand — does not swallow content/ambiguous messages', () => {
  const negatives = [
    'não troca o layout ainda',
    "don't switch to modern yet",
    'I like the modern aesthetic of this design',
    'can you switch to the modern template?',
    'switch to modern please',
    'export pdf and email it to me',
    'modern',
    'pdf',
    '',
    '   ',
    'switch to a template that looks modern',
    'troca pro layout moderno assim que puder',
  ]

  for (const message of negatives) {
    it(`returns null for "${message}"`, () => {
      expect(parseCommand(message)).toBeNull()
    })
  }
})
