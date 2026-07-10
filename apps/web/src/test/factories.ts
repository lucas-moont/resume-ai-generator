import type { ResumeDocument } from '../types/resume'
import type { PatchOp, UploadSourceDocumentResponse } from '../lib/api/dto'
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

/** A realistic stage → done SSE sequence, as emitted by /api/generate/stream and /api/refine/stream. */
export function makeStageEvents(resume: ResumeDocument = makeResume()): MockSseEvent[] {
  const stageEvents: MockSseEvent[] = WORK_STEP_IDS.map((step, idx) => ({
    event: 'stage',
    data: {
      step,
      progress: Math.round(((idx + 1) / (WORK_STEP_IDS.length + 1)) * 100),
      message: STAGE_MESSAGES[step],
    },
  }))
  return [...stageEvents, { event: 'done', data: { progress: 100, resume } }]
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
  const stageEvents: MockSseEvent[] = WORK_STEP_IDS.map((step, idx) => ({
    event: 'stage',
    data: {
      step,
      progress: Math.round(((idx + 1) / (WORK_STEP_IDS.length + 1)) * 100),
      message: STAGE_MESSAGES[step],
    },
  }))
  const resumeVersionId = options.resumeVersionId ?? 1
  return [
    ...stageEvents,
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
  const stageEvents: MockSseEvent[] = WORK_STEP_IDS.map((step, idx) => ({
    event: 'stage',
    data: {
      step,
      progress: Math.round(((idx + 1) / (WORK_STEP_IDS.length + 1)) * 100),
      message: STAGE_MESSAGES[step],
    },
  }))
  return [
    ...stageEvents,
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
