import { create } from 'zustand'

/**
 * Whether the A4 preview is in inline-edit mode (the pencil toggle in
 * PreviewToolbar). Deliberately its own tiny store rather than a field on
 * resumeStore: it's UI/session state, not part of the resume document, and
 * doesn't need undo/redo history or persistence — reloading the page (or a
 * refine landing) should not silently leave the preview in edit mode.
 */
interface EditModeState {
  isEditing: boolean
  toggle: () => void
  setEditing: (isEditing: boolean) => void
}

export const useEditModeStore = create<EditModeState>((set) => ({
  isEditing: false,
  toggle: () => set((s) => ({ isEditing: !s.isEditing })),
  setEditing: (isEditing) => set({ isEditing }),
}))

export const useIsEditing = () => useEditModeStore((s) => s.isEditing)
