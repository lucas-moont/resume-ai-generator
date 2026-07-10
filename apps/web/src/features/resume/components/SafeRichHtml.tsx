import { createElement } from 'react'
import { sanitizeRichHtml } from '../../../lib/sanitize'

type RichTag = 'p' | 'span' | 'div' | 'li' | 'h3'

export function SafeRichHtml({
  html,
  className,
  as = 'span',
}: {
  html: string
  className?: string
  as?: RichTag
}) {
  const clean = sanitizeRichHtml(html)
  return createElement(as, {
    className,
    dangerouslySetInnerHTML: { __html: clean },
  })
}
