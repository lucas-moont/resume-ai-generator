import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ContactGapsNotice } from './ContactGapsNotice'
import { makeResume } from '../../../test/factories'

describe('ContactGapsNotice', () => {
  it('renders nothing when every contact detail is present', () => {
    const { container } = render(<ContactGapsNotice resume={makeResume()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('names the missing phone in the resume own language', () => {
    render(<ContactGapsNotice resume={makeResume({ phone: null, locale: 'pt-BR' })} />)
    expect(screen.getByRole('status')).toHaveTextContent(/vai sair sem: telefone/i)
  })

  it('speaks English for an English resume', () => {
    render(<ContactGapsNotice resume={makeResume({ phone: null, locale: 'en' })} />)
    expect(screen.getByRole('status')).toHaveTextContent(/going out without: phone/i)
  })

  it('lists several gaps in one notice rather than stacking banners', () => {
    render(<ContactGapsNotice resume={makeResume({ phone: null, links: [], locale: 'pt-BR' })} />)
    const status = screen.getByRole('status')
    expect(status).toHaveTextContent(/telefone/i)
    expect(status).toHaveTextContent(/link de perfil/i)
    expect(screen.getAllByRole('status')).toHaveLength(1)
  })

  it('says where the user can fix it, since only they have the value', () => {
    render(<ContactGapsNotice resume={makeResume({ phone: null, locale: 'pt-BR' })} />)
    expect(screen.getByRole('status')).toHaveTextContent(/no chat ou editando/i)
  })

  it('is excluded from browser print, so it never lands on the printed resume', () => {
    // index.css's @media print keeps .print-preview-wrap and its children visible (a
    // multi-page resume has to print in full), so this notice needs its own opt-out.
    render(<ContactGapsNotice resume={makeResume({ phone: null })} />)
    expect(screen.getByRole('status')).toHaveClass('no-print')
  })

  it('never complains about a badly formatted value, only a missing one', () => {
    // Format validation across locales produces false alarms, and a false alarm teaches the
    // user to ignore the notice. "1" is a terrible phone number and still counts as present.
    const { container } = render(<ContactGapsNotice resume={makeResume({ phone: '1' })} />)
    expect(container).toBeEmptyDOMElement()
  })
})
