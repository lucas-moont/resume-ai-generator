import { SuccessBadge } from './SuccessBadge'
import type { ProfileUpdateAppliedCard as ProfileUpdateAppliedCardData } from '../../store/chatStore'

export function ProfileUpdateAppliedCard({ card }: { card: ProfileUpdateAppliedCardData }) {
  return (
    <SuccessBadge>
      Profile updated
      {/* Label-only fallback (v3 ticket 12): a history reload has no "before" SSE event to
          carry profileVersion/summary, so this degrades the same honest way ResumeUpdatedCard
          already does when it has no diff to show. */}
      {card.profileVersion !== undefined && <> to version {card.profileVersion}</>}
      {card.summary && <> · {card.summary}</>}
    </SuccessBadge>
  )
}
