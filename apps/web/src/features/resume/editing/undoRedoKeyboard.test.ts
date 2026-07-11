import { renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import {
  isFocusInsideContentEditable,
  matchesRedo,
  matchesUndo,
  useUndoRedoShortcuts,
} from './undoRedoKeyboard'
import { useResumeStore } from '../store/resumeStore'
import { makeResume } from '../../../test/factories'

function keyEvent(init: Partial<KeyboardEventInit> & { key: string }): KeyboardEvent {
  return new KeyboardEvent('keydown', init)
}

describe('matchesUndo', () => {
  it('matches Ctrl+Z', () => {
    expect(matchesUndo(keyEvent({ key: 'z', ctrlKey: true }))).toBe(true)
  })

  it('matches Cmd+Z (metaKey, for mac keyboards)', () => {
    expect(matchesUndo(keyEvent({ key: 'z', metaKey: true }))).toBe(true)
  })

  it('does not match Ctrl+Shift+Z (that is redo)', () => {
    expect(matchesUndo(keyEvent({ key: 'z', ctrlKey: true, shiftKey: true }))).toBe(false)
  })

  it('does not match a bare "z" with no modifier', () => {
    expect(matchesUndo(keyEvent({ key: 'z' }))).toBe(false)
  })

  it('does not match Ctrl+other-letter', () => {
    expect(matchesUndo(keyEvent({ key: 'a', ctrlKey: true }))).toBe(false)
  })

  it('is case-insensitive on the key', () => {
    expect(matchesUndo(keyEvent({ key: 'Z', ctrlKey: true }))).toBe(true)
  })
})

describe('matchesRedo', () => {
  it('matches Ctrl+Shift+Z', () => {
    expect(matchesRedo(keyEvent({ key: 'z', ctrlKey: true, shiftKey: true }))).toBe(true)
  })

  it('matches Cmd+Shift+Z', () => {
    expect(matchesRedo(keyEvent({ key: 'z', metaKey: true, shiftKey: true }))).toBe(true)
  })

  it('does not match Ctrl+Z alone (that is undo)', () => {
    expect(matchesRedo(keyEvent({ key: 'z', ctrlKey: true }))).toBe(false)
  })
})

describe('isFocusInsideContentEditable', () => {
  it('is false when nothing is focused', () => {
    expect(isFocusInsideContentEditable()).toBe(false)
  })

  it('is true when the focused element is a live contenteditable node', () => {
    const el = document.createElement('div')
    // jsdom quirk: unlike a real browser, a bare createElement'd contenteditable
    // div isn't focusable by .focus() without an explicit tabIndex, and the
    // `contenteditable` attribute must be set via setAttribute (the .contentEditable
    // IDL property setter doesn't reflect to the attribute in jsdom). React's real
    // contentEditable JSX prop does set the attribute directly (see EditableText's
    // own tests), so this only affects this hand-built fixture.
    el.setAttribute('contenteditable', 'true')
    el.tabIndex = 0
    document.body.appendChild(el)
    el.focus()

    expect(isFocusInsideContentEditable()).toBe(true)

    el.remove()
  })

  it('is false when focus is on a regular (non-editable) element', () => {
    const button = document.createElement('button')
    document.body.appendChild(button)
    button.focus()

    expect(isFocusInsideContentEditable()).toBe(false)

    button.remove()
  })

  it('is true when focus is on a <textarea> (e.g. the chat Composer)', () => {
    const textarea = document.createElement('textarea')
    document.body.appendChild(textarea)
    textarea.focus()

    expect(isFocusInsideContentEditable()).toBe(true)

    textarea.remove()
  })

  it('is true when focus is on an <input>', () => {
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()

    expect(isFocusInsideContentEditable()).toBe(true)

    input.remove()
  })

  it('is true when focus is on a <select>', () => {
    const select = document.createElement('select')
    document.body.appendChild(select)
    select.focus()

    expect(isFocusInsideContentEditable()).toBe(true)

    select.remove()
  })
})

describe('useUndoRedoShortcuts', () => {
  beforeEach(() => {
    useResumeStore.setState({ resume: null, validationIssues: [] })
    useResumeStore.temporal.getState().clear()
  })

  it('Ctrl+Z anywhere outside an editable field undoes the last resume change', () => {
    useResumeStore.getState().setResume(makeResume({ fullName: 'Ada Lovelace' }))
    useResumeStore.getState().setResume(makeResume({ fullName: 'Grace Hopper' }))
    renderHook(() => useUndoRedoShortcuts())

    const event = new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, bubbles: true, cancelable: true })
    window.dispatchEvent(event)

    expect(useResumeStore.getState().resume?.fullName).toBe('Ada Lovelace')
    expect(event.defaultPrevented).toBe(true)
  })

  it('Ctrl+Shift+Z redoes', () => {
    useResumeStore.getState().setResume(makeResume({ fullName: 'Ada Lovelace' }))
    useResumeStore.getState().setResume(makeResume({ fullName: 'Grace Hopper' }))
    useResumeStore.temporal.getState().undo()
    renderHook(() => useUndoRedoShortcuts())

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Z', ctrlKey: true, shiftKey: true }))

    expect(useResumeStore.getState().resume?.fullName).toBe('Grace Hopper')
  })

  it('does not intercept Ctrl+Z while focus is inside a live contenteditable field', () => {
    useResumeStore.getState().setResume(makeResume({ fullName: 'Ada Lovelace' }))
    useResumeStore.getState().setResume(makeResume({ fullName: 'Grace Hopper' }))
    renderHook(() => useUndoRedoShortcuts())

    const el = document.createElement('div')
    el.setAttribute('contenteditable', 'true')
    el.tabIndex = 0
    document.body.appendChild(el)
    el.focus()

    const event = new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, bubbles: true, cancelable: true })
    window.dispatchEvent(event)

    // Untouched — the browser's own per-field undo owns this keystroke instead.
    expect(useResumeStore.getState().resume?.fullName).toBe('Grace Hopper')
    expect(event.defaultPrevented).toBe(false)

    el.remove()
  })

  it('does not intercept Ctrl+Z while focus is inside a <textarea> (e.g. the chat Composer)', () => {
    useResumeStore.getState().setResume(makeResume({ fullName: 'Ada Lovelace' }))
    useResumeStore.getState().setResume(makeResume({ fullName: 'Grace Hopper' }))
    renderHook(() => useUndoRedoShortcuts())

    const textarea = document.createElement('textarea')
    document.body.appendChild(textarea)
    textarea.focus()

    const event = new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, bubbles: true, cancelable: true })
    window.dispatchEvent(event)

    // Untouched — Ctrl+Z here should undo a typo in the chat message, not
    // rewind the resume out from under the Composer.
    expect(useResumeStore.getState().resume?.fullName).toBe('Grace Hopper')
    expect(event.defaultPrevented).toBe(false)

    textarea.remove()
  })

  it('does not intercept Ctrl+Z while focus is inside an <input>', () => {
    useResumeStore.getState().setResume(makeResume({ fullName: 'Ada Lovelace' }))
    useResumeStore.getState().setResume(makeResume({ fullName: 'Grace Hopper' }))
    renderHook(() => useUndoRedoShortcuts())

    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()

    const event = new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, bubbles: true, cancelable: true })
    window.dispatchEvent(event)

    expect(useResumeStore.getState().resume?.fullName).toBe('Grace Hopper')
    expect(event.defaultPrevented).toBe(false)

    input.remove()
  })

  it('cleans up its window listener on unmount', () => {
    useResumeStore.getState().setResume(makeResume({ fullName: 'Ada Lovelace' }))
    useResumeStore.getState().setResume(makeResume({ fullName: 'Grace Hopper' }))
    const { unmount } = renderHook(() => useUndoRedoShortcuts())
    unmount()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', ctrlKey: true }))

    expect(useResumeStore.getState().resume?.fullName).toBe('Grace Hopper')
  })
})
