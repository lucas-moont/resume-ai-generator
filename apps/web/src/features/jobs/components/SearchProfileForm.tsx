import { useState, type FormEvent, type KeyboardEvent } from 'react'
import type {
  BoardDto,
  BoardId,
  MaxApplicantBand,
  RemotePreference,
  ScanIntervalHours,
  SearchProfileDto,
  SearchProfileUpdateRequest,
} from '../../../lib/api/dto'
import {
  useBoards,
  useSearchProfile,
  useSuggestSearchProfile,
  useUpdateSearchProfile,
} from '../hooks/useSearchProfile'

/** v7 ticket 14 — the Search Profile form (CONTEXT.md: Search Profile).
 *
 * Self-contained: no props, it loads and saves itself. `JobsShell` (ticket 12) just drops
 * `<SearchProfileForm />` into its left column, the same way `AppHeader` drops in
 * `<SettingsDialog />`.
 *
 * The whole profile is sent on every save (`SearchProfileUpdateRequest` is not a patch), so the
 * form owns ONE draft object and the PUT sends it verbatim.
 */

const LEGEND_CLASS =
  'mb-2 text-[0.6875rem] font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-300'

const FIELD_CLASS =
  'h-9 w-full rounded-lg border border-stone-200 bg-white px-2.5 text-sm text-stone-900 shadow-sm placeholder:text-stone-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder:text-zinc-300'

const OPTION_ROW_CLASS =
  'flex items-center justify-between gap-2 rounded-lg border border-stone-200 px-3 py-2 text-sm text-stone-800 has-[:checked]:border-stone-400 dark:border-zinc-700 dark:text-zinc-200 dark:has-[:checked]:border-zinc-500'

const NOTE_CLASS = 'text-xs text-stone-500 dark:text-zinc-300'

const ALERT_CLASS = 'text-xs text-red-600 dark:text-red-400'

const REMOTE_OPTIONS: { value: RemotePreference; label: string }[] = [
  { value: 'any', label: 'Tanto faz' },
  { value: 'remote_only', label: 'Só remoto' },
  { value: 'onsite_ok', label: 'Presencial/híbrido também' },
]

/** The toggles the form offers. `languages` is a free-form list on the wire (a posting in
 * Spanish may still be one this user wants), so anything else already saved is preserved as a
 * removable chip instead of being silently dropped by a save. */
const KNOWN_LANGUAGES: { code: string; label: string }[] = [
  { code: 'pt', label: 'Português' },
  { code: 'en', label: 'Inglês' },
]

/** Only the four `<` bands are offerable as a cap: `100+`/`unknown` as a ceiling would mean
 * "everything", which `null` ("qualquer") already says. */
const MAX_BAND_OPTIONS: MaxApplicantBand[] = ['<10', '<25', '<50', '<100']

const INTERVAL_OPTIONS: ScanIntervalHours[] = [1, 3, 6, 12, 24]

/** Remotive and Remote OK require naming the source beside each result. Surfaced here, at the
 * moment the user turns the board ON, and again on every Listing Source chip (ticket 12). */
const ATTRIBUTION_BOARDS: readonly BoardId[] = ['remotive', 'remoteok']

function toDraft(profile: SearchProfileDto): SearchProfileUpdateRequest {
  return {
    roles: [...profile.roles],
    locations: [...profile.locations],
    remote: profile.remote,
    languages: [...profile.languages],
    boards: [...profile.boards],
    maxApplicantBand: profile.maxApplicantBand,
    intervalHours: profile.intervalHours,
  }
}

export function SearchProfileForm() {
  const profileQuery = useSearchProfile()
  const boardsQuery = useBoards()

  if (profileQuery.isLoading || boardsQuery.isLoading) {
    return <p className="text-sm text-stone-500 dark:text-zinc-300">Carregando perfil de busca…</p>
  }
  if (profileQuery.isError || boardsQuery.isError || !profileQuery.data || !boardsQuery.data) {
    return (
      <p role="alert" className="text-sm text-red-600 dark:text-red-400">
        Não foi possível carregar o perfil de busca.
      </p>
    )
  }

  return (
    <SearchProfileFields profile={profileQuery.data} boards={boardsQuery.data.boards} />
  )
}

interface SearchProfileFieldsProps {
  profile: SearchProfileDto
  boards: BoardDto[]
}

/**
 * Mounted only once both queries resolved, so the draft is derived from real data at mount
 * instead of synced in by an effect (same pattern as `GithubUsernameRow`).
 */
function SearchProfileFields({ profile, boards }: SearchProfileFieldsProps) {
  const [draft, setDraft] = useState<SearchProfileUpdateRequest>(() => toDraft(profile))
  const [suggested, setSuggested] = useState(false)
  const save = useUpdateSearchProfile()
  const suggest = useSuggestSearchProfile()

  /** Every edit also clears the outcome of the LAST save/suggest: "Perfil de busca salvo." must
   * not keep standing over a draft that has since been changed. */
  const patch = (fields: Partial<SearchProfileUpdateRequest>) => {
    setDraft((current) => ({ ...current, ...fields }))
    setSuggested(false)
    if (save.isSuccess || save.isError) save.reset()
    if (suggest.isError) suggest.reset()
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSuggested(false)
    save.mutate(draft)
  }

  const handleSuggest = () => {
    suggest.mutate(undefined, {
      onSuccess: (suggestion) => {
        // A suggestion is never persisted (`updatedAt: null`) — it only fills the draft, and the
        // user saves it with a normal PUT like anything else they typed.
        setDraft(toDraft(suggestion))
        setSuggested(true)
      },
    })
  }

  const hasLanguage = (code: string) => draft.languages.some((l) => l.toLowerCase() === code)

  const toggleLanguage = (code: string) => {
    patch({
      languages: hasLanguage(code)
        ? draft.languages.filter((l) => l.toLowerCase() !== code)
        : [...draft.languages, code],
    })
  }

  const extraLanguages = draft.languages.filter(
    (l) => !KNOWN_LANGUAGES.some((known) => known.code === l.toLowerCase()),
  )

  const toggleBoard = (id: BoardId) => {
    patch({
      boards: draft.boards.includes(id)
        ? draft.boards.filter((board) => board !== id)
        : [...draft.boards, id],
    })
  }

  // `max(user interval, board minimum)` is what the Scan actually uses, so a 1h interval must not
  // silently read as 1h for every board.
  const throttledBoards =
    draft.intervalHours === null
      ? []
      : boards.filter(
          (board) =>
            draft.boards.includes(board.id) && board.minIntervalHours > (draft.intervalHours ?? 0),
        )

  const busy = save.isPending || suggest.isPending

  return (
    <form onSubmit={handleSubmit} aria-label="Perfil de busca" className="space-y-5">
      <ChipField
        idPrefix="search-profile-roles"
        legend="Cargos-alvo"
        inputLabel="Adicionar cargo"
        placeholder="Ex.: Backend Engineer"
        values={draft.roles}
        removeLabel={(value) => `Remover cargo ${value}`}
        onChange={(roles) => patch({ roles })}
      />

      <ChipField
        idPrefix="search-profile-locations"
        legend="Localizações"
        inputLabel="Adicionar localização"
        placeholder="Ex.: Brasil"
        values={draft.locations}
        removeLabel={(value) => `Remover localização ${value}`}
        onChange={(locations) => patch({ locations })}
      />

      <fieldset>
        <legend className={LEGEND_CLASS}>Remoto</legend>
        <div className="space-y-1.5">
          {REMOTE_OPTIONS.map((option) => (
            <label key={option.value} className={OPTION_ROW_CLASS}>
              <span className="flex items-center gap-2">
                <input
                  type="radio"
                  name="search-profile-remote"
                  value={option.value}
                  checked={draft.remote === option.value}
                  onChange={() => patch({ remote: option.value })}
                  className="h-4 w-4"
                />
                {option.label}
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className={LEGEND_CLASS}>Idiomas das vagas</legend>
        <div className="space-y-1.5">
          {KNOWN_LANGUAGES.map((language) => (
            <label key={language.code} className={OPTION_ROW_CLASS}>
              <span className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={hasLanguage(language.code)}
                  onChange={() => toggleLanguage(language.code)}
                  className="h-4 w-4"
                />
                {language.label}
              </span>
            </label>
          ))}
        </div>
        {extraLanguages.length > 0 && (
          <div className="mt-2">
            <p className={NOTE_CLASS}>Outros idiomas já salvos:</p>
            <ul className="mt-1 flex flex-wrap gap-1.5">
              {extraLanguages.map((language) => (
                <Chip
                  key={language}
                  value={language}
                  removeLabel={`Remover idioma ${language}`}
                  onRemove={() =>
                    patch({ languages: draft.languages.filter((l) => l !== language) })
                  }
                />
              ))}
            </ul>
          </div>
        )}
      </fieldset>

      <fieldset>
        <legend className={LEGEND_CLASS}>Portais</legend>
        <div className="space-y-1.5">
          {boards.map((board) => {
            const needsAttribution = ATTRIBUTION_BOARDS.includes(board.id)
            const noteId = `search-profile-board-${board.id}-note`
            return (
              <div key={board.id}>
                {/* The row, not the <label>, carries the layout: keeping "mín. 6h" OUT of the
                    label means the checkbox's accessible name stays the board's name, with the
                    attribution wired in through aria-describedby instead. */}
                <div className={OPTION_ROW_CLASS}>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={draft.boards.includes(board.id)}
                      onChange={() => toggleBoard(board.id)}
                      aria-describedby={needsAttribution ? noteId : undefined}
                      className="h-4 w-4"
                    />
                    {board.displayName}
                  </label>
                  {board.minIntervalHours > 1 && (
                    <span className="text-xs text-stone-500 dark:text-zinc-300">
                      mín. {board.minIntervalHours}h
                    </span>
                  )}
                </div>
                {needsAttribution && (
                  <p id={noteId} className={`mt-0.5 px-3 ${NOTE_CLASS}`}>
                    Os termos deste portal exigem citar a fonte em cada vaga.
                  </p>
                )}
              </div>
            )
          })}
        </div>
      </fieldset>

      <div className="space-y-1">
        <label htmlFor="search-profile-max-band" className={`block ${LEGEND_CLASS}`}>
          Máximo de candidatos
        </label>
        <select
          id="search-profile-max-band"
          value={draft.maxApplicantBand ?? ''}
          onChange={(event) =>
            patch({
              maxApplicantBand: event.target.value
                ? (event.target.value as MaxApplicantBand)
                : null,
            })
          }
          className={FIELD_CLASS}
        >
          {MAX_BAND_OPTIONS.map((band) => (
            <option key={band} value={band}>
              {band}
            </option>
          ))}
          <option value="">qualquer</option>
        </select>
        <p className={NOTE_CLASS}>
          Vaga sem número de candidatos nunca é excluída por este teto.
        </p>
      </div>

      <div className="space-y-1">
        <label htmlFor="search-profile-interval" className={`block ${LEGEND_CLASS}`}>
          Intervalo de varredura
        </label>
        <select
          id="search-profile-interval"
          value={draft.intervalHours === null ? '' : String(draft.intervalHours)}
          onChange={(event) =>
            patch({
              intervalHours: event.target.value
                ? (Number(event.target.value) as ScanIntervalHours)
                : null,
            })
          }
          className={FIELD_CLASS}
        >
          {INTERVAL_OPTIONS.map((hours) => (
            <option key={hours} value={hours}>
              {hours}h
            </option>
          ))}
          <option value="">off</option>
        </select>
        {draft.intervalHours === null ? (
          <p className={NOTE_CLASS}>Sem varredura automática — "Buscar agora" continua valendo.</p>
        ) : (
          throttledBoards.length > 0 && (
            <p className={NOTE_CLASS}>
              Ritmo próprio destes portais:{' '}
              {throttledBoards
                .map((board) => `${board.displayName} (${board.minIntervalHours}h)`)
                .join(', ')}
              .
            </p>
          )
        )}
      </div>

      {draft.roles.length === 0 && (
        <p role="status" className={NOTE_CLASS}>
          Sem cargos-alvo, uma varredura não tem o que buscar.
        </p>
      )}
      {draft.boards.length === 0 && (
        <p role="status" className={NOTE_CLASS}>
          Sem nenhum portal ligado, uma varredura não consulta nada.
        </p>
      )}

      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={busy}
          className="h-9 rounded-lg bg-stone-900 px-3 text-sm font-medium text-white shadow-sm hover:bg-stone-800 disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-500 dark:bg-zinc-100 dark:text-zinc-950 dark:hover:bg-white"
        >
          {save.isPending ? 'Salvando…' : 'Salvar'}
        </button>
        <button
          type="button"
          onClick={handleSuggest}
          disabled={busy}
          className="h-9 rounded-lg border border-stone-200 px-3 text-sm font-medium text-stone-700 hover:bg-stone-50 disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
        >
          {suggest.isPending ? 'Sugerindo…' : 'Sugerir do meu perfil'}
        </button>
      </div>

      {suggested && (
        <p role="status" className={NOTE_CLASS}>
          Sugestão preenchida a partir do seu perfil. Revise e clique em Salvar.
        </p>
      )}
      {save.isSuccess && (
        <p role="status" className={NOTE_CLASS}>
          Perfil de busca salvo.
        </p>
      )}
      {save.isError && (
        <p role="alert" className={ALERT_CLASS}>
          Não foi possível salvar o perfil de busca. Tente de novo.
        </p>
      )}
      {suggest.isError && (
        <p role="alert" className={ALERT_CLASS}>
          Não foi possível sugerir a partir do seu perfil. Tente de novo.
        </p>
      )}
      <p className={NOTE_CLASS}>
        {profile.updatedAt
          ? `Salvo em ${new Date(profile.updatedAt).toLocaleString('pt-BR')}.`
          : 'Ainda não salvo.'}
      </p>
    </form>
  )
}

interface ChipProps {
  value: string
  removeLabel: string
  onRemove: () => void
}

function Chip({ value, removeLabel, onRemove }: ChipProps) {
  return (
    <li className="flex items-center gap-1 rounded-full border border-stone-200 bg-stone-50 py-0.5 pl-2.5 pr-1 text-xs text-stone-800 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200">
      <span>{value}</span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={removeLabel}
        // h-6 w-6 = 24px, the a11y floor for a hit target (v4 backlog).
        className="flex h-6 w-6 items-center justify-center rounded-full text-stone-500 hover:bg-stone-200 hover:text-stone-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:text-zinc-300 dark:hover:bg-zinc-700 dark:hover:text-zinc-50"
      >
        <span aria-hidden="true">×</span>
      </button>
    </li>
  )
}

interface ChipFieldProps {
  idPrefix: string
  legend: string
  inputLabel: string
  placeholder: string
  values: string[]
  removeLabel: (value: string) => string
  onChange: (next: string[]) => void
}

/**
 * A list of free-text tags edited as chips (roles, locations). Validation mirrors the contract
 * and nothing more: the wire type is `list[str]`, so the only rules are "no blanks" and "no
 * duplicates" — both of which would reach the backend as accepted-but-useless entries.
 */
function ChipField({
  idPrefix,
  legend,
  inputLabel,
  placeholder,
  values,
  removeLabel,
  onChange,
}: ChipFieldProps) {
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const inputId = `${idPrefix}-input`
  const errorId = `${idPrefix}-error`

  const add = () => {
    const trimmed = text.trim()
    if (!trimmed) return
    if (values.some((value) => value.toLowerCase() === trimmed.toLowerCase())) {
      setError('Já está na lista.')
      return
    }
    onChange([...values, trimmed])
    setText('')
    setError(null)
  }

  // Enter adds a chip; it must never submit the surrounding form, which would save a profile
  // WITHOUT the tag the user was in the middle of typing.
  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'Enter') return
    event.preventDefault()
    add()
  }

  return (
    <fieldset>
      <legend className={LEGEND_CLASS}>{legend}</legend>
      {values.length > 0 && (
        <ul className="mb-2 flex flex-wrap gap-1.5">
          {values.map((value) => (
            <Chip
              key={value}
              value={value}
              removeLabel={removeLabel(value)}
              onRemove={() => onChange(values.filter((item) => item !== value))}
            />
          ))}
        </ul>
      )}
      <div className="flex items-center gap-2">
        <label htmlFor={inputId} className="sr-only">
          {inputLabel}
        </label>
        <input
          id={inputId}
          type="text"
          autoComplete="off"
          value={text}
          placeholder={placeholder}
          aria-describedby={error ? errorId : undefined}
          onChange={(event) => {
            setText(event.target.value)
            setError(null)
          }}
          onKeyDown={handleKeyDown}
          className={FIELD_CLASS}
        />
        <button
          type="button"
          onClick={add}
          disabled={!text.trim()}
          className="h-9 shrink-0 rounded-lg border border-stone-200 px-2.5 text-xs font-medium text-stone-700 hover:bg-stone-50 disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
        >
          Adicionar
        </button>
      </div>
      {error && (
        <p id={errorId} role="alert" className={`mt-1 ${ALERT_CLASS}`}>
          {error}
        </p>
      )}
    </fieldset>
  )
}
