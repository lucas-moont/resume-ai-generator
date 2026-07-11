import { describe, expect, it } from 'vitest'
import { server } from '../setup'
import { chatMessageStream } from '../../lib/api/endpoints'
import { makeProposal } from '../factories'
import {
  mockAdjustTurn,
  mockAnalysisError,
  mockAnalysisTurn,
  mockApproveChain,
  mockNewJdTurn,
  mockQuestionTurn,
} from './proposalScenarios'

/**
 * Smoke tests for the F2 scenario helpers themselves: each wraps a
 * makeXTurnEvents factory (src/test/factories.ts) around a real
 * chatMessageStream() call, pinning that the event sequences match
 * docs/v4-improvement-proposal.md §3.6 exactly — F3/F4/F5 consume these
 * by name, so a drift here would silently break every downstream suite.
 */
describe('proposal scenario handlers (v4, F2)', () => {
  async function collect(sessionId: number) {
    const events = []
    for await (const evt of await chatMessageStream(sessionId, { message: 'x' })) events.push(evt)
    return events
  }

  it('mockAnalysisTurn: stage(analyzing_job) -> proposal -> message -> done{proposalId, resumeVersionId:null}', async () => {
    const proposal = makeProposal({ proposalId: 1, revision: 1 })
    server.use(mockAnalysisTurn(1, proposal))

    const events = await collect(1)

    expect(events.map((e) => e.event)).toEqual(['stage', 'proposal', 'message', 'done'])
    expect(events[0]).toMatchObject({ data: { step: 'analyzing_job' } })
    expect(events[1]).toMatchObject({ data: proposal })
    expect(events[3]).toMatchObject({ data: { proposalId: 1, resumeVersionId: null } })
  })

  it('mockAdjustTurn: same proposalId, revision + 1', async () => {
    const revised = makeProposal({ proposalId: 1, revision: 2 })
    server.use(mockAdjustTurn(1, revised))

    const events = await collect(1)

    expect(events.map((e) => e.event)).toEqual(['stage', 'proposal', 'message', 'done'])
    expect(events[1]).toMatchObject({ data: { proposalId: 1, revision: 2 } })
    expect(events[3]).toMatchObject({ data: { proposalId: 1 } })
  })

  it('mockNewJdTurn: a fresh proposalId, status proposed', async () => {
    const fresh = makeProposal({ proposalId: 2, revision: 1, status: 'proposed' })
    server.use(mockNewJdTurn(1, fresh))

    const events = await collect(1)

    expect(events.map((e) => e.event)).toEqual(['stage', 'proposal', 'message', 'done'])
    expect(events[1]).toMatchObject({ data: { proposalId: 2, status: 'proposed' } })
  })

  it('mockQuestionTurn: no proposal event, pending proposal untouched', async () => {
    server.use(mockQuestionTurn(1, 1))

    const events = await collect(1)

    expect(events.map((e) => e.event)).toEqual(['stage', 'message', 'done'])
    expect(events[2]).toMatchObject({ data: { proposalId: 1 } })
  })

  it('mockApproveChain: message -> stage(...generation pipeline) -> resume -> message -> done{resumeVersionId, proposalId}', async () => {
    server.use(mockApproveChain(1, 1))

    const events = await collect(1)

    // Reuses the full preparing_context…finalizing pipeline (buildStageEvents), same as
    // makeChatTurnEvents — not a single stage frame.
    expect(events[0].event).toBe('message')
    expect(events.slice(1, -3).every((e) => e.event === 'stage')).toBe(true)
    expect(events.slice(-3).map((e) => e.event)).toEqual(['resume', 'message', 'done'])
    const done = events.at(-1) as { data: { resumeVersionId: number | null; proposalId: number } }
    expect(done.data.resumeVersionId).not.toBeNull()
    expect(done.data.proposalId).toBe(1)
  })

  it('mockAnalysisError: stage(analyzing_job) -> error, no proposal committed', async () => {
    server.use(mockAnalysisError(1))

    const events = await collect(1)

    expect(events.map((e) => e.event)).toEqual(['stage', 'error'])
    expect(events.some((e) => e.event === 'proposal')).toBe(false)
  })
})
