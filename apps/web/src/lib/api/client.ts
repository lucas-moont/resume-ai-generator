/**
 * A plain `Error` (not renamed via `.name`) so that `String(err)` — used
 * throughout App.tsx's `catch (e) { setError(String(e)) }` — renders
 * identically to the `Error` it replaces ("Error: <message>"), while still
 * carrying the raw `detail`/`status` for call sites that want them (e.g.
 * PDF export and GitHub check use `.detail ?? fallback`, matching their
 * pre-extraction logic exactly).
 */
export class ApiError extends Error {
  detail: unknown
  status: number

  constructor(detail: unknown, status: number) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail))
    this.detail = detail
    this.status = status
  }
}

async function readErrorDetail(response: Response): Promise<unknown> {
  const data = (await response.json().catch(() => ({}))) as { detail?: unknown }
  return data.detail
}

function jsonInit(method: 'POST' | 'PUT', body: unknown, signal?: AbortSignal): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  }
}

export function postInit(body: unknown, signal?: AbortSignal): RequestInit {
  return jsonInit('POST', body, signal)
}

/** Same shape as postInit but PUT — settings writes (v3 ticket 06) are idempotent replacements, not creations. */
export function putInit(body: unknown, signal?: AbortSignal): RequestInit {
  return jsonInit('PUT', body, signal)
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) throw new ApiError(await readErrorDetail(response), response.status)
  return response.json() as Promise<T>
}

export async function requestBlob(path: string, init?: RequestInit): Promise<Blob> {
  const response = await fetch(path, init)
  if (!response.ok) throw new ApiError(await readErrorDetail(response), response.status)
  return response.blob()
}

export async function requestStream(path: string, init: RequestInit): Promise<Response> {
  const response = await fetch(path, init)
  if (!response.ok || !response.body) {
    throw new ApiError(await readErrorDetail(response), response.status)
  }
  return response
}

/** For endpoints with no response body (e.g. DELETE -> 204) — never calls .json(). */
export async function requestVoid(path: string, init?: RequestInit): Promise<void> {
  const response = await fetch(path, init)
  if (!response.ok) throw new ApiError(await readErrorDetail(response), response.status)
}

export interface MultipartOptions {
  onProgress?: (percent: number) => void
  signal?: AbortSignal
}

/**
 * POSTs FormData via XMLHttpRequest rather than fetch: fetch has no
 * cross-browser upload-progress event, and the upload feature's progress
 * bar needs one. Mirrors requestJson's ApiError contract (throws with the
 * parsed `detail` field on a non-2xx response).
 */
export function requestMultipart<T>(
  path: string,
  formData: FormData,
  { onProgress, signal }: MultipartOptions = {},
): Promise<T> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }

    const xhr = new XMLHttpRequest()
    xhr.open('POST', path)

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100))
      }
    }

    xhr.onload = () => {
      // Some XHR mocks (incl. @mswjs/interceptors, used in this repo's tests)
      // don't reliably suppress "load" after xhr.abort() the way a real
      // browser does — guard explicitly rather than relying on that.
      if (signal?.aborted) {
        reject(new DOMException('Aborted', 'AbortError'))
        return
      }
      let body: unknown = {}
      try {
        body = xhr.responseText ? JSON.parse(xhr.responseText) : {}
      } catch {
        // Non-JSON body (e.g. an unhandled server error page) — treated as empty.
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as T)
      } else {
        reject(new ApiError((body as { detail?: unknown }).detail, xhr.status))
      }
    }

    xhr.onerror = () => reject(new ApiError('Network error', 0))
    xhr.onabort = () => reject(new DOMException('Aborted', 'AbortError'))
    signal?.addEventListener('abort', () => xhr.abort())

    xhr.send(formData)
  })
}
