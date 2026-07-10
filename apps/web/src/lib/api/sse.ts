export interface SseEvent<T = unknown> {
  event: string
  data: T
}

/**
 * Parses a fetch `Response` body as a stream of Server-Sent Events, in the
 * `event: <name>\ndata: <payload>\n\n` framing used by /api/generate/stream
 * and /api/refine/stream (and, later, /api/chat/.../stream). Extracted from
 * the inline reader loop that used to live in App.tsx's runStreamRequest.
 */
export async function* parseSseStream<T = unknown>(
  response: Response,
): AsyncGenerator<SseEvent<T>> {
  if (!response.body) return
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''
      for (const frame of frames) {
        const evt = parseFrame<T>(frame)
        if (evt) yield evt
      }
    }
  } finally {
    reader.releaseLock()
  }
}

function parseFrame<T>(frame: string): SseEvent<T> | null {
  const lines = frame.split('\n')
  const eventLine = lines.find((l) => l.startsWith('event:'))
  const dataLines = lines.filter((l) => l.startsWith('data:'))
  if (!eventLine || dataLines.length === 0) return null

  const event = eventLine.replace('event:', '').trim()
  // SSE spec: consecutive `data:` lines within one frame are joined with
  // "\n" to reconstitute the full value before further parsing.
  const raw = dataLines.map(stripDataPrefix).join('\n')
  if (!raw) return null

  return { event, data: JSON.parse(raw) as T }
}

function stripDataPrefix(line: string): string {
  const withoutPrefix = line.slice('data:'.length)
  return withoutPrefix.startsWith(' ') ? withoutPrefix.slice(1) : withoutPrefix
}
