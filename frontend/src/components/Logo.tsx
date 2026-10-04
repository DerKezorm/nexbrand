/** nexbrand mark: three swatches fanned out like a colour fan, in the Dreiklang, within the style of the nexapps
 * marks (dark tile, gradient edge). */
export function Logo({ className = 'h-8 w-8', withWordmark = false }: { className?: string; withWordmark?: boolean }) {
  // userSpaceOnUse, so the gradient runs across the whole mark instead of restarting for each stroke.
  const mark = (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="nexbrand-mark" gradientUnits="userSpaceOnUse" x1="8" y1="8" x2="56" y2="56">
          <stop offset="0" stopColor="#9dbbff" />
          <stop offset=".5" stopColor="#2f7bff" />
          <stop offset="1" stopColor="#e255f5" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="16" fill="#0d0d18" />
      <rect x="2" y="2" width="60" height="60" rx="16" fill="none" stroke="url(#nexbrand-mark)" strokeWidth="2.5" strokeOpacity=".55" />
      <rect x="25" y="21" width="12" height="29" rx="3.5" fill="none" stroke="#e255f5" strokeWidth="3.6" transform="rotate(-34 31 49)" />
      <rect x="25" y="21" width="12" height="29" rx="3.5" fill="none" stroke="#ffe14a" strokeWidth="3.6" transform="rotate(-10 31 49)" />
      <g transform="rotate(14 31 49)">
        <rect x="25" y="21" width="12" height="29" rx="3.5" fill="url(#nexbrand-mark)" stroke="url(#nexbrand-mark)" strokeWidth="3.6" />
        <rect x="27.5" y="23.5" width="7" height="7" rx="1.5" fill="#000" opacity=".28" />
      </g>
      <circle cx="31" cy="45" r="2.6" fill="#0d0d18" />
    </svg>
  )
  if (!withWordmark) return mark
  return (
    <span className="flex items-center gap-2.5">
      {mark}
      <span className="hidden text-lg font-bold tracking-tight sm:inline">
        NEX<span className="text-accent-500">BRAND</span>
      </span>
    </span>
  )
}
