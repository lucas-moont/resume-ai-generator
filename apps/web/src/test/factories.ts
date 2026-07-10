import type { ResumeDocument } from '../types/resume'
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
