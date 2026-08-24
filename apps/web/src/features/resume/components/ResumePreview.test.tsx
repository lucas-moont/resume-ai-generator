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
    // Scoped to `.main-skills`: a technology legitimately appears in BOTH the
    // skills section and a role's Key Technologies line (the default fixture has
    // TypeScript in both), so an unscoped getByText matches two nodes.
    const skills = document.querySelector('.main-skills') as HTMLElement
    expect(within(skills).getByText('TypeScript')).toHaveAttribute('contenteditable', 'true')
    expect(within(skills).getByText('Python')).toHaveAttribute('contenteditable', 'true')
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

  it('renders project name/description as contenteditable, with a remove button per entry and one add button', () => {
    renderWithStore({ projects: [{ name: 'Note G', description: 'A pioneering computational algorithm.' }] }, true)
    expect(screen.getByText('Note G')).toHaveAttribute('contenteditable', 'true')
    expect(screen.getByText('A pioneering computational algorithm.')).toHaveAttribute('contenteditable', 'true')
    expect(screen.getByRole('button', { name: /remove project/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /add project/i })).toBeInTheDocument()
  })

  it('renders a remove button per experience entry and one add button', () => {
    renderWithStore(
      {
        experience: [
          { company: 'A', title: 'Engineer 1', start: '2020', highlights: [] },
          { company: 'B', title: 'Engineer 2', start: '2021', highlights: [] },
        ],
      },
      true,
    )
    expect(screen.getAllByRole('button', { name: /remove experience/i })).toHaveLength(2)
    expect(screen.getByRole('button', { name: /add experience/i })).toBeInTheDocument()
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

  it('clicking an experience entry\'s remove button removes just that entry', async () => {
    const user = userEvent.setup()
    renderWithStore(
      {
        experience: [
          { company: 'A', title: 'Engineer 1', start: '2020', highlights: [] },
          { company: 'B', title: 'Engineer 2', start: '2021', highlights: [] },
        ],
      },
      true,
    )

    const removeButtons = screen.getAllByRole('button', { name: /remove experience/i })
    await user.click(removeButtons[0])

    expect(useResumeStore.getState().resume?.experience).toEqual([
      { company: 'B', title: 'Engineer 2', start: '2021', highlights: [] },
    ])
  })

  it('clicking "Add experience" appends a blank experience entry via the store', async () => {
    const user = userEvent.setup()
    renderWithStore({ experience: [{ company: 'A', title: 'Engineer', start: '2020', highlights: [] }] }, true)

    await user.click(screen.getByRole('button', { name: /add experience/i }))

    expect(useResumeStore.getState().resume?.experience).toHaveLength(2)
    expect(useResumeStore.getState().resume?.experience[1]).toMatchObject({ company: '', title: '' })
  })

  it('clicking a project entry\'s remove button removes just that entry', async () => {
    const user = userEvent.setup()
    renderWithStore(
      {
        projects: [
          { name: 'Note G', description: 'Old' },
          { name: 'Second', description: 'Other' },
        ],
      },
      true,
    )

    const removeButtons = screen.getAllByRole('button', { name: /remove project/i })
    await user.click(removeButtons[0])

    expect(useResumeStore.getState().resume?.projects).toEqual([{ name: 'Second', description: 'Other' }])
  })

  it('clicking "Add project" appends a blank project entry via the store', async () => {
    const user = userEvent.setup()
    renderWithStore({ projects: [{ name: 'Note G', description: 'Old' }] }, true)

    await user.click(screen.getByRole('button', { name: /add project/i }))

    expect(useResumeStore.getState().resume?.projects).toHaveLength(2)
    expect(useResumeStore.getState().resume?.projects[1]).toMatchObject({ name: '', description: '' })
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


describe('ResumePreview — Key Technologies line (v7)', () => {
  it('renders one node per technology, with no literal commas in the text', () => {
    // The separators are painted by CSS (.exp-tech-list li::after) so a comma
    // never lands in the text an inline edit would commit.
    renderWithStore()
    const line = document.querySelector('.exp-tech') as HTMLElement
    expect(line).toBeInTheDocument()
    const items = line.querySelectorAll('.exp-tech-list li')
    expect(items).toHaveLength(2)
    expect(items[0].textContent).toBe('TypeScript')
    expect(items[1].textContent).toBe('PostgreSQL')
  })

  it('labels the line in the document language', () => {
    renderWithStore({ locale: 'en' })
    expect(document.querySelector('.exp-tech-label')?.textContent).toBe('Key Technologies:')
  })

  it('labels the line in Portuguese for a pt-BR document', () => {
    renderWithStore({ locale: 'pt-BR' })
    expect(document.querySelector('.exp-tech-label')?.textContent).toBe('Tecnologias-chave:')
  })

  it('renders nothing at all when the role has no technologies', () => {
    renderWithStore({
      experience: [
        {
          company: 'Acme',
          title: 'Dev',
          location: null,
          start: '2020',
          end: null,
          highlights: ['Did the thing.'],
          keyTechnologies: [],
        },
      ],
    })
    expect(document.querySelector('.exp-tech')).not.toBeInTheDocument()
  })

  it('renders nothing when the field is absent, as on a resume saved before it existed', () => {
    // localStorage rehydration path: the persisted document has no such key, and
    // there is no migration that backfills it (see types/resume.ts).
    renderWithStore({
      experience: [
        {
          company: 'Acme',
          title: 'Dev',
          location: null,
          start: '2020',
          end: null,
          highlights: ['Did the thing.'],
        },
      ],
    })
    expect(document.querySelector('.exp-tech')).not.toBeInTheDocument()
  })

  it('exposes a remove button per technology and one add button when editable', () => {
    renderWithStore({}, true)
    expect(screen.getAllByRole('button', { name: /remove key technology/i })).toHaveLength(2)
    expect(screen.getByRole('button', { name: /add key technology/i })).toBeInTheDocument()
  })

  it('commits an inline edit of a technology to the store', async () => {
    const user = userEvent.setup()
    renderWithStore({}, true)
    const line = document.querySelector('.exp-tech-list') as HTMLElement
    const node = within(line).getByText('PostgreSQL')

    await user.click(node)
    node.textContent = 'MySQL'
    await user.tab()

    expect(useResumeStore.getState().resume?.experience[0].keyTechnologies).toEqual([
      'TypeScript',
      'MySQL',
    ])
  })
})
