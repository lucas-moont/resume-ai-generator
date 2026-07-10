import { useEffect, useRef, useState } from 'react'
import { useResume, useTemplate } from '../store/resumeStore'
import { PreviewToolbar } from './PreviewToolbar'
import { ResumePreview } from './ResumePreview'

const A4_WIDTH_MM = 210
const CSS_PX_PER_MM = 3.7795275591

export function PreviewPanel() {
  const resume = useResume()
  const template = useTemplate()
  const containerRef = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(1)

  useEffect(() => {
    const el = containerRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const pageWidthPx = A4_WIDTH_MM * CSS_PX_PER_MM
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? el.clientWidth
      setScale(width > 0 ? Math.min(1, width / pageWidthPx) : 1)
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
          <div
            className="print-scale mx-auto origin-top rounded-sm shadow-[0_20px_50px_-12px_rgba(0,0,0,0.25)] ring-1 ring-black/5 dark:shadow-[0_24px_60px_-12px_rgba(0,0,0,0.55)] dark:ring-white/10"
            style={{ transform: `scale(${scale})`, width: `${A4_WIDTH_MM}mm` }}
          >
            <ResumePreview resume={resume} template={template} />
          </div>
        ) : (
          <div className="mx-auto mt-12 max-w-sm rounded-2xl border border-dashed border-stone-300 bg-white/90 px-6 py-10 text-center text-sm leading-relaxed text-stone-600 dark:border-zinc-700 dark:bg-zinc-900/80 dark:text-zinc-400">
            Generate a resume to see the A4 preview here.
          </div>
        )}
      </div>
    </div>
  )
}
