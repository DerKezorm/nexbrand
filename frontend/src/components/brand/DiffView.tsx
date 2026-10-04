import { ArrowRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import type { VersionInfo } from '../../api/client'
import { check } from '../../lib/checks'
import { deltaE } from '../../lib/color'
import { useHintText } from './Checks'

/** What changed from one version to another: colours (with their distance), fonts, logos, and what the checks say
 * now that they did not, or no longer. */
export function DiffView({ a, b }: { a: VersionInfo; b: VersionInfo }) {
  const { t, i18n } = useTranslation()
  const words = useHintText()
  const before = new Map(a.data.colors.map((c) => [c.name.toLocaleLowerCase(), c]))
  const after = new Map(b.data.colors.map((c) => [c.name.toLocaleLowerCase(), c]))
  const changed = [...after.entries()].filter(([k, c]) => before.has(k) && before.get(k)!.hex.toUpperCase() !== c.hex.toUpperCase()).map(([k, c]) => [before.get(k)!, c] as const)
  const added = [...after.entries()].filter(([k]) => !before.has(k)).map(([, c]) => c)
  const removed = [...before.entries()].filter(([k]) => !after.has(k)).map(([, c]) => c)
  const fontsA = new Set(a.data.fonts.map((f) => f.family))
  const fontsB = new Set(b.data.fonts.map((f) => f.family))
  const logosA = new Set(a.data.logos.map((l) => `${l.name}:${l.media ?? ''}:${l.wordmark?.text ?? ''}`))
  const logosB = new Set(b.data.logos.map((l) => `${l.name}:${l.media ?? ''}:${l.wordmark?.text ?? ''}`))
  const logoChanged = logosA.size !== logosB.size || [...logosB].some((x) => !logosA.has(x))
  const ha = check(a.data).filter((h) => h.level !== 'info')
  const hb = check(b.data).filter((h) => h.level !== 'info')
  const key = (h: (typeof ha)[number]) => h.code + (h.colors ?? []).join('|') + (h.logo ?? '')
  const newHints = hb.filter((h) => !ha.some((x) => key(x) === key(h)))
  const goneHints = ha.filter((h) => !hb.some((x) => key(x) === key(h)))
  const nothing = !changed.length && !added.length && !removed.length && [...fontsB].every((f) => fontsA.has(f)) && [...fontsA].every((f) => fontsB.has(f)) && !logoChanged
  const row = 'flex flex-wrap items-center gap-2 rounded-xl border border-ink-700 bg-ink-900 px-3 py-2 text-sm'
  const chip = (text: string, tone: string) => <span className={'rounded-full border px-2 py-0.5 text-[11px] ' + tone}>{text}</span>
  const dot = (hex: string) => <span className="inline-block h-5 w-5 rounded-full border border-edge" style={{ background: hex }} />
  return (
    <div className="space-y-2">
      {nothing && <p className="text-sm text-mist-500">{t('diff.nothing')}</p>}
      {changed.map(([x, y]) => (
        <div key={y.name} className={row}>
          {chip(t('diff.changed'), 'border-accent-500/40 text-accent-400')}
          {dot(x.hex)} <span className="font-mono text-xs text-mist-500">{x.hex}</span> <ArrowRight className="h-3.5 w-3.5 text-mist-600" /> {dot(y.hex)}
          <span className="font-mono text-xs">{y.hex}</span>
          <span className="font-semibold">{y.name}</span>
          <span className="text-xs text-mist-500">ΔE {deltaE(x.hex, y.hex).toLocaleString(i18n.language, { maximumFractionDigits: 1 })}</span>
        </div>
      ))}
      {added.map((c) => (
        <div key={c.name} className={row}>
          {chip(t('diff.added'), 'border-ok-500/40 text-ok-500')} {dot(c.hex)} <span className="font-semibold">{c.name}</span> <span className="font-mono text-xs text-mist-500">{c.hex}</span>
        </div>
      ))}
      {removed.map((c) => (
        <div key={c.name} className={row}>
          {chip(t('diff.removed'), 'border-bad-500/40 text-bad-500')} {dot(c.hex)} <span className="font-semibold line-through">{c.name}</span>
        </div>
      ))}
      {[...fontsB].filter((f) => !fontsA.has(f)).map((f) => (
        <div key={f} className={row}>
          {chip(t('diff.fontAdded'), 'border-ok-500/40 text-ok-500')} {f}
        </div>
      ))}
      {[...fontsA].filter((f) => !fontsB.has(f)).map((f) => (
        <div key={f} className={row}>
          {chip(t('diff.fontRemoved'), 'border-bad-500/40 text-bad-500')} <span className="line-through">{f}</span>
        </div>
      ))}
      {logoChanged && <div className={row}>{chip(t('diff.logos'), 'border-accent-500/40 text-accent-400')}</div>}
      {(newHints.length > 0 || goneHints.length > 0) && (
        <div className="mt-3 rounded-xl border border-ink-700 bg-ink-850 p-3 text-sm">
          <div className="mb-1 font-semibold">{t('diff.checks')}</div>
          {newHints.map((h, i) => (
            <div key={'n' + i} className="text-warn-500">
              + {words(h).title}
            </div>
          ))}
          {goneHints.map((h, i) => (
            <div key={'g' + i} className="text-ok-500">
              − {words(h).title} ({t('diff.fixed')})
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
