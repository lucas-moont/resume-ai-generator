import { beforeEach, describe, expect, it } from 'vitest'
import { ACTIVE_SESSION_STORAGE_KEY, useChatStore } from './chatStore'

beforeEach(() => {
  useChatStore.getState().reset()
  localStorage.clear()
})

describe('chatStore', () => {
  it('starts empty: no session, no messages, not streaming', () => {
    const state = useChatStore.getState()
    expect(state.sessionId).toBeNull()
    expect(state.messages).toEqual([])
    expect(state.streaming).toBeNull()
  })

  it('appendUserMessage adds a user message and returns it', () => {
    const msg = useChatStore.getState().appendUserMessage('Senior backend role in Berlin')

    expect(msg.role).toBe('user')
    expect(msg.content).toBe('Senior backend role in Berlin')
    expect(useChatStore.getState().messages).toEqual([msg])
  })

  it('appendAssistantMessage adds an assistant message, optionally with a card', () => {
    const msg = useChatStore.getState().appendAssistantMessage("I've updated your resume.", {
      type: 'resumeUpdated',
      changedSections: ['summary', 'skills'],
    })

    expect(msg.role).toBe('assistant')
    expect(msg.card).toEqual({ type: 'resumeUpdated', changedSections: ['summary', 'skills'] })
    expect(useChatStore.getState().messages).toEqual([msg])
  })

  it('messages keep arriving in order across multiple appends', () => {
    useChatStore.getState().appendUserMessage('one')
    useChatStore.getState().appendAssistantMessage('two')
    useChatStore.getState().appendUserMessage('three')

    expect(useChatStore.getState().messages.map((m) => m.content)).toEqual(['one', 'two', 'three'])
  })

  it('updateStreaming creates the streaming object on first call and merges on subsequent calls', () => {
    useChatStore.getState().updateStreaming({ step: 'preparing_context', progress: 5, message: 'Starting' })
    expect(useChatStore.getState().streaming).toMatchObject({
      status: 'streaming',
      step: 'preparing_context',
      progress: 5,
      message: 'Starting',
    })

    useChatStore.getState().updateStreaming({ step: 'calling_ai', progress: 40 })
    expect(useChatStore.getState().streaming).toMatchObject({
      status: 'streaming',
      step: 'calling_ai',
      progress: 40,
      // message from the previous call is preserved, not wiped
      message: 'Starting',
    })
  })

  it('updateStreaming preserves the abortController across merges', () => {
    const controller = new AbortController()
    useChatStore.getState().updateStreaming({ abortController: controller, step: 'preparing_context' })
    useChatStore.getState().updateStreaming({ step: 'calling_ai' })

    expect(useChatStore.getState().streaming?.abortController).toBe(controller)
  })

  it('finishStreaming resets streaming back to null', () => {
    useChatStore.getState().updateStreaming({ step: 'preparing_context' })
    useChatStore.getState().finishStreaming()

    expect(useChatStore.getState().streaming).toBeNull()
  })

  it('reset clears session, messages, and streaming', () => {
    useChatStore.getState().appendUserMessage('hi')
    useChatStore.getState().updateStreaming({ step: 'calling_ai' })

    useChatStore.getState().reset()

    const state = useChatStore.getState()
    expect(state.sessionId).toBeNull()
    expect(state.messages).toEqual([])
    expect(state.streaming).toBeNull()
  })

  it('loadSession hydrates sessionId and messages, and clears any in-flight streaming', () => {
    useChatStore.getState().updateStreaming({ step: 'calling_ai' })
    const hydrated = [
      { id: 'm1', role: 'user' as const, content: 'hello', createdAt: 1 },
      { id: 'm2', role: 'assistant' as const, content: 'hi there', createdAt: 2 },
    ]

    useChatStore.getState().loadSession(123, hydrated)

    const state = useChatStore.getState()
    expect(state.sessionId).toBe(123)
    expect(state.messages).toEqual(hydrated)
    expect(state.streaming).toBeNull()
  })

  it('updateMessageCard replaces the card of the matching message via an updater function', () => {
    const msg = useChatStore.getState().appendAssistantMessage('Uploaded profile.json', {
      type: 'profileUpdated',
      documentId: 1,
      filename: 'profile.json',
      status: 'proposed',
      diffSummary: ['1 new skill'],
      opsCount: 1,
    })

    useChatStore.getState().updateMessageCard(msg.id, (card) =>
      card.type === 'profileUpdated' ? { ...card, status: 'applied' } : card,
    )

    const updated = useChatStore.getState().messages.find((m) => m.id === msg.id)
    expect(updated?.card).toMatchObject({ type: 'profileUpdated', status: 'applied', documentId: 1 })
  })

  it('updateMessageCard is a no-op for a message id that does not exist', () => {
    useChatStore.getState().appendUserMessage('hello')
    const before = useChatStore.getState().messages

    useChatStore.getState().updateMessageCard('does-not-exist', (card) => card)

    expect(useChatStore.getState().messages).toEqual(before)
  })

  it('setSessionId sets only the session id, leaving messages/streaming untouched', () => {
    useChatStore.getState().appendUserMessage('first message, sent before the session existed')
    useChatStore.getState().updateStreaming({ step: 'preparing_context' })

    useChatStore.getState().setSessionId(456)

    const state = useChatStore.getState()
    expect(state.sessionId).toBe(456)
    expect(state.messages).toHaveLength(1)
    expect(state.streaming).not.toBeNull()
  })

  describe('active session persistence (B2)', () => {
    it('persists only sessionId to localStorage — not messages or streaming', () => {
      useChatStore.getState().loadSession(42, [
        { id: 'm1', role: 'user', content: 'hello', createdAt: 1 },
      ])

      const raw = localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)
      expect(raw).not.toBeNull()
      const parsed = JSON.parse(raw as string)
      expect(parsed.state).toEqual({ sessionId: 42 })
    })

    it('rehydrates sessionId from a pre-populated localStorage entry', async () => {
      localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, JSON.stringify({ state: { sessionId: 7 }, version: 1 }))

      await useChatStore.persist.rehydrate()

      expect(useChatStore.getState().sessionId).toBe(7)
      // Messages/streaming are never part of the persisted blob.
      expect(useChatStore.getState().messages).toEqual([])
    })

    it('reset() clears the persisted sessionId too', () => {
      useChatStore.getState().setSessionId(9)
      useChatStore.getState().reset()

      const raw = localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY)
      const parsed = JSON.parse(raw as string)
      expect(parsed.state).toEqual({ sessionId: null })
    })
  })
})
