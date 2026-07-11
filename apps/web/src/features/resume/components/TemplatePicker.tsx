import { TEMPLATE_REGISTRY, type TemplateId } from '../templates/registry'
import { TemplateThumbnail } from './TemplateThumbnail'

export function TemplatePicker({
  value,
  onChange,
}: {
  value: TemplateId
  onChange: (id: TemplateId) => void
}) {
  return (
    <div>
      <label
        htmlFor="template-picker"
        className="mb-1 block text-[0.6875rem] font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500"
      >
        Template
      </label>
      <div className="relative">
        <select
          id="template-picker"
          value={value}
          onChange={(e) => onChange(e.target.value as TemplateId)}
          className="w-full appearance-none rounded-lg border border-stone-200 bg-white py-1.5 pl-2.5 pr-8 text-sm text-stone-900 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:focus-visible:ring-zinc-500"
        >
          {TEMPLATE_REGISTRY.map((t) => (
            <option key={t.id} value={t.id}>
              {t.label}
            </option>
          ))}
        </select>
        <svg
          aria-hidden="true"
          viewBox="0 0 20 20"
          className="pointer-events-none absolute bottom-1.5 right-2.5 h-4 w-4 text-stone-500 dark:text-zinc-500"
        >
          <path d="m5 7 5 6 5-6" fill="none" stroke="currentColor" strokeWidth="1.8" />
        </svg>
      </div>
      {/*
        Thumbnail previews for all 8 templates. The <select> above stays the
        primary control (native semantics, keyboard nav, and what the
        existing template-switch e2e spec drives via selectOption) — these
        buttons are a supplementary, instant, no-network way to pick the same
        value, grouped separately so screen readers don't see two controls
        both named "Template".
      */}
      <div role="group" aria-label="Template previews" className="mt-2 grid grid-cols-4 gap-1.5">
        {TEMPLATE_REGISTRY.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => onChange(t.id as TemplateId)}
            aria-pressed={value === t.id}
            aria-label={`${t.label} template`}
            title={t.label}
            className={`rounded-md border p-1 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:focus-visible:ring-zinc-500 ${
              value === t.id
                ? 'border-indigo-400 ring-1 ring-indigo-400 dark:border-indigo-500 dark:ring-indigo-500'
                : 'border-stone-200 hover:border-stone-300 dark:border-zinc-700 dark:hover:border-zinc-600'
            }`}
          >
            <TemplateThumbnail tags={t.tags} className="h-10 w-full" />
          </button>
        ))}
      </div>
    </div>
  )
}
