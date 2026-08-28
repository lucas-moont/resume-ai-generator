import { describe, expect, it } from 'vitest'
import { translateInstruction } from './translateInstruction'

describe('translateInstruction (Furo 3B)', () => {
  it('asks for a pure translation into the target language', () => {
    expect(translateInstruction('en')).toMatch(/traduza.*inglês/i)
    expect(translateInstruction('pt-BR')).toMatch(/traduza.*português/i)
  })

  it('keeps the facts identical -- only the language changes (Q7)', () => {
    expect(translateInstruction('en')).toMatch(/idêntico/i)
  })

  it('is recognised as a language-change instruction by the backend (keys on "traduza")', () => {
    // mentions_language_change() keys on this verb, so the refine turn is licensed to switch the
    // document's language instead of pinning the current one.
    expect(translateInstruction('en').toLowerCase()).toContain('traduza')
  })
})
