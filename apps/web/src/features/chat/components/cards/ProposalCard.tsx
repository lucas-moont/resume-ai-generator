import { useChatStore } from '../../store/chatStore'
import type { ProposalCard as ProposalCardData } from '../../store/chatStore'

const NEUTRAL_PALETTE =
  'border-stone-200 bg-stone-50 text-stone-600 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-400'
const PROPOSED_PALETTE =
  'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300'
const APPROVED_PALETTE =
  'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300'

function statusPalette(status: ProposalCardData['status']): string {
  if (status === 'approved') return APPROVED_PALETTE
  if (status === 'proposed') return PROPOSED_PALETTE
  return NEUTRAL_PALETTE // superseded
}

function statusLabel(status: ProposalCardData['status']): string {
  if (status === 'approved') return 'Aplicada — currículo gerado'
  if (status === 'superseded') return 'Substituída'
  return 'Proposta de melhorias'
}

/**
 * Discreet affordance attached to a proposal-bearing assistant bubble (v4, F4, spec §5) — the
 * prose already describes the items, so this card only carries the badge/revision/approve
 * button, never the item list itself (that stays LLM prose, rendered upstream via
 * MarkdownContent — nothing here ever needs escaping of its own).
 *
 * Button visibility is decided by the caller (MessageList): "Aprovar e gerar" shows only on
 * the LATEST message whose card has `proposalId === pendingProposalId && status ===
 * 'proposed'` — after an adjust there are two `proposed` cards sharing the same id, and only
 * the newer bubble's card should offer the button. This component still defends its own
 * invariant on top of that (`card.status === 'proposed'` gate below): an approved/superseded
 * card never renders the button even if a caller ever got the flag wrong, mirroring
 * ProfileUpdatedCard's own `isProposed` gate.
 */
export function ProposalCard({
  card,
  showApproveButton,
  onApprove,
}: {
  card: ProposalCardData
  showApproveButton: boolean
  onApprove: () => void
}) {
  const streaming = useChatStore((s) => s.streaming)

  return (
    <div className={`mt-2 rounded-xl border px-3 py-2.5 text-sm ${statusPalette(card.status)}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">{statusLabel(card.status)}</span>
        {card.revision > 1 && <span className="text-xs opacity-80">revisão {card.revision}</span>}
      </div>

      {card.status === 'proposed' && showApproveButton && (
        <div className="mt-2">
          <button
            type="button"
            onClick={onApprove}
            disabled={streaming !== null}
            className="inline-flex items-center rounded-lg bg-amber-900 px-2.5 py-1 text-xs font-medium text-white shadow-sm hover:bg-amber-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 disabled:pointer-events-none disabled:opacity-50 dark:bg-amber-200 dark:text-amber-950 dark:hover:bg-amber-100"
          >
            Aprovar e gerar
          </button>
        </div>
      )}
    </div>
  )
}
