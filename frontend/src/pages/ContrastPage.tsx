import { ArrowLeftRight, Check, Wand2, XCircle } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ColorField } from '../components/brand/SetEditor'
import { contrast, formatRatio, hsl, parseColor, reach, simulate, VISIONS } from '../lib/color'
import { useTitle } from '../lib/title'

/** Two colours, every check at once, and the nearest colour of the same hue that passes. Colours count as they are
 * typed, in every form the server reads too (`#000`, `000`, `rgb()`, `hsl()`); one that cannot be read is named. */
export function ContrastPage() {
  const { t, i18n } = useTranslation()
  useTitle(t('nav.contrast'))
  const [fgText, setFg] = useState('#C23B2E')
  const [bgText, setBg] = useState('#F3E4C8')
  const fg = parseColor(fgText) ?? ''
  const bg = parseColor(bgText) ?? ''
  const ok = !!fg && !!bg
  const r = ok ? contrast(fg, bg) : 0
  const better = ok && r < 4.5 ? reach(fg, bg, 4.5) : null
  return (
    <main className="nc-scroll min-w-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl space-y-5 px-4 py-6 sm:px-6 sm:py-8">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t('contrast.title')}</h1>
          <p className="mt-1 max-w-2xl text-sm text-mist-500">{t('contrast.text')}</p>
        </div>
        <section className="rounded-2xl border border-ink-700 bg-ink-900 p-5">
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-sm">
              <span className="block text-xs font-medium text-mist-400">{t('contrast.text_')}</span>
              <ColorField value={fgText} onChange={setFg} label={t('contrast.text_')} lenient invalid="contrast-unread" />
            </label>
            <label className="text-sm">
              <span className="block text-xs font-medium text-mist-400">{t('contrast.ground')}</span>
              <ColorField value={bgText} onChange={setBg} label={t('contrast.ground')} lenient invalid="contrast-unread" />
            </label>
            <button type="button" className="nc-btn nc-btn-ghost" onClick={() => (setFg(bgText), setBg(fgText))}>
              <ArrowLeftRight className="h-4 w-4" /> {t('contrast.swap')}
            </button>
          </div>
          {!ok && (
            <p id="contrast-unread" role="alert" className="mt-3 text-sm text-bad-500">
              {t('contrast.unread', { value: (fg ? bgText : fgText).trim() || '…' })}
            </p>
          )}
          {ok && (
            <>
              <div className="mt-5 grid gap-3 md:grid-cols-[1fr_15rem]">
                <div className="rounded-xl p-6" style={{ background: bg, color: fg }}>
                  <div className="text-3xl font-semibold" style={{ fontFamily: "'Fraunces Variable', serif" }}>
                    {t('contrast.big')}
                  </div>
                  <p className="mt-2 text-base">{t('contrast.body')}</p>
                  <p className="mt-1 text-xs">{t('contrast.small')}</p>
                </div>
                <div className="rounded-xl border border-ink-700 p-4 text-sm">
                  <div className="font-mono text-3xl">{formatRatio(r, i18n.language)}</div>
                  {(
                    [
                      ['textAA', r >= 4.5],
                      ['textAAA', r >= 7],
                      ['largeAA', r >= 3],
                      ['largeAAA', r >= 4.5],
                      ['graphics', r >= 3],
                    ] as const
                  ).map(([key, pass]) => (
                    <div key={key} className={'mt-1 flex items-center gap-1.5 ' + (pass ? 'text-ok-500' : 'text-bad-500')}>
                      {pass ? <Check className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />} {t(`checks.pass.${key}`)}
                    </div>
                  ))}
                </div>
              </div>
              {better && (
                <div className="mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-accent-500/40 bg-accent-500/8 px-4 py-3 text-sm">
                  <Wand2 className="h-4 w-4 text-accent-400" />
                  <span className="flex-1">{t('contrast.better', { hex: better, ratio: formatRatio(contrast(better, bg), i18n.language), hue: hsl(better)[0] })}</span>
                  <span className="h-7 w-7 rounded-md border border-ink-600" style={{ background: better }} />
                  <button type="button" className="nc-btn nc-btn-ghost !px-2.5 !py-0.5 !text-xs" onClick={() => setFg(better)}>
                    {t('contrast.take')}
                  </button>
                </div>
              )}
              <h2 className="mt-6 text-sm font-semibold">{t('contrast.vision')}</h2>
              <div className="mt-2 grid gap-2 sm:grid-cols-5">
                {VISIONS.map((v) => {
                  const f = simulate(fg, v)
                  const b = simulate(bg, v)
                  return (
                    <div key={v} className="overflow-hidden rounded-xl border border-ink-700">
                      <div className="px-3 py-3 text-sm font-semibold" style={{ background: b, color: f }}>
                        {t('contrast.sample')}
                      </div>
                      <div className="px-2 py-1 text-xs text-mist-400">
                        {t(`vision.${v}`)} · {formatRatio(contrast(f, b), i18n.language)}
                      </div>
                    </div>
                  )
                })}
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  )
}
