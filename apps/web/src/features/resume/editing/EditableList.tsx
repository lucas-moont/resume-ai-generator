import { useResumeStore } from '../store/resumeStore'
import { addListItem, removeListItem } from './fieldPaths'

/**
 * Floating +/- buttons for the three lists the preview lets a user grow or
 * shrink while editing: top-level `skills`/`education`, and per-experience
 * `experience.<i>.highlights`. Both render nothing when `!editable` — no
 * conditional wrapping needed at ResumePreview's call sites — and both carry
 * `no-print` so they never show up in `window.print()` output (the real
 * PDF export is server-rendered from the JSON document, not from this DOM,
 * so it never sees these buttons regardless).
 */

const buttonClassName =
  'no-print inline-flex h-5 w-5 items-center justify-center rounded-full border border-stone-300 bg-white text-xs font-semibold leading-none text-stone-600 shadow-sm transition-colors hover:border-stone-400 hover:bg-stone-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700'

export function ListAddButton({
  path,
  label,
  editable,
  className,
}: {
  path: string
  label: string
  editable: boolean
  className?: string
}) {
  if (!editable) return null

  const handleClick = () => {
    const { resume, setResume } = useResumeStore.getState()
    if (!resume) return
    setResume(addListItem(resume, path))
  }

  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={handleClick}
      className={`${buttonClassName} ${className ?? ''}`}
    >
      +
    </button>
  )
}

export function ListRemoveButton({
  path,
  index,
  label,
  editable,
  className,
}: {
  path: string
  index: number
  label: string
  editable: boolean
  className?: string
}) {
  if (!editable) return null

  const handleClick = () => {
    const { resume, setResume } = useResumeStore.getState()
    if (!resume) return
    setResume(removeListItem(resume, path, index))
  }

  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={handleClick}
      className={`${buttonClassName} ${className ?? ''}`}
    >
      −
    </button>
  )
}
