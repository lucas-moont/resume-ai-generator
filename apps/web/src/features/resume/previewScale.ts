export const A4_WIDTH_MM = 210
const CSS_PX_PER_MM = 3.7795275591
export const A4_WIDTH_PX = A4_WIDTH_MM * CSS_PX_PER_MM

/**
 * Scale factor (<=1) so a fixed-width A4 page fits within `containerWidthPx`.
 * Never scales up — a resume never needs to render bigger than its true A4
 * size on screen, even in a very wide preview pane.
 */
export function computeFitScale(containerWidthPx: number): number {
  if (containerWidthPx <= 0) return 1
  return Math.min(1, containerWidthPx / A4_WIDTH_PX)
}
