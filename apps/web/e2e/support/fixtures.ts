/** A ResumeDocument matching apps/web/src/types/resume.ts, for e2e response bodies. */
export function makeResume(overrides: Record<string, unknown> = {}) {
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
        highlights: ['Led the design of a distributed computation engine.'],
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

// --- Improvement Proposal (v4, F2) ---
// Mirrors src/test/factories.ts's makeProposalItem/makeProposal (docs/v4-improvement-proposal.md
// §3.2/§3.7) — loosely typed like makeResume above, since e2e specs build page.route JSON bodies
// rather than importing src/lib/api/dto types.

export function makeProposalItem(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    section: 'headline',
    current: 'Dev Backend',
    proposed: 'Backend Engineer especializado em sistemas distribuídos',
    rationale: 'A vaga pede experiência explícita com sistemas distribuídos e Python.',
    ...overrides,
  }
}

/** The `proposal` SSE event payload — also the shape of a rehydrated message's `proposal` field
 * and ChatSessionDetailResponse.pendingProposal (§3.7: same DTO, live-joined). */
export function makeProposal(overrides: Record<string, unknown> = {}) {
  return {
    proposalId: 1,
    status: 'proposed',
    revision: 1,
    items: [makeProposalItem()],
    ...overrides,
  }
}

export const RESUME_STORAGE_KEY = 'resume-agent:resume'

/** localStorage payload matching resumeStore's zustand `persist` format (see F2). */
export function resumeStorageValue(
  resume: ReturnType<typeof makeResume> | null,
  template = 'modern',
  locale = 'auto',
): string {
  return JSON.stringify({ state: { resume, template, locale }, version: 1 })
}
