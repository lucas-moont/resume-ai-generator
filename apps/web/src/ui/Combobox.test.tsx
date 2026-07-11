import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Combobox, type ComboboxOption } from './Combobox'

const OPTIONS: ComboboxOption[] = [
  { value: 'a', label: 'Option A' },
  { value: 'b', label: 'Option B' },
  { value: 'c', label: 'Option C' },
]

function renderCombobox(overrides: Partial<React.ComponentProps<typeof Combobox>> = {}) {
  const onChange = overrides.onChange ?? vi.fn()
  const props = {
    id: 'model',
    value: '',
    onChange,
    options: OPTIONS,
    'aria-label': 'AI model',
    ...overrides,
  }
  const utils = render(<Combobox {...props} />)
  return { ...utils, onChange }
}

describe('Combobox — roles and open/close', () => {
  it('renders a combobox input with the listbox closed by default', () => {
    renderCombobox()

    const input = screen.getByRole('combobox', { name: 'AI model' })
    expect(input).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('opens the listbox on focus, listing every option', async () => {
    const user = userEvent.setup()
    renderCombobox()

    await user.click(screen.getByRole('combobox', { name: 'AI model' }))

    const listbox = screen.getByRole('listbox')
    expect(listbox).toBeInTheDocument()
    expect(screen.getAllByRole('option')).toHaveLength(3)
  })
})

describe('Combobox — arrow key navigation', () => {
  it('highlights the first option on ArrowDown, wiring aria-activedescendant to it', async () => {
    const user = userEvent.setup()
    renderCombobox()
    const input = screen.getByRole('combobox', { name: 'AI model' })
    await user.click(input)

    await user.keyboard('{ArrowDown}')

    const options = screen.getAllByRole('option')
    expect(options[0]).toHaveAttribute('aria-selected', 'true')
    expect(options[1]).toHaveAttribute('aria-selected', 'false')
    expect(input).toHaveAttribute('aria-activedescendant', options[0].id)
  })

  it('moves the highlight forward on repeated ArrowDown, and wraps from the last option back to the first', async () => {
    const user = userEvent.setup()
    renderCombobox()
    await user.click(screen.getByRole('combobox', { name: 'AI model' }))

    await user.keyboard('{ArrowDown}{ArrowDown}')
    let options = screen.getAllByRole('option')
    expect(options[1]).toHaveAttribute('aria-selected', 'true')

    await user.keyboard('{ArrowDown}{ArrowDown}')
    options = screen.getAllByRole('option')
    expect(options[0]).toHaveAttribute('aria-selected', 'true')
  })

  it('moves the highlight backward on ArrowUp, and wraps from the first option to the last', async () => {
    const user = userEvent.setup()
    renderCombobox()
    await user.click(screen.getByRole('combobox', { name: 'AI model' }))

    await user.keyboard('{ArrowUp}')

    const options = screen.getAllByRole('option')
    expect(options[2]).toHaveAttribute('aria-selected', 'true')
  })

  it('jumps to the first option on Home and the last option on End', async () => {
    const user = userEvent.setup()
    renderCombobox()
    await user.click(screen.getByRole('combobox', { name: 'AI model' }))

    await user.keyboard('{ArrowDown}{End}')
    let options = screen.getAllByRole('option')
    expect(options[2]).toHaveAttribute('aria-selected', 'true')

    await user.keyboard('{Home}')
    options = screen.getAllByRole('option')
    expect(options[0]).toHaveAttribute('aria-selected', 'true')
  })
})

describe('Combobox — selection and dismissal', () => {
  it('selects the highlighted option on Enter, calling onChange and onSelect, and closes the listbox', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    const { onChange } = renderCombobox({ onSelect })
    await user.click(screen.getByRole('combobox', { name: 'AI model' }))

    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}')

    expect(onChange).toHaveBeenCalledWith('b')
    expect(onSelect).toHaveBeenCalledWith(OPTIONS[1])
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('closes the listbox on Escape without changing the typed value', async () => {
    const user = userEvent.setup()
    const { onChange } = renderCombobox({ value: 'custom-model' })
    await user.click(screen.getByRole('combobox', { name: 'AI model' }))

    await user.keyboard('{Escape}')

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('selects an option on mouse click without requiring keyboard focus first', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    const { onChange } = renderCombobox({ onSelect })
    await user.click(screen.getByRole('combobox', { name: 'AI model' }))

    await user.click(screen.getByRole('option', { name: 'Option C' }))

    expect(onChange).toHaveBeenCalledWith('c')
    expect(onSelect).toHaveBeenCalledWith(OPTIONS[2])
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('keeps free typing intact: onChange fires with raw text and no option is force-selected', async () => {
    const user = userEvent.setup()
    const { onChange } = renderCombobox()
    const input = screen.getByRole('combobox', { name: 'AI model' })

    await user.type(input, 'glm')

    expect(onChange).toHaveBeenLastCalledWith('m')
    expect(onChange).toHaveBeenCalledTimes(3)
  })

  it('closes the listbox on blur', async () => {
    const user = userEvent.setup()
    renderCombobox()
    await user.click(screen.getByRole('combobox', { name: 'AI model' }))
    expect(screen.getByRole('listbox')).toBeInTheDocument()

    fireEvent.blur(screen.getByRole('combobox', { name: 'AI model' }))

    await vi.waitFor(() => expect(screen.queryByRole('listbox')).not.toBeInTheDocument())
  })
})

describe('Combobox — custom option rendering', () => {
  it('renders each option via renderOption when provided, instead of the default label text', async () => {
    const user = userEvent.setup()
    render(
      <Combobox
        id="model"
        value=""
        onChange={vi.fn()}
        options={OPTIONS}
        aria-label="AI model"
        renderOption={(opt) => <span data-testid={`opt-${opt.value}`}>{opt.value.toUpperCase()}</span>}
      />,
    )

    await user.click(screen.getByRole('combobox', { name: 'AI model' }))

    expect(screen.getByTestId('opt-a')).toHaveTextContent('A')
    expect(screen.queryByText('Option A')).not.toBeInTheDocument()
  })
})

describe('Combobox — empty state', () => {
  it('renders the emptyState content instead of a phantom option list when there are no options', async () => {
    const user = userEvent.setup()
    render(
      <Combobox
        id="model"
        value=""
        onChange={vi.fn()}
        options={[]}
        aria-label="AI model"
        emptyState="No models available."
      />,
    )

    await user.click(screen.getByRole('combobox', { name: 'AI model' }))

    expect(screen.getByRole('listbox')).toBeInTheDocument()
    expect(screen.getByText('No models available.')).toBeInTheDocument()
    expect(screen.queryByRole('option')).not.toBeInTheDocument()
  })
})
