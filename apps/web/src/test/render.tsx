import { render, type RenderOptions } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement } from 'react'
import { ThemeProvider } from '../app/theme/ThemeProvider'

/**
 * Renders `ui` wrapped in the same providers main.tsx wraps <App /> with
 * (QueryClientProvider, ThemeProvider). Tests disable retries so failed
 * queries settle immediately instead of the app's real retry:1 default.
 */
export function renderApp(ui: ReactElement, options?: RenderOptions) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>{ui}</ThemeProvider>
    </QueryClientProvider>,
    options,
  )
}
