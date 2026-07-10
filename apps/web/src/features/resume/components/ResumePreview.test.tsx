import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { ResumePreview } from './ResumePreview'
import { useResumeStore } from '../store/resumeStore'
import { makeResume } from '../../../test/factories'

// EditableText/EditableList write through useResumeStore directly (same
// pattern PreviewToolbar already uses for reads) rather than via a
// per-call-site onCommit prop, so a unit test that exercises a commit must
// seed the store with the SAME resume object being rendered as a prop — in
// production this is automatic (PreviewPanel's `resume` prop IS useResume()).
function renderWithStore(overrides = {}, editable = false) {
  const resume = makeResume(overrides)
  useResumeStore.setState({ resume, validationIssues: [] })
  useResumeStore.temporal.getState().clear()
  render(<ResumePreview resume={resume} editable={editable} />)
  return resume
}

describe('ResumePreview — read-only (editable=false, the default)', () => {
  beforeEach(() => renderWithStore())

  it('renders every field as plain content, with no contenteditable nodes anywhere', () => {
    const { container } = { container: document.body }
    expect(container.querySelectorAll('[contenteditable]')).toHaveLength(0)
  })

  it('renders no +/- list buttons', () => {
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('still renders name, headline, summary, and an experience highlight', () => {
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument()
    expect(screen.getByText('Senior Software Engineer', { selector: '.headline' })).toBeInTheDocument()
    expect(screen.getByText(/resilient distributed systems/)).toBeInTheDocument()
    expect(screen.getByText('Led the design of a distributed computation engine.')).toBeInTheDocument()
  })
})

describe('ResumePreview — editable=true', () => {
  it('renders the header fields as contenteditable', () => {
    renderWithStore({}, true)
    expect(screen.getByText('Ada Lovelace')).toHaveAttribute('contenteditable', 'true')
    expect(screen.getByText('Senior Software Engineer', { selector: '.headline' })).toHaveAttribute(
      'contenteditable',
      'true',
    )
  })

  it('renders experience title/company and a highlight as contenteditable, with a remove button per highlight', () => {
    renderWithStore({}, true)
    expect(screen.getByText('Senior Software Engineer', { selector: '.exp-title' })).toHaveAttribute(
      'contenteditable',
      'true',
    )
    expect(screen.getByText('Analytical Engines Inc.')).toHaveAttribute('contenteditable', 'true')
    expect(
      screen.getByText('Led the design of a distributed computation engine.'),
    ).toHaveAttribute('contenteditable', 'true')
    // the default fixture has two highlights (see test/factories.ts)
    expect(screen.getAllByRole('button', { name: /remove highlight/i })).toHaveLength(2)
    expect(screen.getByRole('button', { name: /add highlight/i })).toBeInTheDocument()
  })

  it('renders each skill as contenteditable with a remove button, plus one add button', () => {
    renderWithStore({ skills: ['TypeScript', 'Python'] }, true)
    expect(screen.getByText('TypeScript')).toHaveAttribute('contenteditable', 'true')
    expect(screen.getByText('Python')).toHaveAttribute('contenteditable', 'true')
    expect(screen.getAllByRole('button', { name: /remove skill/i })).toHaveLength(2)
    expect(screen.getByRole('button', { name: /add skill/i })).toBeInTheDocument()
  })

  it('renders education fields as contenteditable, with a remove button per entry and one add button', () => {
    renderWithStore(
      { education: [{ institution: 'MIT', degree: 'B.Sc.', end: '2010', details: null }] },
      true,
    )
    expect(screen.getByText('B.Sc.')).toHaveAttribute('contenteditable', 'true')
    expect(screen.getByText('MIT')).toHaveAttribute('contenteditable', 'true')
    expect(screen.getByRole('button', { name: /remove education/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /add education/i })).toBeInTheDocument()
  })

  it('renders project name/description as contenteditable, with no +/- (projects are out of scope for lists)', () => {
    renderWithStore({ projects: [{ name: 'Note G', description: 'A pioneering computational algorithm.' }] }, true)
    expect(screen.getByText('Note G')).toHaveAttribute('contenteditable', 'true')
    expect(screen.getByText('A pioneering computational algorithm.')).toHaveAttribute('contenteditable', 'true')
  })

  it('clicking "Add skill" appends an empty skill via the store', async () => {
    const user = userEvent.setup()
    renderWithStore({ skills: ['TypeScript'] }, true)

    await user.click(screen.getByRole('button', { name: /add skill/i }))

    expect(useResumeStore.getState().resume?.skills).toEqual(['TypeScript', ''])
  })

  it('clicking a highlight\'s remove button removes just that highlight', async () => {
    const user = userEvent.setup()
    renderWithStore(
      {
        experience: [
          {
            company: 'A',
            title: 'Engineer',
            start: '2020',
            highlights: ['keep this', 'remove this'],
          },
        ],
      },
      true,
    )

    const removeButtons = screen.getAllByRole('button', { name: /remove highlight/i })
    await user.click(removeButtons[1])

    expect(useResumeStore.getState().resume?.experience[0].highlights).toEqual(['keep this'])
  })

  it('scopes each experience item\'s highlight buttons to that item (no cross-item leakage)', () => {
    renderWithStore(
      {
        experience: [
          { company: 'A', title: 'Engineer 1', start: '2020', highlights: ['one'] },
          { company: 'B', title: 'Engineer 2', start: '2021', highlights: ['two', 'three'] },
        ],
      },
      true,
    )
    const articles = screen.getAllByRole('article')
    expect(within(articles[0]).getAllByRole('button', { name: /remove highlight/i })).toHaveLength(1)
    expect(within(articles[1]).getAllByRole('button', { name: /remove highlight/i })).toHaveLength(2)
  })
})
