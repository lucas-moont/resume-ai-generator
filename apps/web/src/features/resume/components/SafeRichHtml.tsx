import { createElement } from 'react'
import DOMPurify from 'dompurify'

const RICH_HTML = {
  ALLOWED_TAGS: ['strong', 'b', 'em', 'i', 'br', 'code'],
}

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
  const clean = DOMPurify.sanitize(html || '', RICH_HTML)
  return createElement(as, {
    className,
    dangerouslySetInnerHTML: { __html: clean },
  })
}
