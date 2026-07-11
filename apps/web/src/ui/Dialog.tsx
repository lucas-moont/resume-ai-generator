import { useEffect, useId, useRef, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { zIndex } from './zIndex'

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

function getFocusableElements(container: HTMLElement | null): HTMLElement[] {
  if (!container) return []
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
}

export interface DialogProps {
  open: boolean
  onClose: () => void
  /** Rendered as the dialog's heading and wired as its accessible name. */
  title: string
  /** Rendered under the title and wired as the dialog's accessible description. */
  description?: ReactNode
  children: ReactNode
  /** Element to focus when the dialog opens. Defaults to the first focusable element inside it. */
  initialFocusRef?: RefObject<HTMLElement | null>
  className?: string
}

/**
 * Modal dialog primitive: owns focus trap, Escape-to-close, focus return,
 * ARIA wiring, and scroll lock. Rendered via portal to `document.body`
 * rather than the native `<dialog>` element — jsdom (the test environment)
 * doesn't implement `showModal()`, which would make the primitive
 * untestable; a portal gives the same stacking/focus guarantees under full
 * manual control.
 *
 * Assumes a single open Dialog at a time: two simultaneously-open instances
 * would each install their own document-level keydown listener and
 * body-scroll-lock cleanup, and would fight over both. Nesting a second
 * Dialog (e.g. a confirmation inside a Settings dialog) needs that revisited.
 */
export function Dialog({ open, onClose, title, description, children, initialFocusRef, className }: DialogProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const previouslyFocusedRef = useRef<HTMLElement | null>(null)
  const titleId = useId()
  const descriptionId = useId()

  useEffect(() => {
    if (!open) return

    previouslyFocusedRef.current = document.activeElement as HTMLElement | null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const focusTarget = initialFocusRef?.current ?? getFocusableElements(containerRef.current)[0] ?? containerRef.current
    focusTarget?.focus()

    return () => {
      document.body.style.overflow = previousOverflow
      previouslyFocusedRef.current?.focus()
    }
    // initialFocusRef/onClose are read once per open, not re-run on identity churn
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    if (!open) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
        return
      }
      if (e.key !== 'Tab') return

      const focusable = getFocusableElements(containerRef.current)
      if (focusable.length === 0) {
        e.preventDefault()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const active = document.activeElement

      if (e.shiftKey) {
        if (active === first || !containerRef.current?.contains(active)) {
          e.preventDefault()
          last.focus()
        }
      } else if (active === last || !containerRef.current?.contains(active)) {
        e.preventDefault()
        first.focus()
      }
    }

    // Capture phase: a descendant (e.g. a combobox or menu) calling
    // stopPropagation() on keydown must not be able to swallow Escape or
    // break the focus trap before it reaches us.
    document.addEventListener('keydown', handleKeyDown, { capture: true })
    return () => document.removeEventListener('keydown', handleKeyDown, { capture: true })
  }, [open, onClose])

  if (!open) return null

  return createPortal(
    <div
      className={`fixed inset-0 ${zIndex.overlay} flex items-center justify-center bg-stone-950/40 p-4 dark:bg-black/60`}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        // Documents the shortcut this primitive already implements above
        // (capture-phase keydown listener) — every dialog in the app (v3
        // ticket 09's keyboard-shortcuts polish) closes on Escape.
        aria-keyshortcuts="Escape"
        tabIndex={-1}
        className={`w-full max-w-sm rounded-2xl border border-stone-200 bg-white p-5 shadow-xl dark:border-zinc-700 dark:bg-zinc-900 ${className ?? ''}`}
      >
        <h2 id={titleId} className="text-base font-semibold text-stone-900 dark:text-zinc-100">
          {title}
        </h2>
        {description && (
          <p id={descriptionId} className="mt-1 text-sm text-stone-600 dark:text-zinc-400">
            {description}
          </p>
        )}
        <div className="mt-3">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
