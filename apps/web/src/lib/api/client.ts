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

export function postInit(body: unknown, signal?: AbortSignal): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  }
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
