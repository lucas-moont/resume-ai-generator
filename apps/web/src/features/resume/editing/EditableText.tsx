import { useEffect, useRef } from 'react'
import type { KeyboardEvent, ClipboardEvent } from 'react'
import { sanitizePlainText, sanitizeRichHtml } from '../../../lib/sanitize'
import { useResumeStore } from '../store/resumeStore'
import { applyFieldEdit } from './fieldPaths'

/**
 * Drop-in leaf renderer for one field of the ResumeDocument, used at every
 * edit site inside ResumePreview. When `editable` is false it renders
 * exactly what the read-only preview always rendered (plain text node, or
 * sanitized rich HTML — same allowlist as SafeRichHtml). When `editable` is
 * true it becomes a contenteditable node following the pattern validated by
 * the ticket 06 spike:
 *
 *   - The JSX NEVER puts `value`/children/dangerouslySetInnerHTML on the
 *     contenteditable node. React only owns the element's existence,
 *     attributes and event handlers — never its text/HTML content while
 *     editable. Putting `value` back in the children here is exactly the
 *     regression the spike's "naive" comparison demonstrated (reversed
 *     keystroke order under real typing) — see e2e/inline-edit.spec.ts.
 *   - A single `useEffect` is the only writer of DOM content from props, and
 *     it's gated: it skips the write whenever the node currently has focus.
 *     That's what lets an external update (an SSE `resume` event landing
 *     mid-keystroke) leave the field the user is actively typing in alone —
 *     other, unfocused fields still resync immediately.
 *   - Commit is imperative: onBlur reads el.textContent (plain) or sanitizes
 *     el.innerHTML (rich) and writes it into the store via
 *     applyFieldEdit(resume, path, next). Enter in a plain field blurs
 *     (preventDefault + el.blur()) to reuse the same commit path; rich
 *     fields allow Enter as a normal newline/paragraph break.
 */

export type EditableMode = 'plain' | 'rich'
type Tag = 'span' | 'p' | 'li' | 'h1' | 'h3' | 'div'

export interface EditableTextProps {
  path: string
  value: string
  mode: EditableMode
  as?: Tag
  className?: string
  editable: boolean
}

export function EditableText({ path, value, mode, as = 'span', className, editable }: EditableTextProps) {
  const ref = useRef<HTMLElement | null>(null)
  const lastCommitted = useRef(value)
  const El = as

  // The ONLY place `value` (i.e. whatever setResume/SSE last pushed) ever
  // touches the DOM while editable. Gated by focus — see module doc above.
  useEffect(() => {
    if (!editable) return
    const el = ref.current
    if (!el) return
    if (document.activeElement === el) return
    if (mode === 'rich') {
      el.innerHTML = sanitizeRichHtml(value)
    } else {
      el.textContent = value || ''
    }
    lastCommitted.current = value
  }, [value, mode, editable])

  if (!editable) {
    return mode === 'rich' ? (
      <El className={className} data-field={path} dangerouslySetInnerHTML={{ __html: sanitizeRichHtml(value) }} />
    ) : (
      <El className={className} data-field={path}>
        {value}
      </El>
    )
  }

  const commit = () => {
    const el = ref.current
    if (!el) return
    const next = mode === 'rich' ? sanitizeRichHtml(el.innerHTML) : el.textContent || ''
    if (next === lastCommitted.current) return
    lastCommitted.current = next
    const { resume, setResume } = useResumeStore.getState()
    if (!resume) return
    setResume(applyFieldEdit(resume, path, next))
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key === 'Enter' && mode === 'plain') {
      e.preventDefault()
      e.currentTarget.blur()
    }
  }

  const handlePaste = (e: ClipboardEvent<HTMLElement>) => {
    e.preventDefault()
    if (mode === 'rich') {
      const raw = e.clipboardData.getData('text/html') || e.clipboardData.getData('text/plain')
      document.execCommand('insertHTML', false, sanitizeRichHtml(raw))
    } else {
      const raw = e.clipboardData.getData('text/plain')
      document.execCommand('insertText', false, sanitizePlainText(raw))
    }
  }

  return (
    <El
      ref={ref as never}
      contentEditable
      suppressContentEditableWarning
      className={className}
      data-field={path}
      onBlur={commit}
      onKeyDown={handleKeyDown}
      onPaste={handlePaste}
    />
  )
}
