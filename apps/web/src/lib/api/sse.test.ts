import { describe, expect, it } from 'vitest'
import { parseSseStream } from './sse'

function streamFromChunks(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  let i = 0
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i >= chunks.length) {
        controller.close()
        return
      }
      controller.enqueue(encoder.encode(chunks[i++]))
    },
  })
}

async function collect<T>(gen: AsyncGenerator<T>): Promise<T[]> {
  const items: T[] = []
  for await (const item of gen) items.push(item)
  return items
}

describe('parseSseStream', () => {
  it('parses a frame that arrives split across two stream chunks', async () => {
    const full = 'event: stage\ndata: {"step":"calling_ai","progress":40}\n\n'
    const splitPoint = 15
    const response = new Response(
      streamFromChunks([full.slice(0, splitPoint), full.slice(splitPoint)]),
    )

    const events = await collect(parseSseStream(response))

    expect(events).toEqual([{ event: 'stage', data: { step: 'calling_ai', progress: 40 } }])
  })

  it('joins multiple data: lines within one frame per the SSE spec', async () => {
    const frame = 'event: message\ndata: {\ndata:   "content": "hi"\ndata: }\n\n'
    const response = new Response(streamFromChunks([frame]))

    const events = await collect(parseSseStream(response))

    expect(events).toEqual([{ event: 'message', data: { content: 'hi' } }])
  })

  it('propagates stream errors (e.g. an aborted request) and releases the reader lock', async () => {
    const abortError = new DOMException('The operation was aborted.', 'AbortError')
    const encoder = new TextEncoder()
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: stage\ndata: {"step":"calling_ai"}\n\n'))
      },
      pull(controller) {
        controller.error(abortError)
      },
    })
    const response = new Response(stream)

    const generator = parseSseStream(response)
    const received: unknown[] = []

    await expect(
      (async () => {
        for await (const evt of generator) received.push(evt)
      })(),
    ).rejects.toThrow('The operation was aborted.')

    expect(received).toEqual([{ event: 'stage', data: { step: 'calling_ai' } }])
    expect(response.body?.locked).toBe(false)
  })
})
