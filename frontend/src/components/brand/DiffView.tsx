import { ArrowRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import type { VersionInfo } from '../../api/client'
import type { Rule } from '../../lib/brand'
import { check } from '../../lib/checks'
import { deltaE, isHex } from '../../lib/color'
import { diffSets, type Change, type FieldChange } from '../../lib/diff'
import { useHintText } from './Checks'
import { useRuleWords } from './rules'

/** What changed from one version to another, in every part (`lib/diff.ts`, the same as the server's
 * `compare_versions`): colours (with their distance), fonts, logos, the type scale, rules, examples and the dark mode;
 * then what the checks say now that they did not, or no longer. */
export function DiffView({ a, b }: { a: VersionInfo; b: VersionInfo }) {
  const { t, i18n } = useTranslation()
  const words = useHintText()
  const ruleWords = useRuleWords()
  const changes = diffSets(a.data, b.data)
  const ha = check(a.data).filter((h) => h.level !== 'info')
  const hb = check(b.data).filter((h) => h.level !== 'info')
  const key = (h: (typeof ha)[number]) => h.code + (h.colors ?? []).join('|') + (h.logo ?? '')
  const newHints = hb.filter((h) => !ha.some((x) => key(x) === key(h)))
  const goneHints = ha.filter((h) => !hb.some((x) => key(x) === key(h)))
  const row = 'flex flex-wrap items-center gap-2 rounded-xl border border-ink-700 bg-ink-900 px-3 py-2 text-sm'
  const chip = (text: string, tone: string) => <span className={'rounded-full border px-2 py-0.5 text-[11px] ' + tone}>{text}</span>
  const dot = (hex: string) => <span className="inline-block h-4 w-4 shrink-0 rounded-full border border-edge align-[-3px]" style={{ background: hex }} />
  const TONE = { added: 'border-ok-500/40 text-ok-500', removed: 'border-bad-500/40 text-bad-500', changed: 'border-accent-500/40 text-accent-400' }

  const value = (change: Change, field: string, v: unknown) => {
    if (v === null || v === undefined) return <span className="text-mist-500">{t('diff.empty')}</span>
    if (field === 'files') return t('diff.files', { count: (v as unknown[]).length })
    if (field === 'media') return t('diff.file')
    if (field === 'wordmark') return (v as { text?: string }).text ?? ''
    if (field === 'role' && change.part === 'colors') return t(`roles.color.${String(v)}`)
    if (field === 'license') return t(`set.license.${String(v)}`)
    if (field === 'use') return t(`set.use.${String(v)}`)
    if (typeof v === 'boolean') return v ? t('diff.yes') : t('diff.no')
    if (typeof v === 'number') return v.toLocaleString(i18n.language) + (field === 'size' ? ' px' : '')
    if (Array.isArray(v)) return v.join(', ')
    if (typeof v === 'string' && isHex(v))
      return (
        <span className="inline-flex items-center gap-1">
          {dot(v)} <span className="font-mono text-xs">{v}</span>
        </span>
      )
    return String(v)
  }
  const fieldName = (change: Change, field: string) => (change.part === 'dark' ? t(`dark.part.${field}`) : t(`diff.field.${field}`))
  const fieldRow = (change: Change, f: FieldChange) => (
    <span key={f.field} className="inline-flex flex-wrap items-center gap-1 text-xs text-mist-300">
      <span className="text-mist-500">{fieldName(change, f.field)}</span> {value(change, f.field, f.from)} <ArrowRight className="h-3 w-3 text-mist-600" aria-label={t('diff.becomes')} /> {value(change, f.field, f.to)}
      {change.part === 'colors' && f.field === 'hex' && typeof f.from === 'string' && typeof f.to === 'string' && (
        <span className="text-mist-500">ΔE {deltaE(f.from, f.to).toLocaleString(i18n.language, { maximumFractionDigits: 1 })}</span>
      )}
    </span>
  )
  const what = (change: Change) =>
    change.part === 'rules' ? ruleWords.sentence(change.rule as Rule, [...b.data.logos, ...a.data.logos]) : change.part === 'dark' ? '' : change.name

  return (
    <div className="space-y-2" data-testid="diff">
      {!changes.length && <p className="text-sm text-mist-500">{t('diff.nothing')}</p>}
      {changes.map((change, i) => (
        <div key={i} className={row}>
          {chip(t(`diff.${change.change}`), TONE[change.change])}
          <span className="text-xs text-mist-500">{t(`inherit.part.${change.part}`)}</span>
          {change.part === 'colors' && change.change !== 'changed' && dot(((change.change === 'added' ? b : a).data.colors.find((c) => c.name === change.name)?.hex ?? '#000000'))}
          {what(change) && <span className={'font-semibold ' + (change.change === 'removed' ? 'line-through' : '')}>{what(change)}</span>}
          {change.fields.length > 0 && <span className="flex w-full flex-wrap gap-x-4 gap-y-1">{change.fields.map((f) => fieldRow(change, f))}</span>}
        </div>
      ))}
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
