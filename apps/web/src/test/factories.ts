import type { ResumeDocument } from '../types/resume'
import type {
  ChatProposalEventPayload,
  PatchOp,
  ProposalItemDto,
  UploadSourceDocumentResponse,
} from '../lib/api/dto'
import type { MockSseEvent } from './msw/sse'

export function makeResume(overrides: Partial<ResumeDocument> = {}): ResumeDocument {
  return {
    fullName: 'Ada Lovelace',
    headline: 'Senior Software Engineer',
    location: 'Remote',
    email: 'ada@example.com',
    phone: '+1 555 0100',
    links: [{ label: 'GitHub', url: 'https://github.com/ada' }],
    summary: 'Experienced engineer building resilient distributed systems.',
    experience: [
      {
        company: 'Analytical Engines Inc.',
        title: 'Senior Software Engineer',
        location: 'Remote',
        start: '2021',
        end: null,
        highlights: [
          'Led the design of a distributed computation engine.',
          'Mentored a team of five engineers.',
        ],
      },
    ],
    projects: [{ name: 'Note G', description: 'A pioneering computational algorithm.' }],
    skills: ['TypeScript', 'Python', 'Distributed Systems'],
    education: [
      { institution: 'University of London', degree: 'B.Sc. Mathematics', end: '2010', details: null },
    ],
    locale: 'en',
    ...overrides,
  }
}

// Mirrors WORK_STEPS in App.tsx (~line 25). Kept as a local copy rather than
// importing from App.tsx, since F0 is infra-only and must not touch app
// logic; F1+ can replace this with a shared import once WORK_STEPS moves
// into lib/api.
const WORK_STEP_IDS = [
  'preparing_context',
  'extracting_profile_pdf',
  'calling_ai',
  'validating_response',
  'finalizing',
] as const

const STAGE_MESSAGES: Record<(typeof WORK_STEP_IDS)[number], string> = {
  preparing_context: 'Preparing context…',
  extracting_profile_pdf: 'Extracting profile from PDF…',
  calling_ai: 'Calling AI model…',
  validating_response: 'Validating response…',
  finalizing: 'Finalizing…',
}

/** The stage events every SSE fixture below starts with (shared by
 * makeStageEvents/makeChatTurnEvents/makeProfileUpdateTurnEvents). */
function buildStageEvents(): MockSseEvent[] {
  return WORK_STEP_IDS.map((step, idx) => ({
    event: 'stage',
    data: {
      step,
      progress: Math.round(((idx + 1) / (WORK_STEP_IDS.length + 1)) * 100),
      message: STAGE_MESSAGES[step],
    },
  }))
}

/** A realistic stage → done SSE sequence, as emitted by /api/generate/stream and /api/refine/stream. */
export function makeStageEvents(resume: ResumeDocument = makeResume()): MockSseEvent[] {
  return [...buildStageEvents(), { event: 'done', data: { progress: 100, resume } }]
}

/**
 * A realistic stage → resume → message → done SSE sequence, as emitted by
 * POST /api/chat/sessions/{id}/messages/stream (B6/F5) — unlike the legacy
 * generate/refine streams, the chat stream also carries a "resume" event
 * (the ResumeDocument + its version id) and a "message" event (the
 * assistant's chat bubble text).
 */
export function makeChatTurnEvents(
  resume: ResumeDocument = makeResume(),
  options: { content?: string; resumeVersionId?: number; messageId?: number } = {},
): MockSseEvent[] {
  const resumeVersionId = options.resumeVersionId ?? 1
  return [
    ...buildStageEvents(),
    { event: 'resume', data: { resume, resumeVersionId } },
    { event: 'message', data: { content: options.content ?? "I've updated your resume." } },
    { event: 'done', data: { progress: 100, messageId: options.messageId ?? 1, resumeVersionId } },
  ]
}

/**
 * A stage -> profile_update -> message -> done SSE sequence, as emitted for
 * the `profile_update` chat intent (v2, ticket 05/09) — unlike
 * makeChatTurnEvents, there is deliberately no "resume" event: this intent
 * never touches the active resume (the assistant only offers to regenerate
 * it via the following "message" event).
 */
export function makeProfileUpdateTurnEvents(
  options: { profileVersion?: number; summary?: string; content?: string; messageId?: number } = {},
): MockSseEvent[] {
  return [
    ...buildStageEvents(),
    {
      event: 'profile_update',
      data: {
        profileVersion: options.profileVersion ?? 2,
        summary: options.summary ?? 'Updated phone number.',
      },
    },
    {
      event: 'message',
      data: {
        content:
          options.content ??
          "I've updated your profile. Want me to regenerate your resume with this change?",
      },
    },
    { event: 'done', data: { progress: 100, messageId: options.messageId ?? 1, resumeVersionId: null } },
  ]
}

// --- Improvement Proposal (v4, F2) ---
// Contract per docs/v4-improvement-proposal.md §3.2/§3.5/§3.6 (frozen sequences).

export function makeProposalItem(overrides: Partial<ProposalItemDto> = {}): ProposalItemDto {
  return {
    id: 1,
    section: 'headline',
    current: 'Dev Backend',
    proposed: 'Backend Engineer especializado em sistemas distribuídos',
    rationale: 'A vaga pede experiência explícita com sistemas distribuídos e Python.',
    ...overrides,
  }
}

/** The `proposal` SSE event payload — also the shape of ChatMessageDto.proposal and
 * ChatSessionDetailResponse.pendingProposal on rehydration (§3.7: same DTO, live-joined). */
export function makeProposal(overrides: Partial<ChatProposalEventPayload> = {}): ChatProposalEventPayload {
  return {
    proposalId: 1,
    status: 'proposed',
    revision: 1,
    items: [makeProposalItem()],
    ...overrides,
  }
}

/** The `analyzing_job` heartbeat (§3.5), shared by the Analysis/adjust/new-JD/question turns —
 * typing dots on the frontend, never a ProgressCard. */
function buildAnalyzingJobStageEvents(): MockSseEvent[] {
  return [{ event: 'stage', data: { step: 'analyzing_job', progress: 50, message: 'Analyzing job description…' } }]
}

/** Shared shape of the Analysis / adjust / new-JD turns (§3.6): stage(analyzing_job) -> proposal
 * -> message -> done{proposalId, resumeVersionId:null}. The three differ only in what `proposal`
 * carries (fresh vs revision+1 vs a new proposalId) — the named wrappers below exist so call
 * sites read as the contract's own vocabulary. */
function buildProposalTurnEvents(
  proposal: ChatProposalEventPayload,
  options: { content?: string; messageId?: number } = {},
): MockSseEvent[] {
  return [
    ...buildAnalyzingJobStageEvents(),
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
export function makeAnalysisTurnEvents(
  proposal: ChatProposalEventPayload = makeProposal(),
  options: { content?: string; messageId?: number } = {},
): MockSseEvent[] {
  return buildProposalTurnEvents(proposal, options)
}

/** Adjust turn (proposta pendente revisada) — pass the ALREADY-bumped proposal (same
 * `proposalId`, `revision + 1`); this factory doesn't infer the bump for you. */
export function makeAdjustTurnEvents(
  proposal: ChatProposalEventPayload,
  options: { content?: string; messageId?: number } = {},
): MockSseEvent[] {
  return buildProposalTurnEvents(proposal, {
    content: options.content ?? 'Ajustei a proposta conforme pedido.',
    messageId: options.messageId,
  })
}

/** New JD turn (proposta pendente substituída) — pass the NEW proposal (different `proposalId`,
 * `status: 'proposed'`); the old one becoming `superseded` is a live-join concern for GET
 * /api/chat/sessions/{id} (§3.7), not carried by this stream frame. */
export function makeNewJdTurnEvents(
  proposal: ChatProposalEventPayload,
  options: { content?: string; messageId?: number } = {},
): MockSseEvent[] {
  return buildProposalTurnEvents(proposal, {
    content: options.content ?? 'Notei uma nova vaga colada — substituí a proposta anterior por esta.',
    messageId: options.messageId,
  })
}

/** Question turn (proposta pendente intocada): stage(analyzing_job) -> message ->
 * done{proposalId}. No `proposal` event — the pending proposal doesn't change. */
export function makeQuestionTurnEvents(
  proposalId: number,
  options: { content?: string; messageId?: number } = {},
): MockSseEvent[] {
  return [
    ...buildAnalyzingJobStageEvents(),
    {
      event: 'message',
      data: {
        content:
          options.content ?? 'Essa sugestão já leva em conta a experiência mencionada no seu currículo.',
      },
    },
    { event: 'done', data: { progress: 100, messageId: options.messageId ?? 2, resumeVersionId: null, proposalId } },
  ]
}

/** Approve chain (NL "pode fazer" or the button's `proposalAction: 'approve'`, §2/§3.6):
 * message(confirmação) -> stage(preparing_context…finalizing) -> resume -> message(final) ->
 * done{resumeVersionId, proposalId}. Reuses the same generation stage pipeline as
 * makeChatTurnEvents/makeStageEvents. */
export function makeApproveChainEvents(
  proposalId: number,
  options: {
    resume?: ResumeDocument
    resumeVersionId?: number
    confirmContent?: string
    finalContent?: string
    messageId?: number
  } = {},
): MockSseEvent[] {
  const resume = options.resume ?? makeResume()
  const resumeVersionId = options.resumeVersionId ?? 2
  return [
    { event: 'message', data: { content: options.confirmContent ?? 'Vou gerar o currículo com essas melhorias…' } },
    ...buildStageEvents(),
    { event: 'resume', data: { resume, resumeVersionId } },
    {
      event: 'message',
      data: { content: options.finalContent ?? 'Currículo atualizado com as melhorias aprovadas!' },
    },
    { event: 'done', data: { progress: 100, messageId: options.messageId ?? 3, resumeVersionId, proposalId } },
  ]
}

/** Analysis error (§6): LLM error / JSON lixo / timeout during the Analysis turn — the existing
 * error frame, no proposal ever committed. */
export function makeAnalysisErrorEvents(options: { message?: string } = {}): MockSseEvent[] {
  return [
    ...buildAnalyzingJobStageEvents(),
    { event: 'error', data: { message: options.message ?? 'Failed to analyze the job description.' } },
  ]
}

// --- Living Profile: Source Documents (v2, F7) ---

export function makePatchOp(overrides: Partial<PatchOp> = {}): PatchOp {
  return {
    op: 'add',
    path: '/skills/-',
    value: 'Rust',
    reason: 'New skill found in the uploaded document.',
    confidence: 0.92,
    sourceExcerpt: 'Proficient in Rust and systems programming.',
    ...overrides,
  }
}

export function makeUploadResponse(
  overrides: Partial<UploadSourceDocumentResponse> = {},
): UploadSourceDocumentResponse {
  return {
    documentId: 1,
    status: 'proposed',
    proposedPatch: [makePatchOp()],
    diffSummary: ['1 new skill: Rust'],
    extractedPreview: { skills: ['Rust'] },
    ...overrides,
  }
}
