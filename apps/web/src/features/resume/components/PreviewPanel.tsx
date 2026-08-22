import { useEffect, useRef, useState } from 'react'
import { useResume, useTemplate } from '../store/resumeStore'
import { useIsEditing } from '../store/editModeStore'
import { A4_WIDTH_PX, computeFitScale } from '../previewScale'
import { ContactGapsNotice } from './ContactGapsNotice'
import { PreviewToolbar } from './PreviewToolbar'
import { ResumePreview } from './ResumePreview'

export function PreviewPanel() {
  const resume = useResume()
  const template = useTemplate()
  const editable = useIsEditing()
  const containerRef = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(1)

  useEffect(() => {
    const el = containerRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? el.clientWidth
      setScale(computeFitScale(width))
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  return (
    <div className="print-preview flex h-full min-h-0 flex-col border-stone-200 bg-stone-200/80 dark:border-zinc-800 dark:bg-zinc-900/50">
      <PreviewToolbar />
      <div
        ref={containerRef}
        className="print-preview-wrap min-h-0 flex-1 overflow-auto px-4 py-6 sm:px-6"
      >
        {resume ? (
          <>
            {/* Above the page, not inside it: the notice is about the document, never part of
                it — it must never reach the print/PDF surface. */}
            <ContactGapsNotice resume={resume} />
            {/* The page renders at its true (unscaled) A4 width and is then
                visually shrunk with `transform: scale()` — but CSS transforms
                don't affect layout size, so without this outer wrapper the box
                would still reserve its full ~794px of layout width and get
                clipped on narrow viewports (B3). Giving the wrapper an explicit
                width equal to the *scaled* footprint makes layout, overflow,
                and `mx-auto` centering match what's actually painted. */}
            <div className="print-scale-wrapper mx-auto" style={{ width: `${A4_WIDTH_PX * scale}px` }}>
              <div
                className="print-scale origin-top-left rounded-sm shadow-[0_20px_50px_-12px_rgba(0,0,0,0.25)] ring-1 ring-black/5 dark:shadow-[0_24px_60px_-12px_rgba(0,0,0,0.55)] dark:ring-white/10"
                style={{ transform: `scale(${scale})`, width: `${A4_WIDTH_PX}px` }}
              >
                <ResumePreview resume={resume} template={template} editable={editable} />
              </div>
            </div>
          </>
        ) : (
          <div className="mx-auto mt-12 max-w-sm rounded-2xl border border-dashed border-stone-300 bg-white/90 px-6 py-10 text-center text-sm leading-relaxed text-stone-600 dark:border-zinc-700 dark:bg-zinc-900/80 dark:text-zinc-400">
            Generate a resume to see the A4 preview here.
          </div>
        )}
      </div>
    </div>
  )
}
