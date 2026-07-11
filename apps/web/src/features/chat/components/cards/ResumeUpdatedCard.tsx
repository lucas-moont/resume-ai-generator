import { SuccessBadge } from './SuccessBadge'
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
    <SuccessBadge>
      Resume updated · see the preview
      {sectionLabels.length > 0 && (
        <span className="text-emerald-700/80 dark:text-emerald-400/80"> ({sectionLabels.join(', ')})</span>
      )}
    </SuccessBadge>
  )
}
