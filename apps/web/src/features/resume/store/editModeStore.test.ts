import { beforeEach, describe, expect, it } from 'vitest'
import { useEditModeStore } from './editModeStore'

describe('editModeStore', () => {
  beforeEach(() => {
    useEditModeStore.setState({ isEditing: false })
  })

  it('starts with editing off', () => {
    expect(useEditModeStore.getState().isEditing).toBe(false)
  })

  it('toggle() flips isEditing', () => {
    useEditModeStore.getState().toggle()
    expect(useEditModeStore.getState().isEditing).toBe(true)
    useEditModeStore.getState().toggle()
    expect(useEditModeStore.getState().isEditing).toBe(false)
  })

  it('setEditing() sets an explicit value', () => {
    useEditModeStore.getState().setEditing(true)
    expect(useEditModeStore.getState().isEditing).toBe(true)
    useEditModeStore.getState().setEditing(false)
    expect(useEditModeStore.getState().isEditing).toBe(false)
  })
})
