import { SuccessBadge } from './SuccessBadge'
import type { ProfileUpdateAppliedCard as ProfileUpdateAppliedCardData } from '../../store/chatStore'

export function ProfileUpdateAppliedCard({ card }: { card: ProfileUpdateAppliedCardData }) {
  return (
    <SuccessBadge>
      Profile updated to version {card.profileVersion} · {card.summary}
    </SuccessBadge>
  )
}
