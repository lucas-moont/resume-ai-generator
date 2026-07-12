/**
 * Named z-index scale (v3 ticket 05, design debt e — was an arbitrary `z-20`
 * on the Composer's model dropdown). Ordered low-to-high; add new names
 * between existing ones rather than reusing raw numbers.
 */
export const zIndex = {
  /** Composer's drag-and-drop overlay indicator. */
  dropzone: 'z-10',
  /** Composer's model suggestion dropdown. */
  dropdown: 'z-20',
  /** Dialog primitive: backdrop + panel (see ./Dialog.tsx). Above any dropdown. */
  overlay: 'z-50',
  /** Tooltip bubble (see ./Tooltip.tsx). Above everything, including dialogs. */
  tooltip: 'z-[60]',
} as const
