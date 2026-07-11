import { createServer, type Server } from 'node:http'
import type { AddressInfo } from 'node:net'
import type { Page } from '@playwright/test'
import { sseBody, SSE_HEADERS, type E2eSseEvent } from './sse'

/**
 * `page.route(...).fulfill()` always hands the whole SSE body to the browser's fetch in
 * one go (see sse.ts's own doc comment) — fine for asserting a turn's settled end state,
 * but a turn's fleeting mid-stream UI (the `analyzing_job` typing indicator, spec §3.5)
 * never actually renders that way: every SSE-driven store update from a single-shot
 * fulfill lands within the same microtask flush, before the browser gets a chance to
 * paint the intermediate frame — confirmed empirically (5/5 runs) rather than assumed;
 * a single-shot fulfill NEVER shows the typing indicator, deterministically, not flakily.
 *
 * This spins up a real loopback HTTP server that writes the given SSE frame groups with
 * a genuine `setTimeout` gap between them, and redirects (`route.continue({ url })`) the
 * ONE matching request to it — a real task-queue boundary (not just a microtask) sits
 * between groups, giving React time to actually commit + paint the in-between state.
 * `route.continue({ url })` is a DevTools-level substitution: the browser still treats
 * the response as fulfilling the original same-origin request, so no CORS is involved
 * (confirmed empirically too — no preflight, no CORS error, in 5/5 probe runs).
 *
 * Returns a cleanup function that closes the server — call it once the assertions that
 * needed the real timing gap are done; later turns in the same test can go back to the
 * plain `page.route(...).fulfill(...)` pattern via a fresh `page.route()` registration
 * (later registrations take precedence, same rule as everywhere else in this suite).
 */
export async function mockTimedStream(
  page: Page,
  urlGlob: string,
  frameGroups: E2eSseEvent[][],
  gapMs = 500,
): Promise<() => Promise<void>> {
  const server: Server = createServer((req, res) => {
    req.resume() // drain the POST body we don't care about, so the socket never stalls
    res.writeHead(200, SSE_HEADERS)
    void (async () => {
      for (const [index, group] of frameGroups.entries()) {
        if (index > 0) await new Promise((resolve) => setTimeout(resolve, gapMs))
        res.write(sseBody(group))
      }
      res.end()
    })()
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const port = (server.address() as AddressInfo).port

  await page.route(urlGlob, (route) => route.continue({ url: `http://127.0.0.1:${port}/` }))

  return () => new Promise<void>((resolve) => server.close(() => resolve()))
}
