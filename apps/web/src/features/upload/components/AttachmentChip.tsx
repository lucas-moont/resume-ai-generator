import { fileTypeLabel, formatFileSize } from '../fileMeta'
import { Tooltip } from '../../../ui/Tooltip'
import type { UploadAttachment } from '../useFileUpload'

export function AttachmentChip({
  attachment,
  onRemove,
  onRetry,
}: {
  attachment: UploadAttachment
  onRemove: () => void
  onRetry: () => void
}) {
  const { file } = attachment
  const isFailed = attachment.status === 'failed'

  return (
    <div
      className={`flex max-w-full items-center gap-2 rounded-xl border px-2.5 py-1.5 text-xs shadow-sm ${
        isFailed
          ? 'border-red-200 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300'
          : 'border-stone-200 bg-white text-stone-700 dark:border-zinc-700 dark:bg-zinc-900/80 dark:text-zinc-200'
      }`}
    >
      <span className="shrink-0 rounded-md bg-stone-100 px-1.5 py-0.5 font-medium text-stone-600 dark:bg-zinc-800 dark:text-zinc-300">
        {fileTypeLabel(file.name)}
      </span>
      <span className="max-w-[10rem] truncate" title={file.name}>
        {file.name}
      </span>
      <span className="shrink-0 text-stone-500 dark:text-zinc-500">{formatFileSize(file.size)}</span>

      {attachment.status === 'uploading' && (
        <span className="shrink-0 tabular-nums text-stone-500 dark:text-zinc-500" aria-live="polite">
          {attachment.progress}%
        </span>
      )}

      {isFailed && (
        <>
          <span className="truncate">{attachment.error ?? 'Upload failed'}</span>
          <button
            type="button"
            onClick={onRetry}
            aria-label={`Retry uploading ${file.name}`}
            className="shrink-0 rounded-md border border-red-300 bg-white px-1.5 py-0.5 font-medium text-red-800 hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400 dark:border-red-800 dark:bg-zinc-900 dark:text-red-300 dark:hover:bg-red-950/60"
          >
            Retry
          </button>
        </>
      )}

      <Tooltip label="Remove" placement="top">
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove ${file.name}`}
          className="ml-0.5 shrink-0 rounded-full p-0.5 text-stone-400 hover:bg-stone-100 hover:text-stone-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:text-zinc-500 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
        >
          <svg aria-hidden="true" viewBox="0 0 20 20" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M5 5l10 10M15 5 5 15" strokeLinecap="round" />
          </svg>
        </button>
      </Tooltip>
    </div>
  )
}
