import type { ResumeUpdatedCard as ResumeUpdatedCardData } from '../../store/chatStore'

const SECTION_LABELS: Record<string, string> = {
  fullName: 'name',
  headline: 'headline',
  location: 'location',
  email: 'email',
  phone: 'phone',
  links: 'links',
  summary: 'summary',
  experience: 'experience',
  projects: 'projects',
  skills: 'skills',
  education: 'education',
}

export function ResumeUpdatedCard({ card }: { card: ResumeUpdatedCardData }) {
  const sectionLabels = card.changedSections.map((s) => SECTION_LABELS[s] ?? s)
  return (
    <div className="mt-2 flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">
      <svg aria-hidden="true" viewBox="0 0 20 20" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="m4 10 4 4 8-8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span>
        Resume updated · see the preview
        {sectionLabels.length > 0 && (
          <span className="text-emerald-700/80 dark:text-emerald-400/80"> ({sectionLabels.join(', ')})</span>
        )}
      </span>
    </div>
  )
}
