import { describe, expect, it } from 'vitest'
import { TITLE_PREVIEW_MAX_LENGTH, titlePreview } from './titlePreview'

const hasLoneSurrogate = (s: string) => /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(s)

describe('titlePreview', () => {
  it('returns a short message unchanged', () => {
    expect(titlePreview('Vaga de backend')).toBe('Vaga de backend')
  })

  it('cuts a long message and ends it with an ellipsis', () => {
    const out = titlePreview('a'.repeat(100))
    expect(Array.from(out)).toHaveLength(TITLE_PREVIEW_MAX_LENGTH)
    expect(out.endsWith('…')).toBe(true)
  })

  it('never cuts a styled letter or emoji in half', () => {
    // Each bold letter is two UTF-16 units; a cut by .length lands mid-pair and leaves half of it.
    const bold = '\u{1D401}'.repeat(80)
    for (const message of [bold, `x${bold}`, `Senior Engineer ${bold}`, `${'a'.repeat(58)}😀😀😀`]) {
      expect(hasLoneSurrogate(titlePreview(message))).toBe(false)
    }
  })

  it('counts a styled letter as one character', () => {
    const bold = '\u{1D401}'.repeat(TITLE_PREVIEW_MAX_LENGTH)
    expect(titlePreview(bold)).toBe(bold)
  })
})
