import { useRef, useState, type KeyboardEvent, type ReactNode } from 'react'

export interface ComboboxOption {
  value: string
  label: string
}

export interface ComboboxProps {
  id: string
  value: string
  onChange: (value: string) => void
  /** Fired in addition to onChange when an option is chosen (click or Enter). */
  onSelect?: (option: ComboboxOption) => void
  options: ComboboxOption[]
  'aria-label': string
  placeholder?: string
  /** Rendered inside the listbox (as non-interactive content, not an option) when options is empty — avoids showing a phantom suggestion list while loading, erroring, or genuinely empty. */
  emptyState?: ReactNode
  /** Customizes each option's content. Defaults to the option's label. Active-option highlighting is handled by the aria-selected:* CSS variant on the <li>, not this callback. */
  renderOption?: (option: ComboboxOption) => ReactNode
  /** Class on the outer positioning wrapper (e.g. flex-layout sizing like `shrink-0`). */
  wrapperClassName?: string
  className?: string
  listClassName?: string
  /** Class applied to every <li role="option">. Defaults to a hover/active style consistent with the rest of the app. */
  optionClassName?: string
}

const DEFAULT_OPTION_CLASS_NAME =
  'flex w-full cursor-pointer flex-col items-start px-3 py-2 text-left text-sm hover:bg-stone-100 aria-selected:bg-stone-100 dark:hover:bg-zinc-800 dark:aria-selected:bg-zinc-800'

/** Blur closes the popup, but only after this delay — long enough for a
 * mousedown on an option (which fires before blur) to run its
 * preventDefault() and select handler first. */
const BLUR_CLOSE_DELAY_MS = 120

/**
 * ARIA 1.2 combobox+listbox primitive (v3 ticket 07): a text input that
 * stays free-typeable (the value is never coerced to match an option) while
 * offering a keyboard- and mouse-navigable dropdown of suggestions.
 */
function optionId(listboxId: string, index: number): string {
  return `${listboxId}-option-${index}`
}

export function Combobox({
  id,
  value,
  onChange,
  onSelect,
  options,
  'aria-label': ariaLabel,
  placeholder,
  emptyState,
  renderOption,
  wrapperClassName,
  className,
  listClassName,
  optionClassName,
}: ComboboxProps) {
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState<number | null>(null)
  const blurTimeoutRef = useRef<number | undefined>(undefined)
  const listboxId = `${id}-listbox`

  const close = () => {
    setOpen(false)
    setActiveIndex(null)
  }

  const select = (option: ComboboxOption) => {
    onChange(option.value)
    onSelect?.(option)
    close()
  }

  const moveActive = (delta: number) => {
    if (options.length === 0) return
    setActiveIndex((current) => {
      const base = current ?? (delta > 0 ? -1 : 0)
      return (base + delta + options.length) % options.length
    })
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        setOpen(true)
        moveActive(1)
        break
      case 'ArrowUp':
        e.preventDefault()
        setOpen(true)
        moveActive(-1)
        break
      case 'Home':
        if (!open || options.length === 0) return
        e.preventDefault()
        setActiveIndex(0)
        break
      case 'End':
        if (!open || options.length === 0) return
        e.preventDefault()
        setActiveIndex(options.length - 1)
        break
      case 'Enter':
        if (!open || activeIndex == null || !options[activeIndex]) return
        e.preventDefault()
        select(options[activeIndex])
        break
      case 'Escape':
        if (!open) return
        e.preventDefault()
        close()
        break
      default:
        break
    }
  }

  const handleBlur = () => {
    window.clearTimeout(blurTimeoutRef.current)
    blurTimeoutRef.current = window.setTimeout(close, BLUR_CLOSE_DELAY_MS)
  }

  return (
    <div className={`relative ${wrapperClassName ?? ''}`}>
      <input
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-label={ariaLabel}
        aria-autocomplete="list"
        aria-activedescendant={open && activeIndex != null ? optionId(listboxId, activeIndex) : undefined}
        value={value}
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setOpen(true)}
        onBlur={handleBlur}
        onKeyDown={handleKeyDown}
        className={className}
      />
      {open && (
        <ul id={listboxId} role="listbox" className={listClassName}>
          {options.length === 0
            ? emptyState != null && (
                <li aria-disabled="true" className="px-3 py-2 text-sm text-stone-500 dark:text-zinc-500">
                  {emptyState}
                </li>
              )
            : options.map((opt, index) => (
                <li
                  key={opt.value}
                  id={optionId(listboxId, index)}
                  role="option"
                  aria-selected={index === activeIndex}
                  onMouseDown={(e) => {
                    e.preventDefault()
                    select(opt)
                  }}
                  onMouseEnter={() => setActiveIndex(index)}
                  className={optionClassName ?? DEFAULT_OPTION_CLASS_NAME}
                >
                  {renderOption ? renderOption(opt) : opt.label}
                </li>
              ))}
        </ul>
      )}
    </div>
  )
}
