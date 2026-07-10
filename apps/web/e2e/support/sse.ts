/**
 * Builds a complete SSE response body for `page.route(...).fulfill({ body, ... })`.
 * Unlike the Vitest/MSW helper (src/test/msw/sse.ts), this doesn't need to
 * simulate chunked delivery — Playwright's route.fulfill() always hands the
 * whole body to the browser's fetch in one go, and parseSseStream (already
 * unit-tested against fragmented chunks) handles that the same way it
 * handles any single complete read.
 */
export interface E2eSseEvent {
  event: 'stage' | 'resume' | 'message' | 'done' | 'error'
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
