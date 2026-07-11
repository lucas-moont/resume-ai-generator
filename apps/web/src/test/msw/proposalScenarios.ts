import { http } from 'msw'
import type { ChatProposalEventPayload } from '../../lib/api/dto'
import {
  makeAdjustTurnEvents,
  makeAnalysisErrorEvents,
  makeAnalysisTurnEvents,
  makeApproveChainEvents,
  makeNewJdTurnEvents,
  makeProposal,
  makeQuestionTurnEvents,
} from '../factories'
import { sseResponse } from './sse'

/**
 * Ready-to-drop-in `server.use(...)` handlers for the Improvement Proposal turns
 * (docs/v4-improvement-proposal.md §3.6). Each wraps the matching `makeXTurnEvents`
 * factory (src/test/factories.ts) around the chat message-stream endpoint for a given
 * session id, so F3/F4/F5 suites don't hand-roll `http.post(url, () => sseResponse(...))`
 * per test. Default handlers in ./handlers.ts are untouched by this file.
 */
const streamUrl = (sessionId: number) => `/api/chat/sessions/${sessionId}/messages/stream`

export function mockAnalysisTurn(
  sessionId: number,
  proposal: ChatProposalEventPayload = makeProposal(),
  options?: Parameters<typeof makeAnalysisTurnEvents>[1],
) {
  return http.post(streamUrl(sessionId), () => sseResponse(makeAnalysisTurnEvents(proposal, options)))
}

export function mockAdjustTurn(
  sessionId: number,
  proposal: ChatProposalEventPayload,
  options?: Parameters<typeof makeAdjustTurnEvents>[1],
) {
  return http.post(streamUrl(sessionId), () => sseResponse(makeAdjustTurnEvents(proposal, options)))
}

export function mockNewJdTurn(
  sessionId: number,
  proposal: ChatProposalEventPayload,
  options?: Parameters<typeof makeNewJdTurnEvents>[1],
) {
  return http.post(streamUrl(sessionId), () => sseResponse(makeNewJdTurnEvents(proposal, options)))
}

export function mockQuestionTurn(
  sessionId: number,
  proposalId: number,
  options?: Parameters<typeof makeQuestionTurnEvents>[1],
) {
  return http.post(streamUrl(sessionId), () => sseResponse(makeQuestionTurnEvents(proposalId, options)))
}

export function mockApproveChain(
  sessionId: number,
  proposalId: number,
  options?: Parameters<typeof makeApproveChainEvents>[1],
) {
  return http.post(streamUrl(sessionId), () => sseResponse(makeApproveChainEvents(proposalId, options)))
}

export function mockAnalysisError(sessionId: number, options?: Parameters<typeof makeAnalysisErrorEvents>[0]) {
  return http.post(streamUrl(sessionId), () => sseResponse(makeAnalysisErrorEvents(options)))
}
