import { TEMPLATE_REGISTRY, type TemplateId } from '../templates/registry'

export function TemplatePicker({
  value,
  onChange,
}: {
  value: TemplateId
  onChange: (id: TemplateId) => void
}) {
  return (
    <div className="relative">
      <label
        htmlFor="template-picker"
        className="mb-1 block text-[0.6875rem] font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500"
      >
        Template
      </label>
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
  )
}
