import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// packages/resume-templates lives at the monorepo root, a sibling of apps/,
// not under apps/web — the CSS there is the single source of truth shared
// with apps/api/app/services/pdf_export.py (which reads it via a relative
// filesystem path, not this alias).
const resumeTemplatesDir = fileURLToPath(new URL('../../packages/resume-templates', import.meta.url))

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@resume-templates': resumeTemplatesDir,
    },
  },
  server: {
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
    fs: {
      allow: [fileURLToPath(new URL('../..', import.meta.url)), resumeTemplatesDir],
    },
  },
})
