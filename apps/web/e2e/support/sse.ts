/**
 * Builds a complete SSE response body for `page.route(...).fulfill({ body, ... })`.
 * Unlike the Vitest/MSW helper (src/test/msw/sse.ts), this doesn't need to
 * simulate chunked delivery — Playwright's route.fulfill() always hands the
 * whole body to the browser's fetch in one go, and parseSseStream (already
 * unit-tested against fragmented chunks) handles that the same way it
 * handles any single complete read.
 */
export interface E2eSseEvent {
  event: 'stage' | 'resume' | 'message' | 'profile_update' | 'proposal' | 'analysis' | 'done' | 'error'
  data: unknown
}

export function sseBody(events: E2eSseEvent[]): string {
  return events.map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`).join('')
}

export const SSE_HEADERS = {
  'Content-Type': 'text/event-stream',
  'Cache-Control': 'no-cache',
  Connection: 'keep-alive',
}

// --- Improvement Proposal (v4, F2) ---
// Mirrors src/test/factories.ts's makeXTurnEvents (docs/v4-improvement-proposal.md §3.5/§3.6),
// one-to-one, so proposal-flow.spec.ts reads the same as the Vitest/MSW suites. Pass the result
// straight to sseBody(...) in a page.route(...).fulfill({ body: ... }) call.

interface E2eProposal {
  proposalId: number
  status: 'proposed' | 'approved' | 'superseded' | 'discarded'
  revision: number
  items: unknown[]
}

/** The `analyzing_job` heartbeat (§3.5) shared by the Analysis/adjust/new-JD/question turns. */
function analyzingJobStageEvent(): E2eSseEvent {
  return { event: 'stage', data: { step: 'analyzing_job', progress: 50, message: 'Analyzing job description…' } }
}

function proposalTurnEvents(
  proposal: E2eProposal,
  options: { content?: string; messageId?: number } = {},
): E2eSseEvent[] {
  return [
    analyzingJobStageEvent(),
    { event: 'proposal', data: proposal },
    {
      event: 'message',
      data: { content: options.content ?? 'Aqui estão minhas sugestões de melhoria para essa vaga.' },
    },
    {
      event: 'done',
      data: {
        progress: 100,
        messageId: options.messageId ?? 1,
        resumeVersionId: null,
        proposalId: proposal.proposalId,
      },
    },
  ]
}

/** Analysis turn (JD colada, sem proposta pendente). */
export function analysisTurnEvents(
  proposal: E2eProposal,
  options: { content?: string; messageId?: number } = {},
): E2eSseEvent[] {
  return proposalTurnEvents(proposal, options)
}

/** Adjust turn (proposta pendente revisada) — pass the ALREADY-bumped proposal (same
 * `proposalId`, `revision + 1`). */
export function adjustTurnEvents(
  proposal: E2eProposal,
  options: { content?: string; messageId?: number } = {},
): E2eSseEvent[] {
  return proposalTurnEvents(proposal, {
    content: options.content ?? 'Ajustei a proposta conforme pedido.',
    messageId: options.messageId,
  })
}

/** New JD turn (proposta pendente substituída) — pass the NEW proposal (different `proposalId`,
 * `status: 'proposed'`); the old one becoming `superseded` is a live-join concern for GET
 * /api/chat/sessions/{id} (§3.7), not carried by this stream frame. */
export function newJdTurnEvents(
  proposal: E2eProposal,
  options: { content?: string; messageId?: number } = {},
): E2eSseEvent[] {
  return proposalTurnEvents(proposal, {
    content: options.content ?? 'Notei uma nova vaga colada — substituí a proposta anterior por esta.',
    messageId: options.messageId,
  })
}

/** Question turn (proposta pendente intocada): stage(analyzing_job) -> message ->
 * done{proposalId}. No `proposal` event — the pending proposal doesn't change. */
export function questionTurnEvents(
  proposalId: number,
  options: { content?: string; messageId?: number } = {},
): E2eSseEvent[] {
  return [
    analyzingJobStageEvent(),
    {
      event: 'message',
      data: {
        content: options.content ?? 'Essa sugestão já leva em conta a experiência mencionada no seu currículo.',
      },
    },
    { event: 'done', data: { progress: 100, messageId: options.messageId ?? 2, resumeVersionId: null, proposalId } },
  ]
}

/** Approve chain (NL "pode fazer" or the button's `proposalAction: 'approve'`, §2/§3.6):
 * message(confirmação) -> stage(preparing_context…finalizing) -> resume -> message(final) ->
 * done{resumeVersionId, proposalId}. */
export function approveChainEvents(
  proposalId: number,
  options: {
    resume?: unknown
    resumeVersionId?: number
    confirmContent?: string
    finalContent?: string
    messageId?: number
  } = {},
): E2eSseEvent[] {
  const resumeVersionId = options.resumeVersionId ?? 2
  return [
    { event: 'message', data: { content: options.confirmContent ?? 'Vou gerar o currículo com essas melhorias…' } },
    { event: 'stage', data: { step: 'finalizing', progress: 90, message: 'Finalizing…' } },
    { event: 'resume', data: { resume: options.resume, resumeVersionId } },
    {
      event: 'message',
      data: { content: options.finalContent ?? 'Currículo atualizado com as melhorias aprovadas!' },
    },
    { event: 'done', data: { progress: 100, messageId: options.messageId ?? 3, resumeVersionId, proposalId } },
  ]
}

/** Analysis error (§6): LLM error / JSON lixo / timeout during the Analysis turn — the existing
 * error frame, no proposal ever committed. */
export function analysisErrorEvents(options: { message?: string } = {}): E2eSseEvent[] {
  return [
    analyzingJobStageEvent(),
    { event: 'error', data: { message: options.message ?? 'Failed to analyze the job description.' } },
  ]
}

// --- Profile Analysis (v5) ---
// Mirrors analysis_service.py's event sequences (b3): an analysis turn emits
// stage -> analysis (card) -> message (summary) -> done; a clarifying-question / fallback turn
// emits stage -> message (reply) -> done (no card).

function analyzingProfileStageEvent(): E2eSseEvent {
  return { event: 'stage', data: { step: 'analyzing_profile', progress: 40, message: 'Analyzing your profile' } }
}

export function profileAnalysisEvents(
  items: unknown[],
  summary: string,
  options: { messageId?: number } = {},
): E2eSseEvent[] {
  return [
    analyzingProfileStageEvent(),
    { event: 'analysis', data: { items, summary } },
    { event: 'message', data: { content: summary } },
    { event: 'done', data: { progress: 100, messageId: options.messageId ?? 2, resumeVersionId: null } },
  ]
}

export function profileAnalysisQuestionEvents(
  reply: string,
  options: { messageId?: number } = {},
): E2eSseEvent[] {
  return [
    analyzingProfileStageEvent(),
    { event: 'message', data: { content: reply } },
    { event: 'done', data: { progress: 100, messageId: options.messageId ?? 1, resumeVersionId: null } },
  ]
}

export function makeAnalysisItem(overrides: Record<string, unknown> = {}) {
  return {
    section: 'headline',
    current: 'Dev',
    suggestion: 'Desenvolvedor Backend | Python & APIs | Alta disponibilidade',
    rationale: 'Front-load os termos que recruiters buscam.',
    priority: 'alta',
    ...overrides,
  }
}
