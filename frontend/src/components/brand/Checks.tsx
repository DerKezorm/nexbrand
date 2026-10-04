import { AlertTriangle, Check, CircleCheck, Eye, Info, XCircle } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { BrandColor } from '../../lib/brand'
import type { Hint } from '../../lib/checks'
import { visionClashes } from '../../lib/checks'
import { contrast, formatRatio, grade, simulate, VISIONS, type Vision } from '../../lib/color'

const ICON = { bad: XCircle, warn: AlertTriangle, info: Info }
const TONE = { bad: 'text-bad-500', warn: 'text-warn-500', info: 'text-accent-400' }

/** The words of a hint, from its code and numbers. */
// eslint-disable-next-line react-refresh/only-export-components
export function useHintText() {
  const { t, i18n } = useTranslation()
  const number = (n: number | undefined) => (n === undefined ? '' : n.toLocaleString(i18n.language, { maximumFractionDigits: 2 }))
  return (hint: Hint) => {
    const values = {
      a: hint.colors?.[0] ?? '',
      b: hint.colors?.[1] ?? '',
      ratio: hint.ratio !== undefined ? formatRatio(hint.ratio, i18n.language) : '',
      better: hint.better ?? '',
      betterRatio: hint.better_ratio !== undefined ? formatRatio(hint.better_ratio, i18n.language) : '',
      delta: number(hint.delta_e),
      logo: hint.logo ?? '',
      size: hint.size ?? '',
      font: hint.font ?? '',
      rule: hint.rule !== undefined ? hint.rule + 1 : '',
      missing: hint.missing ?? '',
      step: hint.step ?? '',
      min: hint.min ?? '',
      need: hint.need !== undefined ? formatRatio(hint.need, i18n.language) : '',
    }
    const text = t(`checks.${hint.code}.text`, values) + (hint.better ? ' ' + t('checks.better', values) : '')
    return { title: t(`checks.${hint.code}.title`, values), text }
  }
}

export function HintList({ hints, empty = true }: { hints: Hint[]; empty?: boolean }) {
  const { t } = useTranslation()
  const words = useHintText()
  if (!hints.length)
    return empty ? (
      <p className="flex items-center gap-2 rounded-xl border border-ok-500/30 bg-ok-500/8 px-4 py-3 text-sm text-mist-200">
        <CircleCheck className="h-4 w-4 text-ok-500" /> {t('checks.none')}
      </p>
    ) : null
  return (
    <ul className="space-y-2">
      {hints.map((hint, i) => {
        const Icon = ICON[hint.level]
        const { title, text } = words(hint)
        return (
          <li key={hint.code + i} className="flex gap-3 rounded-xl border border-ink-700 bg-ink-900 px-4 py-3">
            <Icon className={'mt-0.5 h-4 w-4 shrink-0 ' + TONE[hint.level]} aria-hidden />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-mist-100">{title}</div>
              <div className="text-sm text-mist-400">{text}</div>
            </div>
            {hint.hex && (
              <div className="flex shrink-0 -space-x-1.5" aria-hidden>
                {hint.hex.map((value, j) => (
                  <span key={j} className="h-6 w-6 rounded-full border border-edge" style={{ background: value }} />
                ))}
              </div>
            )}
          </li>
        )
      })}
    </ul>
  )
}

const GRADE_LOOK = { AAA: 'bg-ok-500/20 text-ok-500', AA: 'bg-ok-500/12 text-ok-500', 'AA large': 'bg-warn-500/15 text-warn-500', fail: 'bg-bad-500/12 text-bad-500' }

/** Every colour on every other: the ratio and the grade, and a sample of the pair chosen. */
export function Matrix({ colors, headFont }: { colors: BrandColor[]; headFont?: string }) {
  const { t, i18n } = useTranslation()
  const [large, setLarge] = useState(false)
  const [names, setNames] = useState<[string, string]>([colors[colors.length - 1]?.name ?? '', colors[0]?.name ?? ''])
  if (colors.length < 2) return <p className="text-sm text-mist-500">{t('checks.matrixEmpty')}</p>
  const fg = colors.find((c) => c.name === names[0]) ?? colors[colors.length - 1]
  const bg = colors.find((c) => c.name === names[1] && c !== fg) ?? colors.find((c) => c !== fg) ?? colors[0]
  const r = contrast(fg.hex, bg.hex)
  return (
    <section className="rounded-2xl border border-ink-700 bg-ink-900 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold">{t('checks.matrixTitle')}</h3>
          <p className="text-sm text-mist-500">{t('checks.matrixText')}</p>
        </div>
        <label className="flex items-center gap-2 text-sm text-mist-400">
          <input type="checkbox" checked={large} onChange={(e) => setLarge(e.target.checked)} className="h-4 w-4 accent-accent-500" />
          {t('checks.large')}
        </label>
      </div>
      <div className="nc-scroll mt-4 overflow-x-auto">
        <table className="w-full border-separate border-spacing-1 text-xs">
          <thead>
            <tr>
              <th className="text-left font-normal text-mist-600">{t('checks.axis')}</th>
              {colors.map((c) => (
                <th key={c.name} scope="col" className="min-w-20 font-medium text-mist-300">
                  <span className="mx-auto mb-1 block h-4 w-4 rounded-full border border-edge" style={{ background: c.hex }} />
                  {c.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {colors.map((text) => (
              <tr key={text.name}>
                <th scope="row" className="pr-2 text-left font-medium whitespace-nowrap text-mist-300">
                  <span className="mr-1.5 inline-block h-3 w-3 rounded-full border border-edge align-middle" style={{ background: text.hex }} />
                  {text.name}
                </th>
                {colors.map((ground) => {
                  if (text === ground) return <td key={ground.name} className="rounded-md bg-ink-850 text-center text-mist-600">·</td>
                  const ratio = contrast(text.hex, ground.hex)
                  const g = grade(ratio, large)
                  const on = fg === text && bg === ground
                  return (
                    <td key={ground.name} className="p-0">
                      <button
                        type="button"
                        onClick={() => setNames([text.name, ground.name])}
                        aria-label={t('checks.cellLabel', { text: text.name, ground: ground.name, ratio: formatRatio(ratio, i18n.language) })}
                        className={'w-full rounded-md px-1.5 py-1.5 text-center ' + GRADE_LOOK[g] + (on ? ' ring-2 ring-accent-500' : '')}
                      >
                        <span className="block font-mono">{formatRatio(ratio, i18n.language)}</span>
                        <span className="block text-[10px] font-semibold">{t(`checks.grade.${g}`)}</span>
                      </button>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-[1fr_auto]">
        <div className="rounded-xl p-5" style={{ background: bg.hex, color: fg.hex }}>
          <div className="text-2xl font-semibold" style={{ fontFamily: headFont }}>
            {t('checks.sampleTitle')}
          </div>
          <p className="mt-1 text-[15px]">{t('checks.sampleText', { text: fg.name, ground: bg.name })}</p>
          <p className="mt-1 text-xs">{t('checks.sampleSmall')}</p>
        </div>
        <div className="flex flex-col justify-center gap-1 rounded-xl border border-ink-700 px-4 py-3 text-sm">
          <div className="font-mono text-2xl text-mist-100">{formatRatio(r, i18n.language)}</div>
          {(
            [
              ['textAA', r >= 4.5],
              ['textAAA', r >= 7],
              ['largeAA', r >= 3],
              ['graphics', r >= 3],
            ] as const
          ).map(([key, ok]) => (
            <div key={key} className={'flex items-center gap-1.5 ' + (ok ? 'text-ok-500' : 'text-bad-500')}>
              {ok ? <Check className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />} {t(`checks.pass.${key}`)}
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

/** The palette as people with a colour vision deficiency see it, and the pairs that run together for them. */
export function VisionPanel({ colors }: { colors: BrandColor[] }) {
  const { t } = useTranslation()
  const [vision, setVision] = useState<Vision>('deutan')
  const clashes = vision === 'normal' || vision === 'achromat' ? [] : visionClashes(colors, vision)
  return (
    <section className="rounded-2xl border border-ink-700 bg-ink-900 p-5">
      <h3 className="flex items-center gap-2 font-semibold">
        <Eye className="h-4 w-4 text-accent-400" /> {t('vision.title')}
      </h3>
      <div className="mt-3 flex flex-wrap gap-2" role="tablist">
        {VISIONS.map((v) => (
          <button
            key={v}
            type="button"
            role="tab"
            aria-selected={vision === v}
            onClick={() => setVision(v)}
            className={'rounded-full border px-3 py-1 text-sm ' + (vision === v ? 'border-accent-500/60 bg-accent-500/15 text-accent-400' : 'border-ink-700 text-mist-400 hover:text-mist-100')}
          >
            {t(`vision.${v}`)}
          </button>
        ))}
      </div>
      <p className="mt-2 text-xs text-mist-500">{t(`vision.${vision}Hint`)}</p>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {colors.map((c) => (
          <div key={c.name} className="overflow-hidden rounded-xl border border-ink-700">
            <div className="flex h-14">
              <span className="w-1/3" style={{ background: c.hex }} title={t('vision.meant')} />
              <span className="flex-1" style={{ background: simulate(c.hex, vision) }} />
            </div>
            <div className="truncate px-2 py-1 text-xs text-mist-300">{c.name}</div>
          </div>
        ))}
      </div>
      {clashes.length > 0 && (
        <p className="mt-3 flex items-start gap-2 text-sm text-warn-500">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {t('vision.clash', { pairs: clashes.map(([a, b]) => `${a.name} / ${b.name}`).join(', ') })}
        </p>
      )}
    </section>
  )
}
