import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { AnalysisCard } from './AnalysisCard'
import { renderApp } from '../../../test/render'
import type { AnalysisItemDto } from '../../../lib/api/dto'

const HEADLINE: AnalysisItemDto = {
  section: 'headline',
  current: 'Dev',
  suggestion: 'Desenvolvedor Backend | Python & APIs | Alta disponibilidade',
  rationale: 'Front-load os termos que recruiters buscam.',
  priority: 'alta',
}

describe('AnalysisCard', () => {
  it('renders section label, priority, current → suggestion and rationale', () => {
    renderApp(<AnalysisCard summary="Resumo geral." items={[HEADLINE]} />)

    expect(screen.getByText('Resumo geral.')).toBeInTheDocument()
    expect(screen.getByText('Headline')).toBeInTheDocument()
    expect(screen.getByText('Alta')).toBeInTheDocument()
    expect(screen.getByText('Dev')).toBeInTheDocument() // current
    expect(screen.getByText(HEADLINE.suggestion)).toBeInTheDocument()
    expect(screen.getByText(/front-load/i)).toBeInTheDocument()
  })

  it('shows a character counter for the headline', () => {
    renderApp(<AnalysisCard summary="" items={[HEADLINE]} />)
    expect(screen.getByText(`${HEADLINE.suggestion.length}/220 caracteres`)).toBeInTheDocument()
  })

  it('flags a headline over 220 characters', () => {
    const long = { ...HEADLINE, suggestion: 'x'.repeat(230) }
    renderApp(<AnalysisCard summary="" items={[long]} />)
    expect(screen.getByText('230/220 caracteres')).toBeInTheDocument()
  })

  it('copies the suggestion to the clipboard', async () => {
    const user = userEvent.setup()
    renderApp(<AnalysisCard summary="" items={[HEADLINE]} />)

    const button = screen.getByRole('button', { name: /copiar sugestão/i })
    await user.click(button)

    expect(await navigator.clipboard.readText()).toBe(HEADLINE.suggestion)
    await waitFor(() => expect(button).toHaveTextContent('Copiado!'))
  })

  it('renders one card per item', () => {
    const completeness: AnalysisItemDto = {
      section: 'completeness',
      current: null,
      suggestion: 'Adicione uma seção Sobre.',
      rationale: 'Perfis sem Sobre têm menos visibilidade.',
      priority: 'média',
    }
    renderApp(<AnalysisCard summary="" items={[HEADLINE, completeness]} />)
    expect(screen.getByText('Headline')).toBeInTheDocument()
    expect(screen.getByText('Completude')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /copiar sugestão/i })).toHaveLength(2)
  })
})
