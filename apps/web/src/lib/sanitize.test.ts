import { describe, expect, it } from 'vitest'
import { RICH_HTML_ALLOWED_TAGS, sanitizeRichHtml, sanitizePlainText } from './sanitize'

describe('sanitizeRichHtml', () => {
  it('keeps every tag in the shared rich allowlist', () => {
    const html = 'a <strong>b</strong> <b>c</b> <em>d</em> <i>e</i> f<br>g <code>h</code>'
    expect(sanitizeRichHtml(html)).toBe(html)
  })

  it('strips script tags and their content', () => {
    expect(sanitizeRichHtml('safe <script>alert(1)</script> text')).toBe('safe  text')
  })

  it('strips onerror/onclick attributes and other event handlers', () => {
    expect(sanitizeRichHtml('<strong onclick="steal()">click me</strong>')).toBe('<strong>click me</strong>')
  })

  it('strips img tags (including onerror payloads) entirely, keeping only allowlisted tags', () => {
    expect(sanitizeRichHtml('<img src=x onerror="alert(1)">before<b>after</b>')).toBe('before<b>after</b>')
  })

  it('strips disallowed tags like span/style but keeps their text content', () => {
    expect(sanitizeRichHtml('<span style="color:red">colored</span>')).toBe('colored')
  })

  it('treats empty/undefined input as an empty string', () => {
    expect(sanitizeRichHtml('')).toBe('')
  })

  it('exposes the allowlist so callers can stay in sync deliberately', () => {
    expect(RICH_HTML_ALLOWED_TAGS).toEqual(['strong', 'b', 'em', 'i', 'br', 'code'])
  })
})

describe('sanitizePlainText', () => {
  it('strips all tags but keeps their visible text', () => {
    expect(sanitizePlainText('<b>bold</b> and <em>italic</em>')).toBe('bold and italic')
  })

  it('strips script tags and their content (not just the tag)', () => {
    expect(sanitizePlainText('safe <script>alert(1)</script> text')).toBe('safe  text')
  })

  it('treats empty/undefined input as an empty string', () => {
    expect(sanitizePlainText('')).toBe('')
  })
})
