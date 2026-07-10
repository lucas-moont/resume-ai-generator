import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../../test/setup'
import { ApiError, postInit, requestBlob, requestJson, requestStream } from './client'

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
