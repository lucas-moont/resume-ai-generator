/**
 * Furo 3B: the chat instruction the resume-screen language picker sends when the user switches
 * language. It reuses the normal chat refine path (Q13-A) rather than a dedicated endpoint, so
 * it must read as a language-change instruction the backend recognises (`mentions_language_change`
 * keys on "traduza"/"idioma"), and it must ask for a pure translation — same facts, only the
 * language changes (Q7) — which the server's per-section language gate then keeps single-language.
 */
export function translateInstruction(locale: string): string {
  const target = locale === 'en' ? 'inglês' : 'português'
  return `Traduza o currículo inteiro para ${target}, mantendo cada fato idêntico ao original — apenas o idioma muda.`
}
