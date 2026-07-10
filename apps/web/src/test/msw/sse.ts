import { HttpResponse } from 'msw'

/**
 * One SSE frame as consumed by `runStreamRequest` in App.tsx (~line 148):
 * `event: <event>\ndata: <json>\n\n`.
 */
export interface MockSseEvent {
  event: 'stage' | 'resume' | 'message' | 'done' | 'error' | (string & {})
  data: unknown
  /** Wait before emitting this frame, to simulate real streaming pacing. */
  delayMs?: number
  /**
   * Split this frame's raw text into two separate stream chunks at this
   * character offset, to exercise the client's cross-chunk buffering
   * (`buffer += decoder.decode(...)` then split on "\n\n").
   */
  splitAt?: number
}

function frameText(evt: MockSseEvent): string {
  return `event: ${evt.event}\ndata: ${JSON.stringify(evt.data)}\n\n`
}

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

export function sseStream(events: MockSseEvent[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream<Uint8Array>({
    async start(controller) {
      for (const evt of events) {
        if (evt.delayMs) await wait(evt.delayMs)
        const text = frameText(evt)
        if (evt.splitAt !== undefined && evt.splitAt > 0 && evt.splitAt < text.length) {
          controller.enqueue(encoder.encode(text.slice(0, evt.splitAt)))
          await Promise.resolve()
          controller.enqueue(encoder.encode(text.slice(evt.splitAt)))
        } else {
          controller.enqueue(encoder.encode(text))
        }
      }
      controller.close()
    },
  })
}

/** Wrap `sseStream` in the MSW response an `http.post(...)` handler returns. */
export function sseResponse(events: MockSseEvent[]) {
  return new HttpResponse(sseStream(events), {
    status: 200,
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    },
  })
}
