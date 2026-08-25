import type { JobListingDto } from '../../../lib/api/dto'
import { useListing } from '../hooks/useListings'
import { useOneClickResume, useOpenInChat } from '../hooks/useOneClickResume'
import {
  applicantBandLabel,
  boardLabel,
  formatPlace,
  formatPostedAt,
  listingStatusLabel,
} from '../listingFormat'

/** v7 ticket 13 — the selected Job Listing in full: the posting's text, every Listing Source
 * with the board that carries it, and the two actions.
 *
 * The description lives here and nowhere else — the list response omits it on purpose — so
 * opening this panel is also what marks the listing `seen` (the backend does it on the GET;
 * `useListing` invalidates the list so the card catches up).
 */

interface ListingDetailProps {
  listingId: number
  onClose: () => void
}

const HINT_CLASS = 'px-1 py-6 text-sm text-stone-500 dark:text-zinc-400'

const NEUTRAL = 'bg-stone-100 text-stone-600 dark:bg-zinc-800 dark:text-zinc-300'
const STRONG = 'bg-stone-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
const ACCENT = 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300'
const WARN = 'bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300'

const PRIMARY_BUTTON =
  'inline-flex min-h-[2rem] items-center gap-2 rounded-lg bg-stone-900 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition-colors hover:bg-stone-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-950 dark:hover:bg-zinc-200 dark:focus-visible:ring-zinc-500'

const SECONDARY_BUTTON =
  'inline-flex min-h-[2rem] items-center gap-2 rounded-lg border border-stone-200 px-3 py-1.5 text-xs font-medium text-stone-700 transition-colors hover:bg-stone-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800 dark:focus-visible:ring-zinc-500'

function Badge({ children, tone, title }: { children: string; tone: string; title?: string }) {
  return (
    <li>
      <span
        title={title}
        className={`inline-block rounded-full px-2 py-0.5 text-[0.6875rem] font-medium ${tone}`}
      >
        {children}
      </span>
    </li>
  )
}

/** Purely decorative: the button's own label already says "Gerando…", and a screen reader
 * reading "image" here would add nothing. */
function Spinner() {
  return (
    <span
      aria-hidden="true"
      className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
    />
  )
}

/** Boards ship postings with Windows line endings and long runs of blank lines; collapsing them
 * is the whole of "clean text" here. Nothing is stripped — the text renders as text
 * (`whitespace-pre-wrap`), never as markup, so there is no HTML to sanitize. */
function cleanDescription(description: string): string {
  return description.replace(/\r\n?/g, '\n').replace(/\n{3,}/g, '\n\n').trim()
}

function OneClickActions({ listing }: { listing: JobListingDto }) {
  const oneClick = useOneClickResume(listing)
  const openInChat = useOpenInChat(listing.id)

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        {!oneClick.canGenerate ? (
          <button type="button" disabled title={oneClick.disabledReason ?? undefined} className={PRIMARY_BUTTON}>
            Gerar currículo em um clique
          </button>
        ) : oneClick.hasResume ? (
          <>
            <button
              type="button"
              onClick={() => oneClick.run(false)}
              disabled={oneClick.isPending}
              aria-busy={oneClick.isPending && !oneClick.pendingRegenerate}
              className={PRIMARY_BUTTON}
              title="Baixa o currículo já gerado para esta vaga, sem gastar uma nova chamada de IA."
            >
              {oneClick.isPending && !oneClick.pendingRegenerate && <Spinner />}
              {oneClick.isPending && !oneClick.pendingRegenerate ? 'Baixando…' : 'Baixar PDF'}
            </button>
            <button
              type="button"
              onClick={() => oneClick.run(true)}
              disabled={oneClick.isPending}
              aria-busy={oneClick.isPending && oneClick.pendingRegenerate}
              className={SECONDARY_BUTTON}
              title="Gera de novo do zero — gasta uma chamada de IA."
            >
              {oneClick.isPending && oneClick.pendingRegenerate && <Spinner />}
              {oneClick.isPending && oneClick.pendingRegenerate ? 'Gerando…' : 'Regerar'}
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => oneClick.run(false)}
            disabled={oneClick.isPending}
            aria-busy={oneClick.isPending}
            className={PRIMARY_BUTTON}
          >
            {oneClick.isPending && <Spinner />}
            {oneClick.isPending ? 'Gerando…' : 'Gerar currículo em um clique'}
          </button>
        )}

        <button
          type="button"
          onClick={() => openInChat.mutate()}
          disabled={openInChat.isPending}
          className={SECONDARY_BUTTON}
          title="Abre a vaga no chat com a proposta de melhorias para você revisar."
        >
          {openInChat.isPending ? 'Abrindo…' : 'Abrir no chat'}
        </button>
      </div>

      {oneClick.isPending && (
        <p role="status" className="mt-2 text-xs text-stone-500 dark:text-zinc-400">
          Gerando o currículo desta vaga — a análise e a geração rodam nesta chamada, leva alguns
          instantes.
        </p>
      )}

      {!oneClick.canGenerate && (
        <p className="mt-2 text-xs text-stone-500 dark:text-zinc-400">
          {oneClick.disabledReason}
        </p>
      )}

      {oneClick.error !== null && (
        <p role="alert" className="mt-2 text-xs text-red-600 dark:text-red-400">
          {oneClick.error}
        </p>
      )}

      {openInChat.isError && (
        <p role="alert" className="mt-2 text-xs text-red-600 dark:text-red-400">
          Não foi possível abrir esta vaga no chat.
        </p>
      )}
    </div>
  )
}

export function ListingDetail({ listingId, onClose }: ListingDetailProps) {
  const { data: listing, isLoading, isError } = useListing(listingId)

  if (isLoading) {
    return (
      <p role="status" className={HINT_CLASS}>
        Carregando a vaga…
      </p>
    )
  }

  if (isError || !listing) {
    return (
      <p role="alert" className={HINT_CLASS}>
        Não foi possível carregar esta vaga.
      </p>
    )
  }

  return (
    <article className="flex min-h-0 flex-col gap-3">
      <header>
        <div className="flex items-start justify-between gap-2">
          <h2 className="text-base font-semibold text-stone-900 dark:text-zinc-50">
            {listing.title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar detalhe da vaga"
            className="rounded-lg px-2 py-0.5 text-sm text-stone-400 hover:bg-stone-100 hover:text-stone-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:text-zinc-500 dark:hover:bg-zinc-800 dark:hover:text-zinc-200 dark:focus-visible:ring-zinc-500"
          >
            ✕
          </button>
        </div>
        <p className="mt-0.5 text-xs text-stone-600 dark:text-zinc-400">
          {listing.company} · {formatPlace(listing)}
        </p>
        <p className="mt-0.5 text-xs text-stone-400 dark:text-zinc-500">
          {formatPostedAt(listing.datePosted)}
        </p>
      </header>

      <ul className="flex flex-wrap items-center gap-1.5">
        <Badge
          tone={STRONG}
          title={
            listing.fitEstimated
              ? 'Fit estimado pelo filtro de palavras-chave — a vaga ficou fora do top pontuado pelo modelo neste Scan.'
              : 'Fit calculado pelo modelo.'
          }
        >
          {`Fit ${listing.fitEstimated ? '~' : ''}${listing.fitScore}%`}
        </Badge>
        <Badge tone={ACCENT} title="Chance de o currículo ser visto: fit + recência + concorrência.">
          {`Visibilidade ${listing.visibilityScore}`}
        </Badge>
        <Badge tone={NEUTRAL}>{applicantBandLabel(listing.applicantBand)}</Badge>
        {listing.isRepost && (
          <Badge tone={WARN} title="Vaga já conhecida que reapareceu com data mais nova.">
            Repostada
          </Badge>
        )}
        <Badge tone={NEUTRAL}>{listingStatusLabel(listing.status)}</Badge>
      </ul>

      <OneClickActions listing={listing} />

      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-stone-500 dark:text-zinc-400">
          Onde esta vaga está
        </h3>
        {/* Every Listing Source is kept and named: dedup must not cost the user the board they
            would rather apply on, and naming the board beside its link is what Remotive's and
            Remote OK's terms require. */}
        <ul aria-label="Fontes da vaga" className="mt-1.5 flex flex-col gap-1">
          {listing.sources.map((source) => (
            <li key={`${source.board}-${source.url}`} className="text-xs">
              <a
                href={source.url}
                target="_blank"
                rel="noreferrer"
                className="font-medium text-stone-800 underline underline-offset-2 hover:text-stone-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:text-zinc-200 dark:hover:text-zinc-50 dark:focus-visible:ring-zinc-500"
              >
                {boardLabel(source.board)}
              </a>
              <span className="text-stone-400 dark:text-zinc-500">
                {` · ${applicantBandLabel(source.applicantBand)} · ${formatPostedAt(source.datePosted)}`}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="flex min-h-0 flex-col">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-stone-500 dark:text-zinc-400">
          Descrição
        </h3>
        {/* Focusable because it scrolls: a keyboard user has no other way to reach the rest of a
            long posting. */}
        <div
          tabIndex={0}
          role="region"
          aria-label="Descrição da vaga"
          className="mt-1.5 max-h-[24rem] overflow-y-auto whitespace-pre-wrap rounded-lg border border-stone-200 bg-white p-3 text-xs leading-relaxed text-stone-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:focus-visible:ring-zinc-500"
        >
          {listing.description === null || listing.description.trim() === ''
            ? 'Esta vaga veio sem descrição. Abra o link do portal.'
            : cleanDescription(listing.description)}
        </div>
      </section>
    </article>
  )
}
