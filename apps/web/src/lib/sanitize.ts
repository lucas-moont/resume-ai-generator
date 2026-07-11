import DOMPurify from 'dompurify'

/**
 * Tags allowed in "rich" resume fields (headline, summary, highlights, project
 * descriptions, education details). Single source of truth shared by the
 * read-only renderer (SafeRichHtml) and the inline editor (EditableText) —
 * both the render-time and paste-time sanitization paths import from here so
 * they can never drift apart.
 */
export const RICH_HTML_ALLOWED_TAGS = ['strong', 'b', 'em', 'i', 'br', 'code'] as const

export function sanitizeRichHtml(html: string): string {
  return DOMPurify.sanitize(html || '', { ALLOWED_TAGS: [...RICH_HTML_ALLOWED_TAGS] })
}

/**
 * Strips ALL markup for "plain" fields (name, dates, skills, ...). Routed
 * through DOMPurify rather than a naive tag-stripping regex so `<script>` /
 * `<style>` content is dropped along with the tag, not just unwrapped into
 * visible text.
 */
export function sanitizePlainText(html: string): string {
  return DOMPurify.sanitize(html || '', { ALLOWED_TAGS: [] })
}
