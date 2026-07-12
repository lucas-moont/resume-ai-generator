import {
  cloneElement,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent,
  type MouseEvent,
  type ReactElement,
  type Ref,
} from 'react'
import { createPortal } from 'react-dom'
import { zIndex } from './zIndex'

type Placement = 'top' | 'bottom'

/** The subset of trigger props Tooltip augments — it chains any handlers the
 *  child already declares rather than clobbering them. */
interface TriggerProps {
  ref?: Ref<HTMLElement>
  onMouseEnter?: (e: MouseEvent) => void
  onMouseLeave?: (e: MouseEvent) => void
  onFocus?: (e: FocusEvent) => void
  onBlur?: (e: FocusEvent) => void
  onKeyDown?: (e: KeyboardEvent) => void
}

/** Small delay before a hover tooltip appears, so quickly sweeping the cursor
 *  across a toolbar doesn't flash a trail of bubbles. Keyboard focus shows
 *  instantly (no equivalent noise, and waiting would feel unresponsive). */
const SHOW_DELAY_MS = 250

export interface TooltipProps {
  /** Visible tip text. The trigger keeps its own `aria-label` as the accessible
   *  name; the tooltip is a visual affordance (aria-hidden) and does not
   *  re-announce the control to screen readers. */
  label: string
  placement?: Placement
  /** A single focusable trigger element (typically an icon button). It must not
   *  need its own ref — Tooltip attaches one to measure its position. */
  children: ReactElement<TriggerProps>
}

/**
 * Styled, theme-aware tooltip that matches the app's design (unlike the native
 * `title=` attribute: OS-gray, ~1s delay, no dark mode). Portals the bubble to
 * `document.body` with fixed positioning so it's never clipped by an
 * `overflow` ancestor (the sidebar and preview panes both scroll), and flips
 * to the opposite side when the preferred one would run off the viewport.
 */
export function Tooltip({ label, placement = 'top', children }: TooltipProps) {
  const [open, setOpen] = useState(false)
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(null)
  const triggerRef = useRef<HTMLElement | null>(null)
  const tooltipRef = useRef<HTMLDivElement | null>(null)
  const showTimer = useRef<number | undefined>(undefined)

  const clearShowTimer = () => {
    if (showTimer.current !== undefined) {
      window.clearTimeout(showTimer.current)
      showTimer.current = undefined
    }
  }

  const show = useCallback((immediate: boolean) => {
    clearShowTimer()
    if (immediate) setOpen(true)
    else showTimer.current = window.setTimeout(() => setOpen(true), SHOW_DELAY_MS)
  }, [])

  const hide = useCallback(() => {
    clearShowTimer()
    setOpen(false)
    setCoords(null)
  }, [])

  useEffect(() => () => clearShowTimer(), [])

  // Position after the bubble is in the DOM (so its size is measurable) but
  // before paint — useLayoutEffect keeps it from flashing at the corner first.
  useLayoutEffect(() => {
    if (!open) return
    const trigger = triggerRef.current
    const tip = tooltipRef.current
    if (!trigger || !tip) return
    const anchor = trigger.getBoundingClientRect()
    const size = tip.getBoundingClientRect()
    const gap = 8
    const margin = 8

    let top = placement === 'bottom' ? anchor.bottom + gap : anchor.top - size.height - gap
    // Flip to the other side if the preferred one clips against a viewport edge.
    if (placement === 'top' && top < margin) top = anchor.bottom + gap
    else if (placement === 'bottom' && top + size.height > window.innerHeight - margin)
      top = anchor.top - size.height - gap

    let left = anchor.left + anchor.width / 2 - size.width / 2
    left = Math.max(margin, Math.min(left, window.innerWidth - size.width - margin))

    setCoords({ top, left })
  }, [open, placement, label])

  // A fixed-positioned bubble would drift from its anchor once the page scrolls
  // or resizes; tooltips are transient, so dismiss rather than chase.
  useEffect(() => {
    if (!open) return
    const dismiss = () => hide()
    window.addEventListener('scroll', dismiss, true)
    window.addEventListener('resize', dismiss)
    return () => {
      window.removeEventListener('scroll', dismiss, true)
      window.removeEventListener('resize', dismiss)
    }
  }, [open, hide])

  const setTriggerRef = useCallback((node: HTMLElement | null) => {
    triggerRef.current = node
  }, [])

  const child = children
  // setTriggerRef is a stable useCallback that only *writes* triggerRef in its
  // own callback (never reads a ref during render), so the rule's "may read a
  // ref during render" concern doesn't apply to this cloneElement.
  // eslint-disable-next-line react-hooks/refs
  const trigger = cloneElement(child, {
    ref: setTriggerRef,
    onMouseEnter: (e: MouseEvent) => {
      child.props.onMouseEnter?.(e)
      show(false)
    },
    onMouseLeave: (e: MouseEvent) => {
      child.props.onMouseLeave?.(e)
      hide()
    },
    onFocus: (e: FocusEvent) => {
      child.props.onFocus?.(e)
      show(true)
    },
    onBlur: (e: FocusEvent) => {
      child.props.onBlur?.(e)
      hide()
    },
    onKeyDown: (e: KeyboardEvent) => {
      child.props.onKeyDown?.(e)
      if (e.key === 'Escape') hide()
    },
  })

  return (
    <>
      {trigger}
      {open &&
        createPortal(
          <div
            ref={tooltipRef}
            // aria-hidden (and no role="tooltip"): the trigger's own aria-label
            // is the accessible name, so the bubble is a visual reinforcement
            // only — associating it too would make screen readers announce the
            // control twice.
            aria-hidden="true"
            className={`pointer-events-none fixed ${zIndex.tooltip} max-w-xs rounded-lg bg-stone-900 px-2.5 py-1.5 text-xs font-medium text-white shadow-lg ring-1 ring-black/5 dark:bg-zinc-100 dark:text-zinc-900 dark:ring-white/10`}
            // Pre-measurement (coords null): render offscreen so the layout
            // effect can size it without a visible flash at (0,0).
            style={coords ?? { top: -9999, left: -9999 }}
          >
            {label}
          </div>,
          document.body,
        )}
    </>
  )
}
