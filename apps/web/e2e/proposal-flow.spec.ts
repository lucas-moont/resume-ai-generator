import { test, expect } from '@playwright/test'
import { mockBaseline } from './support/mocks'
import { sseBody, SSE_HEADERS } from './support/sse'
import { analysisTurnEvents, adjustTurnEvents, approveChainEvents } from './support/sse'
import { makeResume, makeProposal, makeProposalItem } from './support/fixtures'
import { mockTimedStream } from './support/timedSse'

/**
 * v4 Improvement Proposal — end-to-end chat flow (docs/v4-improvement-proposal.md §3.6).
 * 100% mocked via page.route; the first turn of the happy-path scenario uses
 * `mockTimedStream` (real chunked delivery through a loopback server) so the
 * `analyzing_job` typing indicator has a genuine window to render — a single-shot
 * `route.fulfill()` never shows it at all (confirmed empirically, not just suspected:
 * every SSE-driven store update from one fulfilled body lands in the same microtask
 * flush, before the browser paints). Every other turn in this file uses the ordinary
 * single-shot mock, same as the rest of this suite.
 */
test.describe('Improvement Proposal chat flow (v4)', () => {
  test('paste a JD, adjust, approve by text — proposal survives to an applied resume', async ({ page }) => {
    const sessionId = 401
    const proposalId = 21
    const createdAt = new Date().toISOString()

    await mockBaseline(page)
    await page.route('**/api/chat/sessions', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      await route.fulfill({ status: 201, json: { id: sessionId, title: 'Backend role', createdAt } })
    })

    // --- Turn 1: Analysis (JD colada, sem pendente) ---
    const proposalV1 = makeProposal({
      proposalId,
      revision: 1,
      items: [makeProposalItem()],
    })
    const analysisContent =
      '**Seguem minhas sugestões de melhoria para essa vaga:**\n\n' +
      '- Destaque sua experiência com sistemas distribuídos\n' +
      '- Inclua métricas de impacto no resumo\n\n' +
      'Quer aprovar ou ajustar antes de eu gerar o currículo?'
    const closeTimedServer = await mockTimedStream(
      page,
      `**/api/chat/sessions/${sessionId}/messages/stream`,
      [
        [{ event: 'stage', data: { step: 'analyzing_job', progress: 50, message: 'Analyzing job description…' } }],
        analysisTurnEvents(proposalV1, { content: analysisContent }),
      ],
    )

    await page.goto('/')
    await page
      .getByLabel('Message', { exact: true })
      .fill('Senior Backend Engineer — distributed systems team, Python, Kubernetes, PostgreSQL.')
    await page.getByRole('button', { name: 'Send', exact: true }).click()

    await expect(page.getByRole('status', { name: 'Assistente está digitando' })).toBeVisible()

    // Prose rendered as real markdown DOM, not raw asterisks.
    await expect(
      page.locator('strong', { hasText: 'Seguem minhas sugestões de melhoria para essa vaga:' }),
    ).toBeVisible()
    // Note: getByRole(..., { name }) computes the true ARIA accessible name, which content-only
    // roles like `listitem` don't have (the debug snapshot shows their text for readability, but
    // that's not the same thing) — `.filter({ hasText })` is the correct way to match on content.
    await expect(
      page.getByRole('listitem').filter({ hasText: 'Destaque sua experiência com sistemas distribuídos' }),
    ).toBeVisible()
    await expect(page.getByText('**', { exact: false })).toHaveCount(0)

    await expect(page.getByText('Proposta de melhorias')).toBeVisible()
    const approveButton = page.getByRole('button', { name: 'Aprovar e gerar', exact: true })
    await expect(approveButton).toBeVisible()

    await closeTimedServer()

    // --- Turn 2: Adjust (pendente) — same proposalId, revision + 1 ---
    const proposalV2 = makeProposal({
      proposalId,
      revision: 2,
      items: [makeProposalItem(), makeProposalItem({ id: 2, section: 'skills', current: null, proposed: 'Docker, Kubernetes' })],
    })
    await page.route(`**/api/chat/sessions/${sessionId}/messages/stream`, (route) =>
      route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody(adjustTurnEvents(proposalV2, { content: 'Ajustei a proposta: adicionei Docker e Kubernetes ao resumo.' })),
      }),
    )

    await page.getByLabel('Message', { exact: true }).fill('Também inclua Docker e Kubernetes no resumo')
    await page.getByRole('button', { name: 'Send', exact: true }).click()

    await expect(page.getByText('Ajustei a proposta: adicionei Docker e Kubernetes ao resumo.')).toBeVisible()
    await expect(page.getByText('revisão 2')).toBeVisible()
    // Button rule (spec §5): only the newest proposal bubble keeps the button.
    await expect(page.getByRole('button', { name: 'Aprovar e gerar', exact: true })).toHaveCount(1)

    // --- Turn 3: Approve via natural language ---
    const approvedResume = makeResume({
      fullName: 'Ada Lovelace',
      headline: 'Backend Engineer especializado em sistemas distribuídos',
    })
    await page.route(`**/api/chat/sessions/${sessionId}/messages/stream`, (route) =>
      route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody(
          approveChainEvents(proposalId, {
            resume: approvedResume,
            resumeVersionId: 2,
            confirmContent: 'Vou gerar o currículo com essas melhorias…',
            finalContent: 'Currículo atualizado com as melhorias aprovadas!',
          }),
        ),
      }),
    )

    await page.getByLabel('Message', { exact: true }).fill('pode fazer, aprovado')
    await page.getByRole('button', { name: 'Send', exact: true }).click()

    await expect(page.getByText('Vou gerar o currículo com essas melhorias…')).toBeVisible()
    await expect(page.getByText('Currículo atualizado com as melhorias aprovadas!')).toBeVisible()
    await expect(page.getByText(/resume updated/i)).toBeVisible()
    await expect(
      page.getByLabel('Preview', { exact: true }).getByText('Backend Engineer especializado em sistemas distribuídos'),
    ).toBeVisible()

    // Terminal state: applied badge (both the original and the adjusted bubble share this
    // proposalId, so both flip to "approved" — see useChatStream's markProposalCards), no
    // more approve button anywhere.
    await expect(page.getByText('Aplicada — currículo gerado')).toHaveCount(2)
    await expect(page.getByRole('button', { name: 'Aprovar e gerar', exact: true })).toHaveCount(0)
  })

  test('clicking "Aprovar e gerar" sends the approval and threads proposalAction in the request body', async ({
    page,
  }) => {
    const sessionId = 402
    const proposalId = 22
    const createdAt = new Date().toISOString()

    await mockBaseline(page)
    await page.route('**/api/chat/sessions', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      await route.fulfill({ status: 201, json: { id: sessionId, title: 'Backend role', createdAt } })
    })

    const proposal = makeProposal({ proposalId, revision: 1, items: [makeProposalItem()] })
    await page.route(`**/api/chat/sessions/${sessionId}/messages/stream`, (route) =>
      route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody(analysisTurnEvents(proposal, { content: 'Aqui estão minhas sugestões para essa vaga.' })),
      }),
    )

    await page.goto('/')
    await page.getByLabel('Message', { exact: true }).fill('Senior Backend Engineer role, distributed systems.')
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Aprovar e gerar', exact: true })).toBeVisible()

    let capturedBody: { proposalAction?: string } | undefined
    const approvedResume = makeResume({ fullName: 'Ada Lovelace' })
    await page.route(`**/api/chat/sessions/${sessionId}/messages/stream`, (route) => {
      capturedBody = route.request().postDataJSON()
      return route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody(approveChainEvents(proposalId, { resume: approvedResume, resumeVersionId: 5 })),
      })
    })

    await page.getByRole('button', { name: 'Aprovar e gerar', exact: true }).click()

    // The button's own user-facing message appears in the chat like any other send.
    await expect(page.locator('.whitespace-pre-wrap', { hasText: 'Aprovar e gerar' })).toBeVisible()

    await expect(page.getByText(/resume updated/i)).toBeVisible()
    await expect(page.getByText('Aplicada — currículo gerado')).toBeVisible()
    expect(capturedBody?.proposalAction).toBe('approve')
  })

  test('a pending proposal and its approve button survive a session reload', async ({ page }) => {
    const sessionId = 403
    const proposalId = 23
    const createdAt = new Date().toISOString()
    const jdMessage = 'Senior Backend Engineer role, distributed systems, Python.'

    await mockBaseline(page)
    await page.route('**/api/chat/sessions', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      await route.fulfill({ status: 201, json: { id: sessionId, title: 'Backend role', createdAt } })
    })

    const proposalContent = 'Aqui estão minhas sugestões para essa vaga.'
    const proposal = makeProposal({ proposalId, revision: 1, items: [makeProposalItem()] })
    await page.route(`**/api/chat/sessions/${sessionId}/messages/stream`, (route) =>
      route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody(analysisTurnEvents(proposal, { content: proposalContent })),
      }),
    )

    await page.goto('/')
    await page.getByLabel('Message', { exact: true }).fill(jdMessage)
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Aprovar e gerar', exact: true })).toBeVisible()

    // Simulate the backend's live-joined rehydration (§3.7): each message's own `proposal`
    // field plus the session-level `pendingProposal` — same DTO shape, current status.
    await page.route('**/api/chat/sessions', async (route) => {
      if (route.request().method() !== 'GET') return route.fallback()
      await route.fulfill({
        json: { sessions: [{ id: sessionId, title: 'Backend role', updatedAt: createdAt, activeResumeVersionId: null }] },
      })
    })
    await page.route(`**/api/chat/sessions/${sessionId}`, (route) =>
      route.fulfill({
        json: {
          session: {
            id: sessionId,
            title: 'Backend role',
            updatedAt: createdAt,
            activeResumeVersionId: null,
            locale: null,
            jobDescription: null,
            createdAt,
          },
          messages: [
            { id: 1, role: 'user', content: jdMessage, intent: null, resumeVersionId: null, createdAt, sourceDocument: null, proposal: null },
            {
              id: 2,
              role: 'assistant',
              content: proposalContent,
              // The real backend stamps the Analysis message with intent "propose"
              // (chat_service._handle_propose_turn) — and since QA-01, rehydration only
              // rebuilds a ProposalCard for the proposal-emitting intents. An unfaithful
              // `intent: null` here silently drops the card and fails this scenario.
              intent: 'propose',
              resumeVersionId: null,
              createdAt,
              sourceDocument: null,
              proposal,
            },
          ],
          activeResume: null,
          pendingProposal: proposal,
        },
      }),
    )

    await page.reload()

    await expect(page.getByText(proposalContent)).toBeVisible()
    await expect(page.getByText('Proposta de melhorias')).toBeVisible()
    const approveButtonAfterReload = page.getByRole('button', { name: 'Aprovar e gerar', exact: true })
    await expect(approveButtonAfterReload).toBeVisible()

    // Not just visually present — the rehydrated button must still actually work.
    const approvedResume = makeResume({ fullName: 'Ada Lovelace' })
    await page.route(`**/api/chat/sessions/${sessionId}/messages/stream`, (route) =>
      route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody(approveChainEvents(proposalId, { resume: approvedResume, resumeVersionId: 2 })),
      }),
    )
    await approveButtonAfterReload.click()

    await expect(page.getByText(/resume updated/i)).toBeVisible()
    await expect(page.getByText('Aplicada — currículo gerado')).toBeVisible()
  })

  test('generation failure after approval leaves the button alive; re-approving succeeds', async ({ page }) => {
    const sessionId = 404
    const proposalId = 24
    const createdAt = new Date().toISOString()

    await mockBaseline(page)
    await page.route('**/api/chat/sessions', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      await route.fulfill({ status: 201, json: { id: sessionId, title: 'Backend role', createdAt } })
    })

    const proposal = makeProposal({ proposalId, revision: 1, items: [makeProposalItem()] })
    await page.route(`**/api/chat/sessions/${sessionId}/messages/stream`, (route) =>
      route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody(analysisTurnEvents(proposal, { content: 'Aqui estão minhas sugestões para essa vaga.' })),
      }),
    )

    await page.goto('/')
    await page.getByLabel('Message', { exact: true }).fill('Senior Backend Engineer role, distributed systems.')
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    const approveButton = page.getByRole('button', { name: 'Aprovar e gerar', exact: true })
    await expect(approveButton).toBeVisible()

    // Approve -> generation fails mid-chain (§6: "Proposta continua proposed; error frame;
    // reaprovação funciona").
    await page.route(`**/api/chat/sessions/${sessionId}/messages/stream`, (route) =>
      route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody([
          { event: 'message', data: { content: 'Vou gerar o currículo com essas melhorias…' } },
          { event: 'stage', data: { step: 'finalizing', progress: 90, message: 'Finalizing…' } },
          { event: 'error', data: { message: 'Falha ao gerar o currículo. Tente novamente.' } },
        ]),
      }),
    )
    await approveButton.click()

    await expect(page.getByRole('alert')).toContainText('Falha ao gerar o currículo. Tente novamente.')
    // The button is still there AND still active — the proposal was never consumed.
    await expect(approveButton).toBeVisible()
    await expect(approveButton).toBeEnabled()
    await expect(page.getByRole('button', { name: 'Aprovar e gerar', exact: true })).toHaveCount(1)

    // Re-approve -> succeeds this time.
    const approvedResume = makeResume({ fullName: 'Ada Lovelace' })
    await page.route(`**/api/chat/sessions/${sessionId}/messages/stream`, (route) =>
      route.fulfill({
        headers: SSE_HEADERS,
        body: sseBody(approveChainEvents(proposalId, { resume: approvedResume, resumeVersionId: 2 })),
      }),
    )
    await approveButton.click()

    await expect(page.getByText(/resume updated/i)).toBeVisible()
    await expect(page.getByText('Aplicada — currículo gerado')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Aprovar e gerar', exact: true })).toHaveCount(0)
  })
})
