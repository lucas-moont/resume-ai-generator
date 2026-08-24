/**
 * Lightweight CSS/SVG miniature of a template, driven by its manifest tags —
 * not a screenshot of the real resume.css render. Purely decorative (used in
 * TemplatePicker's thumbnail grid); `aria-hidden` because the parent button
 * already carries the accessible name.
 */
export function TemplateThumbnail({
  tags,
  className,
}: {
  tags: readonly string[]
  className?: string
}) {
  const monochrome = tags.includes('monochrome')
  const monospace = tags.includes('monospace')
  const serif = tags.includes('serif')
  const twoColumn = tags.includes('two-column')
  const dense = tags.includes('dense')
  const skillsFirst = tags.includes('skills-first')
  const navy = tags.includes('navy')
  // `serif` implies a centered header in the templates that use one; `centered`
  // is the explicit tag for a template that centers without being serif
  // (latex-ats).
  const centered = serif || tags.includes('centered')

  const accent = monochrome
    ? '#9ca3af'
    : monospace
      ? '#16a34a'
      : serif
        ? '#92703f'
        : navy
          ? '#1f4e79'
          : dense
            ? '#0d9488'
            : '#6366f1'

  const lineIndexes = skillsFirst ? [0, 1, 2] : [0, 1, 2, 3, 4]

  return (
    <svg viewBox="0 0 64 76" aria-hidden="true" className={className}>
      <rect x="1" y="1" width="62" height="74" rx="2" fill="#fff" stroke="#e5e7eb" />
      <rect
        x={centered ? 17 : 6}
        y="7"
        width={centered ? 30 : 34}
        height="4"
        rx="1"
        fill={accent}
      />
      <rect
        x={centered ? 22 : 6}
        y="14"
        width={centered ? 20 : 24}
        height="2.5"
        rx="1"
        fill="#d4d4d8"
      />
      {twoColumn ? (
        <>
          <rect x="6" y="24" width="13" height="46" rx="1" fill={accent} opacity={monochrome ? 0 : 0.12} />
          {[0, 1, 2, 3].map((i) => (
            <rect key={i} x="8.5" y={30 + i * 10} width="8" height="2" rx="1" fill={monochrome ? '#9ca3af' : accent} />
          ))}
          {lineIndexes.map((i) => (
            <rect
              key={i}
              x="23"
              y={24 + i * 9}
              width={i === 0 && skillsFirst ? 14 : 34}
              height={i === 0 && skillsFirst ? 4 : 2.5}
              rx="1"
              fill={i === 0 && skillsFirst ? accent : '#d4d4d8'}
            />
          ))}
        </>
      ) : (
        lineIndexes.map((i) => (
          <rect
            key={i}
            x={centered ? 10 + (i % 2) * 5 : 6}
            y={24 + i * 9}
            width={centered ? 44 - (i % 2) * 10 : 52}
            height={i === 0 && skillsFirst ? 4 : 2.5}
            rx="1"
            fill={i === 0 && skillsFirst ? accent : '#d4d4d8'}
          />
        ))
      )}
    </svg>
  )
}
