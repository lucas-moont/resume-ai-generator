import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MarkdownContent } from './MarkdownContent'

describe('MarkdownContent', () => {
  it('renders GFM lists', () => {
    render(<MarkdownContent content={'- one\n- two\n- three'} />)

    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(3)
    expect(items[0]).toHaveTextContent('one')
  })

  it('renders bold and italic emphasis', () => {
    render(<MarkdownContent content={'**bold** and *italic*'} />)

    expect(screen.getByText('bold').tagName).toBe('STRONG')
    expect(screen.getByText('italic').tagName).toBe('EM')
  })

  it('renders inline code', () => {
    render(<MarkdownContent content={'run `npm test` now'} />)

    expect(screen.getByText('npm test').tagName).toBe('CODE')
  })

  it('renders fenced code blocks', () => {
    render(<MarkdownContent content={'```\nconst x = 1\n```'} />)

    expect(screen.getByText('const x = 1').tagName).toBe('CODE')
  })

  it('maps h1-h3 headings to chat-scaled headings, never a giant page h1', () => {
    render(<MarkdownContent content={'# Heading 1\n## Heading 2\n### Heading 3'} />)

    const h1 = screen.getByRole('heading', { level: 1, name: 'Heading 1' })
    const h2 = screen.getByRole('heading', { level: 2, name: 'Heading 2' })
    const h3 = screen.getByRole('heading', { level: 3, name: 'Heading 3' })

    // Contained inside the bubble: no default browser giant heading sizes.
    expect(h1.className).not.toMatch(/text-4xl|text-3xl|text-5xl/)
    expect(h1.className).toMatch(/text-(base|lg|sm)/)
    expect(h2.className.length).toBeGreaterThan(0)
    expect(h3.className.length).toBeGreaterThan(0)
  })

  it('escapes raw <script> tags as visible text instead of executing/injecting them', () => {
    const { container } = render(<MarkdownContent content={'before <script>alert(1)</script> after'} />)

    expect(container.querySelector('script')).not.toBeInTheDocument()
    expect(container.textContent).toContain('<script>alert(1)</script>')
  })

  it('escapes raw <img onerror> tags as visible text instead of creating an img element', () => {
    const { container } = render(
      <MarkdownContent content={'<img src=x onerror="alert(1)">'} />,
    )

    expect(container.querySelector('img')).not.toBeInTheDocument()
    expect(container.textContent).toContain('<img src=x onerror="alert(1)">')
  })

  it('forces rel=noopener noreferrer and target=_blank on links regardless of markdown source', () => {
    render(<MarkdownContent content={'[SmartHow](https://smarthow.com)'} />)

    const link = screen.getByRole('link', { name: 'SmartHow' })
    expect(link).toHaveAttribute('href', 'https://smarthow.com')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('renders plain text without markdown syntax visually equivalent to the current whitespace-pre-wrap look (single paragraph, no stray markup)', () => {
    const { container } = render(<MarkdownContent content={'Just a plain sentence.'} />)

    expect(screen.getByText('Just a plain sentence.')).toBeInTheDocument()
    expect(container.querySelectorAll('p')).toHaveLength(1)
  })

  it('renders multiple paragraphs with spacing between them', () => {
    render(<MarkdownContent content={'First paragraph.\n\nSecond paragraph.'} />)

    expect(screen.getByText('First paragraph.')).toBeInTheDocument()
    expect(screen.getByText('Second paragraph.')).toBeInTheDocument()
  })
})
