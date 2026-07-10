import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config'

// css: false — components are asserted via role/text/ARIA, never via computed
// styles, so skipping the real Tailwind/PostCSS pipeline in tests is safe and
// keeps the suite fast. Flip to true only if a future test needs real
// stylesheet cascade (e.g. asserting visibility driven purely by a CSS rule).
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
      globals: true,
      css: false,
      // e2e/ holds Playwright specs (its own test() API, own runner) — vitest's
      // default include glob would otherwise also match e2e/**/*.spec.ts.
      exclude: ['**/node_modules/**', '**/dist/**', 'e2e/**'],
    },
  }),
)
