import { useTranslation } from 'react-i18next'

import type { BrandColor, BrandLogo, Scheme } from '../../lib/brand'
import { pickColors } from '../../lib/brand'
import { luminance, textOn } from '../../lib/color'
import type { BrandFont } from '../../lib/brand'
import { LogoView } from './LogoView'

/** A small website with the design set applied: what a relaunch would look like before anybody writes code. */
export function WebPreview({
  colors,
  head,
  body,
  name,
  logo,
  fonts = [],
  fileUrl,
  compact = false,
  scheme = null,
  logos = [],
}: {
  colors: BrandColor[]
  head: string
  body: string
  name: string
  logo?: BrandLogo
  fonts?: BrandFont[]
  fileUrl: (id: string) => string
  compact?: boolean
  /** The set's dark mode as values: drawn dark when given. */
  scheme?: Scheme | null
  /** All logos, so the dark page can take one made for a dark ground. */
  logos?: BrandLogo[]
}) {
  const { t } = useTranslation()
  const picked = pickColors(colors, luminance)
  const accent = picked.accent
  // Light: the palette's own picks on a white header. Dark: the set's dark mode, part by part.
  const page = scheme
    ? { ground: scheme.ground, text: scheme.text, muted: scheme.muted, head: scheme.surface, card: scheme.surface, cardText: scheme.text, primary: scheme.primary, onPrimary: scheme.on_primary, foot: scheme.surface, line: `${scheme.text}22` }
    : { ground: picked.light, text: picked.dark, muted: picked.dark, head: '#FFFFFF', card: '#FFFFFF', cardText: picked.dark, primary: picked.primary, onPrimary: textOn(picked.primary), foot: picked.dark, line: `${picked.dark}22` }
  // On a dark header, a logo made for a dark ground, or one without a ground of its own.
  const shownLogo = scheme ? (logos.find((l) => l.ground !== 'transparent' && luminance(l.ground) < 0.2) ?? logos.find((l) => l.ground === 'transparent') ?? logo) : logo
  const s = compact ? 0.62 : 1
  return (
    <div className="overflow-hidden rounded-xl border border-ink-700 shadow-sm" style={{ background: page.ground, color: page.text, fontFamily: body }} aria-label={t('preview.label')} data-scheme={scheme ? 'dark' : 'light'}>
      <div className="flex items-center gap-3 border-b px-4" style={{ height: 44 * s, borderColor: page.line, background: page.head }}>
        {shownLogo ? (
          <LogoView logo={shownLogo} fonts={fonts} fileUrl={fileUrl} className={(compact ? 'h-5' : 'h-7') + ' max-w-[70%]'} />
        ) : (
          <b className="flex min-w-0 items-center gap-1.5 truncate whitespace-nowrap" style={{ fontFamily: head, fontSize: 15 * s }}>
            <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: page.primary }} />
            {name}
          </b>
        )}
        <span className={'ml-auto shrink-0 gap-3 whitespace-nowrap ' + (compact ? 'hidden 2xl:flex' : 'flex')} style={{ fontSize: 12 * s }}>
          <span>{t('preview.nav1')}</span>
          <span>{t('preview.nav2')}</span>
          <span style={{ color: page.primary, fontWeight: 600 }}>{t('preview.nav3')}</span>
        </span>
      </div>
      <div className="px-5" style={{ paddingTop: 28 * s, paddingBottom: 24 * s }}>
        <div className="mb-2 inline-block rounded-full px-2 py-0.5 font-semibold" style={{ background: accent, color: textOn(accent), fontSize: 10 * s }}>
          {t('preview.badge')}
        </div>
        <div style={{ fontFamily: head, fontSize: 30 * s, lineHeight: 1.1, fontWeight: 700 }}>{t('preview.headline', { name: name || t('preview.name') })}</div>
        <p className="mt-2 max-w-md" style={{ fontSize: 14 * s, lineHeight: 1.55, color: page.muted, opacity: scheme ? 1 : 0.85 }}>
          {t('preview.text')}
        </p>
        <div className="mt-4 flex items-center gap-3" style={{ fontSize: 13 * s }}>
          <span className="rounded-lg px-3 py-1.5 font-semibold" style={{ background: page.primary, color: page.onPrimary }}>
            {t('preview.button')}
          </span>
          <span className="font-semibold underline" style={{ color: page.primary }}>
            {t('preview.link')}
          </span>
        </div>
      </div>
      {!compact && (
        <div className="grid grid-cols-3 gap-3 px-5 pb-5">
          {[t('preview.card1'), t('preview.card2'), t('preview.card3')].map((title, i) => (
            <div key={i} className="rounded-lg p-3" style={{ background: page.card, border: `1px solid ${page.line}`, color: page.cardText }}>
              <span className="mb-2 block h-6 w-6 rounded-md" style={{ background: i === 1 ? accent : page.primary }} />
              <div className="text-sm font-semibold" style={{ fontFamily: head }}>
                {title}
              </div>
              <div className="mt-1 text-xs opacity-75">{t('preview.cardText')}</div>
            </div>
          ))}
        </div>
      )}
      <div className="px-5 py-2" style={{ background: page.foot, color: scheme ? page.muted : textOn(page.foot), fontSize: 11 * s }}>
        © {name || t('preview.name')} · {t('preview.footer')}
      </div>
    </div>
  )
}
