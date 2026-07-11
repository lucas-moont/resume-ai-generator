import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../../test/setup'
import {
  ApiError,
  postInit,
  requestBlob,
  requestJson,
  requestMultipart,
  requestStream,
  requestVoid,
} from './client'

describe('postInit', () => {
  it('builds a JSON POST RequestInit carrying the body and an optional abort signal', () => {
    const controller = new AbortController()

    expect(postInit({ hello: 'world' }, controller.signal)).toEqual({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hello: 'world' }),
      signal: controller.signal,
    })
  })
})

describe('requestJson', () => {
  it('returns the parsed JSON body on success', async () => {
    server.use(http.get('/api/test-json-ok', () => HttpResponse.json({ hello: 'world' })))

    await expect(requestJson('/api/test-json-ok')).resolves.toEqual({ hello: 'world' })
  })

  it('throws an ApiError whose message is the string detail verbatim', async () => {
    server.use(
      http.get('/api/test-json-error', () =>
        HttpResponse.json({ detail: 'Bad request' }, { status: 400 }),
      ),
    )

    let caught: unknown
    try {
      await requestJson('/api/test-json-error')
    } catch (e) {
      caught = e
    }

    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ApiError).detail).toBe('Bad request')
    expect((caught as ApiError).status).toBe(400)
    // `.name` is left as the inherited "Error" (not "ApiError") so
    // `String(err)` renders exactly like the plain `Error` it replaces.
    expect(String(caught)).toBe('Error: Bad request')
  })

  it('stringifies a non-string detail', async () => {
    server.use(
      http.get('/api/test-json-error-obj', () =>
        HttpResponse.json({ detail: { field: 'model' } }, { status: 422 }),
      ),
    )

    await expect(requestJson('/api/test-json-error-obj')).rejects.toThrow(
      JSON.stringify({ field: 'model' }),
    )
  })
})

describe('requestBlob', () => {
  it('returns the response body as a Blob on success', async () => {
    server.use(
      http.post('/api/test-blob-ok', () => new HttpResponse('pdf-bytes', { status: 200 })),
    )

    const blob = await requestBlob('/api/test-blob-ok', postInit({}))
    expect(await blob.text()).toBe('pdf-bytes')
  })

  it('throws an ApiError on failure', async () => {
    server.use(
      http.post('/api/test-blob-error', () =>
        HttpResponse.json({ detail: 'PDF export failed' }, { status: 500 }),
      ),
    )

    await expect(requestBlob('/api/test-blob-error', postInit({}))).rejects.toThrow(
      'PDF export failed',
    )
  })
})

describe('requestStream', () => {
  it('returns the response when it is ok and has a body', async () => {
    server.use(
      http.post('/api/test-stream-ok', () => new HttpResponse('chunk', { status: 200 })),
    )

    const response = await requestStream('/api/test-stream-ok', postInit({}))
    expect(response.ok).toBe(true)
  })

  it('throws when the response is ok but has no body', async () => {
    server.use(
      http.post('/api/test-stream-nobody', () => new HttpResponse(null, { status: 200 })),
    )

    let caught: unknown
    try {
      await requestStream('/api/test-stream-nobody', postInit({}))
    } catch (e) {
      caught = e
    }

    expect(caught).toBeInstanceOf(ApiError)
  })

  it('throws using the error body detail when the response is not ok', async () => {
    server.use(
      http.post('/api/test-stream-error', () =>
        HttpResponse.json({ detail: 'Model not found' }, { status: 404 }),
      ),
    )

    await expect(requestStream('/api/test-stream-error', postInit({}))).rejects.toThrow(
      'Model not found',
    )
  })
})

describe('requestMultipart', () => {
  it('uploads FormData and resolves the parsed JSON body on success', async () => {
    // Body-content fidelity (filename/bytes) isn't asserted here: jsdom's
    // File doesn't round-trip through @mswjs/interceptors' Node-side
    // multipart re-serialization in this test environment (a known
    // jsdom/undici interop gap, not something this client controls) — a
    // real browser XHR send doesn't go through that layer. What's under
    // test is requestMultipart's own contract: POST + parse the JSON body.
    server.use(
      http.post('/api/test-multipart-ok', () =>
        HttpResponse.json({ documentId: 1, status: 'proposed' }, { status: 202 }),
      ),
    )

    const formData = new FormData()
    formData.append('file', new File(['{"fullName":"Ada"}'], 'profile.json', { type: 'application/json' }))

    const result = await requestMultipart('/api/test-multipart-ok', formData)

    expect(result).toEqual({ documentId: 1, status: 'proposed' })
  })

  it('reports upload progress via onProgress, ending at 100', async () => {
    server.use(http.post('/api/test-multipart-progress', () => HttpResponse.json({ ok: true })))
    const progressUpdates: number[] = []
    const formData = new FormData()
    formData.append('file', new File(['hello world'], 'notes.md'))

    await requestMultipart('/api/test-multipart-progress', formData, {
      onProgress: (pct) => progressUpdates.push(pct),
    })

    expect(progressUpdates.length).toBeGreaterThan(0)
    expect(progressUpdates.at(-1)).toBe(100)
  })

  it('throws an ApiError carrying the detail on a non-2xx response', async () => {
    server.use(
      http.post('/api/test-multipart-error', () =>
        HttpResponse.json({ detail: 'file too large' }, { status: 413 }),
      ),
    )
    const formData = new FormData()
    formData.append('file', new File(['x'], 'a.pdf'))

    let caught: unknown
    try {
      await requestMultipart('/api/test-multipart-error', formData)
    } catch (e) {
      caught = e
    }

    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ApiError).detail).toBe('file too large')
    expect((caught as ApiError).status).toBe(413)
  })

  it('rejects with an AbortError if the signal was aborted mid-flight, even if the mock still delivers a response', async () => {
    // @mswjs/interceptors' XHR mock doesn't reliably suppress "load" after
    // xhr.abort() the way a real browser does — this proves requestMultipart
    // guards against that itself rather than trusting the mock's abort semantics.
    server.use(
      http.post('/api/test-multipart-late-abort', async () => {
        await new Promise((resolve) => setTimeout(resolve, 50))
        return HttpResponse.json({ documentId: 1, status: 'proposed' })
      }),
    )
    const controller = new AbortController()
    const formData = new FormData()
    formData.append('file', new File(['x'], 'a.json'))

    const pending = requestMultipart('/api/test-multipart-late-abort', formData, {
      signal: controller.signal,
    })
    controller.abort()

    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('rejects with an AbortError when the signal is already aborted, without sending a request', async () => {
    server.use(
      http.post('/api/test-multipart-abort', () => {
        throw new Error('should never be called — signal was already aborted')
      }),
    )
    const controller = new AbortController()
    controller.abort()
    const formData = new FormData()
    formData.append('file', new File(['x'], 'a.json'))

    await expect(
      requestMultipart('/api/test-multipart-abort', formData, { signal: controller.signal }),
    ).rejects.toMatchObject({ name: 'AbortError' })
  })
})

describe('requestVoid', () => {
  it('resolves without attempting to parse a body (e.g. 204 No Content)', async () => {
    server.use(
      http.delete('/api/test-void-ok', () => new HttpResponse(null, { status: 204 })),
    )

    await expect(requestVoid('/api/test-void-ok', { method: 'DELETE' })).resolves.toBeUndefined()
  })

  it('throws an ApiError on failure', async () => {
    server.use(
      http.delete('/api/test-void-error', () =>
        HttpResponse.json({ detail: 'Session not found' }, { status: 404 }),
      ),
    )

    await expect(requestVoid('/api/test-void-error', { method: 'DELETE' })).rejects.toThrow(
      'Session not found',
    )
  })
})
