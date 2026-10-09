export const TITLE_PREVIEW_MAX_LENGTH = 60

/** A conversation title built from the user's first message, at most
 * `TITLE_PREVIEW_MAX_LENGTH` characters. Counted by code point, not by `.length`: emoji and the
 * styled letters LinkedIn posts use take two UTF-16 units, and a `.slice` by units can cut one in
 * half. That half is not valid text, and the API cannot store it. */
export function titlePreview(message: string): string {
  const chars = Array.from(message)
  return chars.length > TITLE_PREVIEW_MAX_LENGTH
    ? `${chars.slice(0, TITLE_PREVIEW_MAX_LENGTH - 1).join('')}…`
    : message
}
