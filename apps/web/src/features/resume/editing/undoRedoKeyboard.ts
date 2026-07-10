import { useEffect } from 'react'
import { useResumeStore } from '../store/resumeStore'

/**
 * Ctrl/Cmd+Z undoes, Ctrl/Cmd+Shift+Z redoes — global, not scoped to the
 * pencil/edit-mode toggle (undoing a bad chat refine should work even if
 * inline editing was never turned on).
 *
 * Exception: while focus is inside a live contenteditable node (the user is
 * actively typing a field), the shortcut is left alone so the browser's own
 * native per-field undo handles it instead of jumping the WHOLE resume back
 * a version out from under an in-progress edit — see isFocusInsideContentEditable.
 */

export function matchesUndo(e: KeyboardEvent): boolean {
  return (e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z'
}

export function matchesRedo(e: KeyboardEvent): boolean {
  return (e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'z'
}

export function isFocusInsideContentEditable(): boolean {
  const el = document.activeElement
  return !!el && el.getAttribute('contenteditable') === 'true'
}

export function useUndoRedoShortcuts(): void {
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (isFocusInsideContentEditable()) return
      if (matchesRedo(e)) {
        e.preventDefault()
        useResumeStore.temporal.getState().redo()
      } else if (matchesUndo(e)) {
        e.preventDefault()
        useResumeStore.temporal.getState().undo()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])
}
