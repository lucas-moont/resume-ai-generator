import { describe, expect, it } from 'vitest'
import { parseSseStream } from './sse'
import { sseResponse, type MockSseEvent } from '../../test/msw/sse'

function rawResponse(chunks: string[]): Response {
  const encoder = new TextEncoder()
  let i = 0
  return new Response(
    new ReadableStream<Uint8Array>({
      pull(controller) {
        if (i >= chunks.length) {
          controller.close()
          return
        }
        controller.enqueue(encoder.encode(chunks[i++]))
      },
    }),
  )
}

async function collect<T>(gen: AsyncGenerator<T>): Promise<T[]> {
  const items: T[] = []
  for await (const item of gen) items.push(item)
  return items
}

describe('parseSseStream', () => {
  it('parses a single frame', async () => {
    const events: MockSseEvent[] = [{ event: 'stage', data: { step: 'calling_ai', progress: 40 } }]

    await expect(collect(parseSseStream(sseResponse(events)))).resolves.toEqual(events)
  })

  it('parses multiple frames delivered across the stream', async () => {
    const events: MockSseEvent[] = [
      { event: 'stage', data: { step: 'preparing_context' } },
      { event: 'stage', data: { step: 'calling_ai' } },
      { event: 'done', data: { resume: { fullName: 'Ada Lovelace' } } },
    ]

    await expect(collect(parseSseStream(sseResponse(events)))).resolves.toEqual(events)
  })

  it('parses a frame that arrives split across two stream chunks', async () => {
    const events: MockSseEvent[] = [
      { event: 'stage', data: { step: 'calling_ai', progress: 40 }, splitAt: 15 },
    ]

    await expect(collect(parseSseStream(sseResponse(events)))).resolves.toEqual([
      { event: 'stage', data: { step: 'calling_ai', progress: 40 } },
    ])
  })

  it('joins multiple data: lines within one frame per the SSE spec', async () => {
    // The MockSseEvent helper always emits one `data:` line per event, so
    // this exercises the raw multi-line wire format directly instead.
    const frame = 'event: message\ndata: {\ndata:   "content": "hi"\ndata: }\n\n'

    await expect(collect(parseSseStream(rawResponse([frame])))).resolves.toEqual([
      { event: 'message', data: { content: 'hi' } },
    ])
  })

  it('yields an "error" event\'s payload as-is — the parser is semantics-free', async () => {
    // parseSseStream doesn't know about stage/done/error; deciding to throw
    // on an "error" event is the caller's job (see endpoints.ts / App.tsx's
    // runStreamEvents), not the parser's.
    const events: MockSseEvent[] = [{ event: 'error', data: { message: 'model unavailable' } }]

    await expect(collect(parseSseStream(sseResponse(events)))).resolves.toEqual(events)
  })

  it('throws a SyntaxError on invalid JSON in a data: line', async () => {
    // Documented choice: throw (not skip), matching the pre-extraction
    // runStreamRequest, which also called JSON.parse with no try/catch.
    // Callers already handle stream rejection via the surrounding try/catch
    // in App.tsx's generate()/refine().
    const frame = 'event: stage\ndata: {not valid json\n\n'

    await expect(collect(parseSseStream(rawResponse([frame])))).rejects.toThrow(SyntaxError)
  })

  it('propagates an AbortController abort and releases the reader lock', async () => {
    const controller = new AbortController()
    const encoder = new TextEncoder()
    const stream = new ReadableStream<Uint8Array>({
      start(streamController) {
        streamController.enqueue(encoder.encode('event: stage\ndata: {"step":"calling_ai"}\n\n'))
      },
      pull(streamController) {
        if (controller.signal.aborted) {
          streamController.error(new DOMException('The operation was aborted.', 'AbortError'))
        }
      },
    })
    const response = new Response(stream)

    const generator = parseSseStream(response)
    const received: unknown[] = []

    const consuming = (async () => {
      for await (const evt of generator) {
        received.push(evt)
        controller.abort()
      }
    })()

    await expect(consuming).rejects.toThrow('The operation was aborted.')
    expect(received).toEqual([{ event: 'stage', data: { step: 'calling_ai' } }])
    expect(response.body?.locked).toBe(false)
  })
})
