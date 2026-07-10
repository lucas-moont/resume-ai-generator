import type { ProfileUpdateAppliedCard as ProfileUpdateAppliedCardData } from '../../store/chatStore'

export function ProfileUpdateAppliedCard({ card }: { card: ProfileUpdateAppliedCardData }) {
  return (
    <div className="mt-2 flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">
      <svg aria-hidden="true" viewBox="0 0 20 20" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="m4 10 4 4 8-8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span>
        Profile updated to version {card.profileVersion} · {card.summary}
      </span>
    </div>
  )
}
