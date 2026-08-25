import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { JobListingDto } from '../../../lib/api/dto'
import { ApiError } from '../../../lib/api/client'
import { oneClickResume, openInChat } from '../../../lib/api/jobs'
import { useAppModeStore } from '../../../app/appModeStore'
import { CHAT_SESSIONS_QUERY_KEY, useResumeChatSession } from '../../chat/hooks/useChatSession'
import { downloadBlob } from '../../resume/downloadResumePdf'
import { LISTINGS_QUERY_ROOT, listingQueryKey } from './useListings'

/** v7 ticket 13 — the two actions on a Job Listing.
 *
 * One-click Resume is the one place in the product where a Resume is generated with the
 * Improvement Proposal auto-approved (CONTEXT.md), and the whole pipeline runs inside the single
 * POST that answers with the PDF. So there is no progress channel: the button is either idle,
 * spinning, or done — and "done" means the Listing Memory holds a Resume, which is why a second
 * click can ask for the SAME PDF (`regenerate=0`, no LLM) and only "Regerar" spends a call.
 */

/** Below this the backend refuses with 422 `description_too_short` (it runs
 * `looks_like_job_description` on the text). Mirrored here so the button is disabled BEFORE the
 * user spends a click and a round-trip on a refusal — the list response carries
 * `descriptionWordCount` for exactly this. A server 422 still latches the same state, because
 * the real predicate is the backend's and this number only approximates it. */
export const ONE_CLICK_MIN_WORDS = 30

export const TOO_SHORT_HINT = 'Descrição insuficiente — abra o link da vaga'

const GENERIC_ERROR = 'Não foi possível gerar o currículo desta vaga.'

/** Strips accents and anything that is not a letter or digit: a filename lands on the user's
 * filesystem, and "Acme Cloud · Engenheiro(a) Sênior" is not a name every OS accepts. */
export function slugifyForFileName(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

/** `curriculo-<empresa>-<cargo>.pdf`. Both parts are the user's own vocabulary for the job —
 * a downloads folder with ten `resume.pdf` files is the failure mode this avoids. */
export function oneClickFileName(listing: Pick<JobListingDto, 'company' | 'title'>): string {
  const parts = [slugifyForFileName(listing.company), slugifyForFileName(listing.title)].filter(
    (part) => part !== '',
  )
  return parts.length === 0 ? 'curriculo.pdf' : `curriculo-${parts.join('-')}.pdf`
}

/** The 502's `detail` is written by the backend to be acted on ("o provedor de IA não
 * respondeu"), so it is shown verbatim; the 422's is the CODE `description_too_short`, which is
 * not copy and must never reach the screen. */
function oneClickErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return GENERIC_ERROR
  if (error.status === 422) return TOO_SHORT_HINT
  return typeof error.detail === 'string' && error.detail.trim() !== ''
    ? error.detail
    : GENERIC_ERROR
}

export interface OneClickResumeState {
  /** False when the description cannot sustain a generation — the button is disabled and
   * `disabledReason` is its tooltip. */
  canGenerate: boolean
  disabledReason: string | null
  /** True once a PDF exists for this listing: from the Listing Memory (`hasOneClickResume`) or
   * because this session just generated one. Switches the UI to "Baixar PDF" + "Regerar". */
  hasResume: boolean
  isPending: boolean
  /** Which of the two buttons is spinning — `true` while "Regerar" runs, `false` otherwise. */
  pendingRegenerate: boolean
  error: string | null
  run: (regenerate: boolean) => void
}

export function useOneClickResume(listing: JobListingDto): OneClickResumeState {
  const queryClient = useQueryClient()
  const [generated, setGenerated] = useState(false)
  const [serverRefusedAsTooShort, setServerRefusedAsTooShort] = useState(false)
  const [pendingRegenerate, setPendingRegenerate] = useState(false)

  const mutation = useMutation({
    mutationFn: async (regenerate: boolean) => {
      const blob = await oneClickResume(listing.id, { regenerate })
      downloadBlob(blob, oneClickFileName(listing))
    },
    onMutate: (regenerate) => {
      setPendingRegenerate(regenerate)
    },
    onSuccess: () => {
      setGenerated(true)
      // The Listing Memory now holds a Resume for this identity: both the card and this detail
      // carry `hasOneClickResume`, and neither learns about it without a refetch.
      void queryClient.invalidateQueries({ queryKey: listingQueryKey(listing.id) })
      void queryClient.invalidateQueries({ queryKey: LISTINGS_QUERY_ROOT })
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 422) setServerRefusedAsTooShort(true)
    },
  })

  const tooShort =
    serverRefusedAsTooShort || listing.descriptionWordCount < ONE_CLICK_MIN_WORDS

  return {
    canGenerate: !tooShort,
    disabledReason: tooShort ? TOO_SHORT_HINT : null,
    hasResume: listing.hasOneClickResume || generated,
    isPending: mutation.isPending,
    pendingRegenerate,
    error: mutation.error == null ? null : oneClickErrorMessage(mutation.error),
    run: (regenerate: boolean) => mutation.mutate(regenerate),
  }
}

/** "Abrir no chat": the backend creates a normal `kind: 'resume'` session seeded with the
 * posting, and the frontend then does exactly what clicking that session in the sidebar does —
 * `resumeSession` hydrates the chat and resume stores — before switching the app to the resume
 * area. Hydrating INSIDE the mutation (not in `onSuccess`) is what makes a failure honest: if
 * the session cannot be loaded, the user stays in the Job Monitor with an error instead of
 * landing in an empty chat. */
export function useOpenInChat(listingId: number) {
  const queryClient = useQueryClient()
  const { resumeSession } = useResumeChatSession()
  const setMode = useAppModeStore((state) => state.setMode)

  return useMutation({
    mutationFn: async () => {
      const { sessionId } = await openInChat(listingId)
      await queryClient.invalidateQueries({ queryKey: CHAT_SESSIONS_QUERY_KEY })
      await resumeSession(sessionId)
      return sessionId
    },
    onSuccess: () => {
      setMode('resume')
    },
  })
}
