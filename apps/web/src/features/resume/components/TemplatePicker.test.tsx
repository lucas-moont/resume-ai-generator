import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { TEMPLATE_REGISTRY } from '../templates/registry'
import { TemplatePicker } from './TemplatePicker'

describe('TemplatePicker', () => {
  it('renders the native select with all 8 templates as options', () => {
    render(<TemplatePicker value="modern" onChange={vi.fn()} />)
    const select = screen.getByLabelText('Template', { exact: true })
    expect(select).toBeInstanceOf(HTMLSelectElement)
    const options = screen.getAllByRole('option')
    expect(options).toHaveLength(TEMPLATE_REGISTRY.length)
    for (const t of TEMPLATE_REGISTRY) {
      expect(screen.getByRole('option', { name: t.label })).toBeInTheDocument()
    }
  })

  it('renders a labeled thumbnail button for every template (presence/labeling, not a visual snapshot)', () => {
    render(<TemplatePicker value="modern" onChange={vi.fn()} />)
    const group = screen.getByRole('group', { name: 'Template previews' })
    for (const t of TEMPLATE_REGISTRY) {
      expect(
        screen.getByRole('button', { name: `${t.label} template` }),
      ).toBeInTheDocument()
    }
    expect(group.querySelectorAll('button')).toHaveLength(TEMPLATE_REGISTRY.length)
  })

  it('marks the current template thumbnail as pressed', () => {
    render(<TemplatePicker value="classic" onChange={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Classic template' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByRole('button', { name: 'Modern template' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
  })

  it('clicking a thumbnail switches instantly (no network — just calls onChange)', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<TemplatePicker value="modern" onChange={onChange} />)
    await user.click(screen.getByRole('button', { name: 'Tech template' }))
    expect(onChange).toHaveBeenCalledWith('tech')
  })

  it('selecting via the native select still works', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<TemplatePicker value="modern" onChange={onChange} />)
    await user.selectOptions(screen.getByLabelText('Template', { exact: true }), 'executive')
    expect(onChange).toHaveBeenCalledWith('executive')
  })
})
