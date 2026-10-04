import type { BrandFont, BrandLogo } from '../../lib/brand'
import { findFont, fontStack } from '../../lib/fonts'

/** A logo as it is: the uploaded picture, or the word mark drawn from the name, its font and colours. */
export function LogoView({ logo, fonts, fileUrl, className = 'h-12' }: { logo: BrandLogo; fonts: BrandFont[]; fileUrl: (id: string) => string; className?: string }) {
  if (logo.media) return <img src={fileUrl(logo.media)} alt={logo.name} className={className + ' w-auto max-w-full object-contain'} draggable={false} />
  const text = logo.wordmark?.text || logo.name
  const family = fontStack(findFont(fonts, logo.wordmark?.font ?? ''), fileUrl)
  if (logo.compact)
    return (
      <svg viewBox="0 0 48 48" className={className} role="img" aria-label={text}>
        <rect x="4" y="4" width="40" height="40" rx="11" fill={logo.accent} />
        <text x="24" y="33" textAnchor="middle" fontSize="26" fontWeight="700" fill={logo.fg} style={{ fontFamily: family }}>
          {text.trim()[0]?.toUpperCase()}
        </text>
      </svg>
    )
  const width = Math.max(120, text.length * 15 + 30)
  return (
    <svg viewBox={`0 0 ${width} 48`} className={className + ' max-w-full'} role="img" aria-label={text}>
      <circle cx="10" cy="24" r="6" fill={logo.accent} />
      <text x="24" y="33" fontSize="27" fontWeight="700" fill={logo.fg} letterSpacing="-.5" style={{ fontFamily: family }}>
        {text}
      </text>
    </svg>
  )
}

/** The face of a client in lists: its small logo on its ground, or its first letter in its main colour. */
export function ClientMark({ name, logo, colors, fileUrl, className = 'h-10 w-10' }: { name: string; logo: BrandLogo | null; colors: string[]; fileUrl: (id: string) => string; className?: string }) {
  const ground = logo && logo.ground !== 'transparent' ? logo.ground : '#FFFFFF'
  if (logo)
    return (
      <span className={'grid shrink-0 place-items-center overflow-hidden rounded-xl border border-ink-700 p-1 ' + className} style={{ background: ground }}>
        <LogoView logo={logo} fonts={[]} fileUrl={fileUrl} className="h-full w-full" />
      </span>
    )
  return (
    <span className={'grid shrink-0 place-items-center rounded-xl text-lg font-bold ' + className} style={{ background: colors[0] ?? 'var(--color-ink-800)', color: '#fff' }}>
      {name.trim()[0]?.toUpperCase()}
    </span>
  )
}
