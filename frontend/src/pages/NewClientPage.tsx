/** A new client: who it is, then a start (a few words, a picture, one colour, or empty), colours, fonts, sizes and logo
 * in the workbench, and the draft, before the client if wanted. Also the way to record a CI that exists already. */
import { ArrowLeft, ArrowRight, Check, Eraser, ImagePlus, Loader2, Palette, Pipette, Send, Sparkles, Table2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { aiApi, ApiError, clientsApi, mediaApi, mediaUrl, reviewsApi, type ClientWhole, type MediaInfo } from '../api/client'
import { HintList, Matrix } from '../components/brand/Checks'
import { LogoView } from '../components/brand/LogoView'
import { SharesOff } from '../components/brand/SharesPanel'
import { ColorsEditor, useNames } from '../components/brand/SetEditor'
import { WebPreview } from '../components/brand/WebPreview'
import { Dialog } from '../components/Dialog'
import { emptySet, type BrandColor, type BrandLogo, type BrandSet } from '../lib/brand'
import { check } from '../lib/checks'
import { isHex, textOn } from '../lib/color'
import { errorText } from '../lib/errors'
import { useTitle } from '../lib/title'
import { CATALOG, PAIRINGS, catalogEntry, catalogFont, fontStack } from '../lib/fonts'
import { colorsOfImage, directions, familyOf, fromAi, oneColor, RATIOS, rolesFor, startRules, typeScale, wordmarks, type Direction } from '../lib/generate'
import { useAuth } from '../state/auth'
import { useBrands } from '../state/brands'
import { Feedback } from './settings/ui'

const STEPS = ['who', 'start', 'colors', 'fonts', 'sizes', 'finish'] as const
type Step = (typeof STEPS)[number]

type Bench = { colors: BrandColor[]; head: string; body: string; base: number; ratio: number; logo?: MediaInfo }

export function NewClientPage() {
  const { t } = useTranslation()
  useTitle(t('wizard.title'))
  const navigate = useNavigate()
  const { me } = useAuth()
  const brands = useBrands()
  const [params] = useSearchParams()
  const names = useNames()
  const [step, setStep] = useState<Step>('who')
  // A client without a design set yet (one nexsuite brought, or one made earlier): the wizard makes its first version.
  const presetId = params.get('client')
  const [existing, setExisting] = useState<ClientWhole | null>(null)
  // The client this wizard works for, once there is one: made when a logo is uploaded or at the end.
  const [made, setMade] = useState<{ id: string; space_id: number } | null>(null)
  const [name, setName] = useState('')
  const [sector, setSector] = useState('')
  const fixed = !!existing
  const [project, setProject] = useState('')
  const [brief, setBrief] = useState('')
  const [dirs, setDirs] = useState<Direction[] | null>(null)
  const [along, setAlong] = useState<Record<string, boolean>>({})
  const [bench, setBench] = useState<Bench>({ colors: [], head: 'fraunces', body: 'inter', base: 17, ratio: 1.25 })
  const [matrix, setMatrix] = useState(false)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const set = (patch: Partial<Bench>) => setBench((b) => ({ ...b, ...patch }))
  useEffect(() => {
    if (!presetId) return
    clientsApi.read(presetId).then((whole) => {
      setExisting(whole)
      setMade({ id: whole.id, space_id: whole.space_id })
      setName(whole.name)
      setSector(whole.sector)
    }, () => setProblem('not_found'))
  }, [presetId])
  const index = STEPS.indexOf(step)
  const shownName = name.trim() || t('wizard.yourName')

  const setOf = (colors: BrandColor[], head: string, body: string): BrandSet => {
    const fonts = head === body ? [catalogEntry(head, t('gen.roleBoth'))] : [catalogEntry(head, t('gen.roleHead')), catalogEntry(body, t('gen.roleBody'))]
    const valid = colors.filter((c) => isHex(c.hex))
    const marks = wordmarks(name.trim() || '?', valid, familyOf(head), { positive: t('gen.wordPositive'), negative: t('gen.wordNegative'), monogram: t('gen.monogram') })
    const logos: BrandLogo[] = bench.logo ? [{ id: 'logo', name: t('gen.logo'), media: bench.logo.id, fg: '#000000', accent: '#000000', ground: '#FFFFFF', files: [] }, ...marks.map((m) => ({ ...m, name: `${m.name} (${t('gen.standIn')})` }))] : marks
    const scaleNames = { h1: t('gen.h1'), h2: t('gen.h2'), h3: t('gen.h3'), lead: t('gen.lead'), body: t('gen.body'), small: t('gen.small') }
    return {
      ...emptySet(),
      colors: valid,
      fonts,
      logos,
      scale: typeScale(bench.base, bench.ratio, familyOf(head), familyOf(body), scaleNames),
      rules: startRules(valid, { clear: t('gen.clear'), distort: t('gen.distort') }),
    }
  }

  const current = useMemo(() => setOf(bench.colors, bench.head, bench.body), [bench, name]) // eslint-disable-line react-hooks/exhaustive-deps
  // Before the step with the logos, no hint about a logo: nobody has seen one yet (F24).
  const logosShown = STEPS.indexOf(step) >= STEPS.indexOf('sizes')
  const hints = useMemo(() => (current.colors.length ? check(current).filter((h) => h.level !== 'info' && (logosShown || !h.logo)) : []), [current, logosShown])
  const allowed = presetId ? !!existing && (existing.role === 'write' || existing.role === 'manage') : !!me?.may_create_clients
  const canNext = step === 'who' ? !!name.trim() && allowed : step === 'start' ? true : step === 'colors' ? current.colors.length > 0 : true
  // Why "Next" waits, said beside it instead of a grey button without a word (F25).
  const waitsFor = step === 'who' && !name.trim() ? t('wizard.needName') : step === 'colors' && !current.colors.length ? t('wizard.needColor') : null
  // Whoever makes a client manages it; for one that exists, its right counts: from write up (A2).
  const reviewRight = existing ? existing.role === 'write' || existing.role === 'manage' : true
  const reviewPossible = reviewRight && me?.shares_allowed !== false

  /** The client to put the design set and its files into: the one given, or a new one, made once. */
  const ensure = async (): Promise<{ id: string; space_id: number }> => {
    if (made) return made
    const fresh = await clientsApi.create({ name: name.trim(), sector: sector.trim(), label: '' })
    const kept = { id: fresh.id, space_id: fresh.space_id }
    setMade(kept)
    return kept
  }

  const finish = async (review: boolean) => {
    setBusy(true)
    setProblem(null)
    try {
      const target = await ensure()
      // Made earlier for a logo: the name and sector typed since count.
      if (!existing && made) await clientsApi.change(target.id, { name: name.trim(), sector: sector.trim() })
      const draft = await clientsApi.newVersion(target.id, { label: '1.0', data: current })
      if (project.trim()) await clientsApi.newProject(target.id, { name: project.trim(), version_id: draft.id })
      if (review && reviewPossible) {
        const variants = [{ id: 'a', label: t('wizard.worked'), why: t('wizard.workedWhy'), data: current }]
        for (const d of dirs ?? []) if (along[d.id]) variants.push({ id: String.fromCharCode(97 + variants.length), label: d.label || t(`wizard.dir.${d.id}.label`), why: dirWhy(d), data: setOf(d.colors, d.head, d.body) })
        await reviewsApi.create(target.id, { version_id: draft.id, variants, label: '1.0', sender: me?.display_name || me?.name || '', days: 30 })
      }
      await brands.refresh()
      navigate(`/c/${target.id}?v=${draft.id}${review && reviewPossible ? '&tab=reviews' : ''}`)
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
    } finally {
      setBusy(false)
    }
  }

  // From the first step on only with a name no other client has (F15): said there, not at the very end.
  const [checking, setChecking] = useState(false)
  const nextBusy = useRef(false)
  const next = async () => {
    if (nextBusy.current) return
    nextBusy.current = true
    try {
      if (step === 'who' && !existing) {
        setProblem(null)
        setChecking(true)
        const found = await clientsApi.nameCheck(name.trim(), made?.id).catch(() => ({ free: true, code: null }))
        if (!found.free) return setProblem(found.code ?? 'client_name_taken')
      }
      setStep(STEPS[index + 1])
    } finally {
      setChecking(false)
      nextBusy.current = false
    }
  }

  const moodWord = (m: string) => t(`wizard.mood.${m}`)
  const dirWhy = (d: Direction) => d.why || t(`wizard.dir.${d.id}.why`, { mood: moodWord(d.mood), second: moodWord(d.second) })
  const fileUrl = (id: string) => mediaUrl(id)

  if (!presetId && me && !me.may_create_clients) {
    // Nothing can be made here, so no form to fill in for nothing (B19). Connected, the clients from nexsuite that
    // have no CI yet are offered instead; each opens the workbench for its first version.
    const open = me.suite === 'connected' ? brands.clients.filter((c) => !c.current && c.drafts === 0 && (c.role === 'write' || c.role === 'manage')) : []
    return (
      <main className="nc-scroll min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-5 px-4 py-6 sm:px-6 sm:py-8">
          <h1 className="text-2xl font-bold tracking-tight">{t('wizard.title')}</h1>
          <p className="rounded-xl border border-ink-700 bg-ink-900 px-4 py-3 text-sm text-mist-300" data-testid="wizard-not-here">
            {me.suite === 'connected' ? t('wizard.fromSuite') : t('wizard.notAllowed')}
          </p>
          {me.suite === 'connected' && (
            <Panel title={t('wizard.pickTitle')} text={open.length ? t('wizard.pickText') : undefined}>
              {open.length ? (
                <ul className="divide-y divide-ink-700 rounded-xl border border-ink-700" data-testid="wizard-pick">
                  {open.map((c) => (
                    <li key={c.id}>
                      <Link to={`/new?client=${c.id}`} className="flex items-center gap-3 px-4 py-2.5 text-sm hover:bg-ink-850">
                        <span className="h-3 w-3 shrink-0 rounded-full" style={{ background: c.color }} aria-hidden />
                        <span className="min-w-0 flex-1 truncate font-medium text-mist-100">{c.name}</span>
                        <span className="truncate text-xs text-mist-500">{c.sector}</span>
                        <ArrowRight className="h-4 w-4 shrink-0 text-mist-500" aria-hidden />
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-mist-400">{t('wizard.pickNone')}</p>
              )}
            </Panel>
          )}
          <Link to="/" className="nc-btn nc-btn-ghost">
            <ArrowLeft className="h-4 w-4" /> {t('wizard.toClients')}
          </Link>
        </div>
      </main>
    )
  }

  return (
    <main className="nc-scroll min-w-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-5 px-4 py-6 sm:px-6 sm:py-8">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t('wizard.title')}</h1>
          <p className="mt-1 max-w-2xl text-sm text-mist-500">{t('wizard.text')}</p>
        </div>
        <ol className="flex flex-wrap gap-1.5" aria-label={t('wizard.steps')}>
          {STEPS.map((s, i) => (
            <li key={s}>
              <button
                type="button"
                disabled={i > index && !canNext}
                onClick={() => (i <= index || canNext) && setStep(s)}
                aria-current={s === step ? 'step' : undefined}
                className={'flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm ' + (s === step ? 'border-accent-500/60 bg-accent-500/15 text-accent-400' : i < index ? 'border-ink-700 text-mist-300' : 'border-ink-700 text-mist-600')}
              >
                <span className={'grid h-5 w-5 place-items-center rounded-full text-[11px] font-bold ' + (i < index ? 'bg-ok-500/20 text-ok-500' : 'bg-ink-800')}>{i < index ? <Check className="h-3 w-3" /> : i + 1}</span>
                {t(`wizard.step.${s}`)}
              </button>
            </li>
          ))}
        </ol>

        {existing && existing.versions.length > 0 && <p className="rounded-xl border border-warn-500/40 bg-warn-500/8 px-4 py-3 text-sm">{t('wizard.hasCi')}</p>}

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="min-w-0 space-y-4">
            {step === 'who' && (
              <Panel title={t('wizard.whoTitle')}>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Labeled label={t('client.name')}>
                    <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('wizard.nameHint')} className="nc-field mt-1" autoFocus={!fixed} readOnly={fixed} />
                  </Labeled>
                  <Labeled label={t('client.sector')}>
                    <input value={sector} onChange={(e) => setSector(e.target.value)} placeholder={t('wizard.sectorHint')} className="nc-field mt-1" readOnly={fixed} />
                  </Labeled>
                  <Labeled label={t('wizard.project')}>
                    <input value={project} onChange={(e) => setProject(e.target.value)} placeholder={t('wizard.projectHint')} className="nc-field mt-1" />
                  </Labeled>
                </div>
                {problem && (
                  <p role="alert" className="text-sm text-bad-500" data-testid="name-problem">
                    {errorText(problem)}
                  </p>
                )}
                <Labeled label={t('wizard.brief')}>
                  <textarea value={brief} onChange={(e) => setBrief(e.target.value)} rows={3} placeholder={t('wizard.briefHint')} className="nc-field mt-1" />
                </Labeled>
                <div className="flex flex-wrap gap-1.5">
                  {(['ex1', 'ex2', 'ex3', 'ex4'] as const).map((k) => (
                    <button key={k} type="button" onClick={() => setBrief(t(`wizard.${k}`))} className="rounded-full border border-ink-700 px-2.5 py-0.5 text-xs text-mist-400 hover:text-mist-100">
                      {t(`wizard.${k}`)}
                    </button>
                  ))}
                </div>
              </Panel>
            )}

            {step === 'start' && (
              <StartStep
                brief={brief}
                name={name}
                dirs={dirs}
                setDirs={setDirs}
                names={names}
                dirWhy={dirWhy}
                onTake={(d) => (set({ colors: d.colors, head: d.head, body: d.body }), setStep('colors'))}
                onColors={(colors) => (set({ colors }), setStep('colors'))}
                onEmpty={() => (set({ colors: [] }), setStep('colors'))}
              />
            )}

            {step === 'colors' && (
              <Panel title={t('wizard.colorsTitle')} text={t('wizard.colorsText')}>
                <ColorsEditor colors={bench.colors} onChange={(colors) => set({ colors })} />
              </Panel>
            )}

            {step === 'fonts' && (
              <Panel title={t('wizard.fontsTitle')} text={t('wizard.fontsText')}>
                <div className="grid gap-3 sm:grid-cols-2">
                  {PAIRINGS.map((p) => {
                    const on = p.head === bench.head && p.body === bench.body
                    return (
                      <button key={p.head + p.body} type="button" aria-pressed={on} onClick={() => set({ head: p.head, body: p.body })} className={'rounded-xl border p-4 text-left ' + (on ? 'border-accent-500 bg-accent-500/8' : 'border-ink-700 hover:bg-ink-850')}>
                        <div className="text-2xl leading-tight font-bold" style={{ fontFamily: catalogFont(p.head)?.stack }}>
                          {shownName}
                        </div>
                        <p className="mt-1 text-sm text-mist-300" style={{ fontFamily: catalogFont(p.body)?.stack }}>
                          {t('wizard.bodySample', { font: familyOf(p.body) })}
                        </p>
                        <div className="mt-2 flex flex-wrap gap-1">
                          {p.moods.map((m) => (
                            <span key={m} className="rounded-full border border-ink-700 px-2 py-0.5 text-[11px] text-mist-500">
                              {moodWord(m)}
                            </span>
                          ))}
                        </div>
                        <p className="mt-2 text-xs text-mist-500">
                          {familyOf(p.head)} + {familyOf(p.body)}. {t(`fonts.pairs.${p.head}-${p.body}`)}
                        </p>
                      </button>
                    )
                  })}
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  {(['head', 'body'] as const).map((k) => (
                    <Labeled key={k} label={t(k === 'head' ? 'wizard.headFree' : 'wizard.bodyFree')}>
                      <select value={bench[k]} onChange={(e) => set({ [k]: e.target.value })} className="nc-field mt-1">
                        {CATALOG.map((f) => (
                          <option key={f.id} value={f.id}>
                            {f.family} · {t(`fonts.kind.${f.kind}`)}
                          </option>
                        ))}
                      </select>
                    </Labeled>
                  ))}
                </div>
                <p className="text-xs text-mist-500">{t('wizard.fontsLater')}</p>
              </Panel>
            )}

            {step === 'sizes' && (
              <>
                <Panel title={t('wizard.sizesTitle')} text={t('wizard.sizesText')}>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Labeled label={t('editor.base', { size: bench.base })}>
                      <input type="range" min={14} max={21} value={bench.base} onChange={(e) => set({ base: Number(e.target.value) })} className="mt-2 w-full accent-accent-500" />
                      {bench.base < 16 && <span className="text-xs text-warn-500">{t('checks.body_small.text', { size: bench.base })}</span>}
                    </Labeled>
                    <Labeled label={t('editor.ratio')}>
                      <select value={bench.ratio} onChange={(e) => set({ ratio: Number(e.target.value) })} className="nc-field mt-1">
                        {RATIOS.map((r) => (
                          <option key={r} value={r}>
                            {t(`editor.ratios.${String(r).replace('.', '_')}`)}
                          </option>
                        ))}
                      </select>
                    </Labeled>
                  </div>
                  <div className="divide-y divide-ink-700">
                    {current.scale.map((s) => (
                      <div key={s.name} className="flex items-baseline gap-4 py-2">
                        <span className="w-28 shrink-0 font-mono text-xs text-mist-500">
                          {s.size} px
                          <br />
                          {s.name}
                        </span>
                        <span className="min-w-0 truncate" style={{ fontFamily: CATALOG.find((f) => f.family === s.font)?.stack, fontSize: Math.min(s.size, 56), fontWeight: s.weight, lineHeight: s.line_height }}>
                          {shownName}
                        </span>
                      </div>
                    ))}
                  </div>
                </Panel>
                <Panel title={t('wizard.logoTitle')} text={t('wizard.logoText')}>
                  <LogoUpload ensure={async () => (await ensure()).space_id} logo={bench.logo} onChange={(logo) => set({ logo })} />
                  <div className="grid gap-3 sm:grid-cols-3">
                    {current.logos.map((l) => (
                      <div key={l.id} className="overflow-hidden rounded-xl border border-ink-700">
                        <div className={'grid h-24 place-items-center px-3 ' + (l.ground === 'transparent' ? 'nb-checker' : '')} style={l.ground !== 'transparent' ? { background: l.ground } : undefined}>
                          <LogoView logo={l} fonts={current.fonts} fileUrl={fileUrl} className={l.compact ? 'h-12' : 'h-9'} />
                        </div>
                        <div className="px-3 py-1.5 text-xs text-mist-400">{l.name}</div>
                      </div>
                    ))}
                  </div>
                </Panel>
              </>
            )}

            {step === 'finish' && (
              <Panel title={t('wizard.finishTitle')} text={t('wizard.finishText')}>
                <div className="flex items-start gap-3 rounded-xl border border-accent-500/50 bg-accent-500/8 p-3 text-sm">
                  <Check className="mt-0.5 h-4 w-4 text-accent-400" />
                  <span className="flex-1">
                    <b>{t('wizard.worked')}</b>
                    <span className="block text-xs text-mist-500">{t('wizard.workedWhy')}</span>
                  </span>
                  <Swatches colors={current.colors} />
                </div>
                {dirs?.map((d) => (
                  <label key={d.id} className="flex items-start gap-3 rounded-xl border border-ink-700 p-3 text-sm">
                    <input type="checkbox" checked={!!along[d.id]} onChange={(e) => setAlong({ ...along, [d.id]: e.target.checked })} className="mt-1 accent-accent-500" />
                    <span className="flex-1">
                      <b>{d.label || t(`wizard.dir.${d.id}.label`)}</b>
                      <span className="block text-xs text-mist-500">{t('wizard.alongText')}</span>
                    </span>
                    <Swatches colors={d.colors} />
                  </label>
                ))}
                {hints.length > 0 && <p className="rounded-xl border border-warn-500/40 bg-warn-500/8 px-3 py-2 text-sm text-mist-200">{t('wizard.stillHints', { count: hints.length })}</p>}
                {me?.shares_allowed === false ? <SharesOff /> : !reviewRight && <p className="text-xs text-mist-500">{t('wizard.noReview')}</p>}
                <Feedback problem={problem} />
                <div className="flex flex-wrap justify-end gap-2">
                  <button type="button" className="nc-btn nc-btn-ghost" disabled={busy} onClick={() => void finish(false)}>
                    {t('wizard.onlyDraft')}
                  </button>
                  {reviewPossible && (
                    <button type="button" className="nc-btn nc-btn-accent" disabled={busy} onClick={() => void finish(true)}>
                      <Send className="h-4 w-4" /> {t('wizard.withReview')}
                    </button>
                  )}
                </div>
              </Panel>
            )}

            <div className="flex flex-wrap items-center justify-between gap-3">
              <button type="button" className="nc-btn nc-btn-ghost" onClick={() => setStep(STEPS[Math.max(0, index - 1)])} disabled={index === 0}>
                <ArrowLeft className="h-4 w-4" /> {t('wizard.back')}
              </button>
              {/* At the start the way on is the button of the chosen start: a second "Next" beside it went on without
                  taking anything. Only with colours from before, it goes on with those, and says so (F25). */}
              {index < STEPS.length - 1 && (step !== 'start' || current.colors.length > 0) && (
                <span className="ml-auto flex flex-wrap items-center justify-end gap-3">
                  {waitsFor && (
                    <span id="wizard-waits" className="text-sm text-mist-500" data-testid="wizard-waits">
                      {waitsFor}
                    </span>
                  )}
                  <button type="button" className="nc-btn nc-btn-accent" onClick={() => void next()} disabled={!canNext || checking} aria-describedby={waitsFor ? 'wizard-waits' : undefined}>
                    {step === 'start' ? t('wizard.keepColors') : t('wizard.next')} <ArrowRight className="h-4 w-4" />
                  </button>
                </span>
              )}
            </div>
          </div>

          <aside className="space-y-3 lg:sticky lg:top-4 lg:self-start" aria-label={t('editor.live')}>
            {current.colors.length > 0 ? (
              <>
                <WebPreview colors={current.colors} head={fontStack(current.fonts[0], fileUrl)} body={fontStack(current.fonts[1] ?? current.fonts[0], fileUrl)} name={shownName} logo={current.logos.find((l) => !l.compact)} fonts={current.fonts} fileUrl={fileUrl} compact />
                <section className="rounded-2xl border border-ink-700 bg-ink-900 p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <h3 className="text-sm font-semibold">{t('editor.live')}</h3>
                    <span className={'rounded-full border px-2 py-0.5 text-[11px] ' + (hints.length ? 'border-warn-500/40 text-warn-500' : 'border-ok-500/40 text-ok-500')}>{hints.length ? t('editor.hints', { count: hints.length }) : t('editor.allGood')}</span>
                  </div>
                  <div className="nc-scroll max-h-72 overflow-y-auto">
                    <HintList hints={hints} />
                  </div>
                  <button type="button" className="nc-btn nc-btn-ghost mt-2 !px-2.5 !py-0.5 !text-xs" onClick={() => setMatrix(true)}>
                    <Table2 className="h-3.5 w-3.5" /> {t('wizard.allPairs')}
                  </button>
                </section>
              </>
            ) : (
              <section className="rounded-2xl border border-dashed border-ink-700 p-5 text-sm text-mist-500">
                <Palette className="mb-2 h-5 w-5 text-mist-600" />
                {t('wizard.asideEmpty')}
              </section>
            )}
          </aside>
        </div>
      </div>
      {matrix && (
        <Dialog title={t('checks.matrixTitle')} onClose={() => setMatrix(false)} wide>
          <Matrix colors={current.colors} headFont={fontStack(current.fonts[0], fileUrl)} />
        </Dialog>
      )}
    </main>
  )
}

function Panel({ title, text, children }: { title: string; text?: string; children: ReactNode }) {
  return (
    <section className="space-y-4 rounded-2xl border border-ink-700 bg-ink-900 p-5">
      <div>
        <h2 className="font-semibold">{title}</h2>
        {text && <p className="text-sm text-mist-500">{text}</p>}
      </div>
      {children}
    </section>
  )
}

function Labeled({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="text-xs font-medium text-mist-400">{label}</span>
      {children}
    </label>
  )
}

const Swatches = ({ colors }: { colors: BrandColor[] }) => (
  <span className="flex shrink-0 overflow-hidden rounded-md border border-ink-700">
    {colors.map((c, i) => (
      <span key={c.name + i} className="h-6 w-5" style={{ background: c.hex }} />
    ))}
  </span>
)

function StartStep({
  brief,
  name,
  dirs,
  setDirs,
  names,
  dirWhy,
  onTake,
  onColors,
  onEmpty,
}: {
  brief: string
  name: string
  dirs: Direction[] | null
  setDirs: (d: Direction[]) => void
  names: ReturnType<typeof useNames>
  dirWhy: (d: Direction) => string
  onTake: (d: Direction) => void
  onColors: (c: BrandColor[]) => void
  onEmpty: () => void
}) {
  const { t, i18n } = useTranslation()
  const [mode, setMode] = useState<'words' | 'picture' | 'color' | 'empty'>(brief.trim() ? 'words' : 'color')
  const [loading, setLoading] = useState(false)
  // The account's own AI when it has one switched on; without it, or when it fails, the rules of `lib/generate.ts`.
  const [aiReady, setAiReady] = useState(false)
  const [aiProblem, setAiProblem] = useState<string | null>(null)
  useEffect(() => {
    aiApi.state().then((s) => setAiReady(s.ready), () => setAiReady(false))
  }, [])
  const propose = async () => {
    setLoading(true)
    setAiProblem(null)
    if (aiReady && brief.trim().length >= 3) {
      try {
        const answer = await aiApi.directions(brief.trim(), name.trim(), i18n.language.startsWith('de') ? 'German' : 'English')
        setDirs(fromAi(answer.directions, names))
        setLoading(false)
        return
      } catch (error) {
        setAiProblem(error instanceof ApiError ? error.code : 'internal_error')
      }
    }
    window.setTimeout(() => (setDirs(directions(brief, name, names)), setLoading(false)), 300)
  }
  const [start, setStart] = useState('#2E7D5B')
  const [found, setFound] = useState<string[] | null>(null)
  const [picture, setPicture] = useState<string | null>(null)
  const canvas = useRef<HTMLCanvasElement>(null)

  const read = (draw: (ctx: CanvasRenderingContext2D) => void) => {
    const c = canvas.current!
    const ctx = c.getContext('2d', { willReadFrequently: true })!
    ctx.clearRect(0, 0, 96, 96)
    draw(ctx)
    setPicture(c.toDataURL())
    setFound(colorsOfImage(ctx.getImageData(0, 0, 96, 96).data))
  }
  const loadFile = (file: File) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      read((ctx) => ctx.drawImage(img, 0, 0, 96, 96))
      URL.revokeObjectURL(url)
    }
    img.src = url
  }

  const modes = [
    ['words', Sparkles],
    ['picture', ImagePlus],
    ['color', Pipette],
    ['empty', Eraser],
  ] as const

  return (
    <Panel title={t('wizard.startTitle')} text={t('wizard.startText')}>
      <div className="flex flex-wrap gap-2" role="tablist">
        {modes.map(([m, Icon]) => (
          <button key={m} type="button" role="tab" aria-selected={mode === m} onClick={() => setMode(m)} className={'inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm ' + (mode === m ? 'border-accent-500/60 bg-accent-500/15 text-accent-400' : 'border-ink-700 text-mist-400 hover:text-mist-100')}>
            <Icon className="h-4 w-4" /> {t(`wizard.mode.${m}`)}
          </button>
        ))}
      </div>

      {mode === 'words' && (
        <div className="space-y-3">
          <p className="rounded-xl bg-ink-850 px-3 py-2 text-sm text-mist-300">„{brief.trim() || t('wizard.noBrief')}“</p>
          {!dirs && (
            <button
              type="button"
              className="nc-btn nc-btn-accent"
              disabled={loading}
              onClick={() => void propose()}
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} {aiReady ? t('wizard.proposeAi') : t('wizard.propose')}
            </button>
          )}
          {!dirs && <p className="text-xs text-mist-500">{aiReady ? t('wizard.aiHint') : t('wizard.rulesHint')}</p>}
          {aiProblem && (
            <p role="status" className="text-xs text-warn-500">
              {t('wizard.aiFailed', { reason: errorText(aiProblem) })}
            </p>
          )}
          {dirs && (
            <>
              <p className="text-xs text-mist-500">{t('wizard.proposeNote')}</p>
              <div className="grid gap-3 xl:grid-cols-3">
                {dirs.map((d) => {
                  const n = check({ colors: d.colors, fonts: [], logos: [], scale: [] }).filter((h) => h.level !== 'info').length
                  return (
                    <article key={d.id} className="flex flex-col gap-3 rounded-xl border border-ink-700 bg-ink-850 p-3">
                      <WebPreview colors={d.colors} head={catalogFont(d.head)!.stack} body={catalogFont(d.body)!.stack} name={name || t('wizard.yourName')} fileUrl={mediaUrl} compact />
                      <div>
                        <h3 className="text-sm font-semibold">{d.label || t(`wizard.dir.${d.id}.label`)}</h3>
                        <p className="mt-1 text-xs text-gelb-text">{dirWhy(d)}</p>
                      </div>
                      <div className="flex items-center justify-between gap-2 text-xs text-mist-500">
                        <Swatches colors={d.colors} />
                        <span>
                          {familyOf(d.head)} / {familyOf(d.body)}
                        </span>
                      </div>
                      <div className="mt-auto flex items-center justify-between">
                        <span className={'rounded-full border px-2 py-0.5 text-[11px] ' + (n ? 'border-warn-500/40 text-warn-500' : 'border-ok-500/40 text-ok-500')}>{n ? t('editor.hints', { count: n }) : t('editor.allGood')}</span>
                        <button type="button" className="nc-btn nc-btn-accent !px-2.5 !py-0.5 !text-xs" onClick={() => onTake(d)}>
                          {t('wizard.takeThis')}
                        </button>
                      </div>
                    </article>
                  )
                })}
              </div>
            </>
          )}
        </div>
      )}

      {mode === 'picture' && (
        <div className="space-y-3">
          <p className="text-sm text-mist-500">{t('wizard.pictureText')}</p>
          <label className="nc-btn nc-btn-ghost cursor-pointer">
            <ImagePlus className="h-4 w-4" /> {t('wizard.pickPicture')}
            <input type="file" accept="image/*" className="sr-only" onChange={(e) => e.target.files?.[0] && loadFile(e.target.files[0])} />
          </label>
          <canvas ref={canvas} width={96} height={96} className="hidden" />
          {picture && found && (
            <div className="flex flex-wrap items-center gap-4">
              <img src={picture} alt={t('wizard.picture')} className="h-24 w-24 rounded-xl border border-ink-700" style={{ imageRendering: 'pixelated' }} />
              <div className="flex flex-wrap gap-1.5">
                {found.map((c) => (
                  <span key={c} className="grid h-14 w-14 place-items-end rounded-lg border border-ink-700 p-1 font-mono text-[9px]" style={{ background: c, color: textOn(c) }}>
                    {c}
                  </span>
                ))}
              </div>
              <button type="button" className="nc-btn nc-btn-accent" onClick={() => onColors(rolesFor(found, names))}>
                {t('wizard.takeColors')}
              </button>
            </div>
          )}
        </div>
      )}

      {mode === 'color' && (
        <div className="space-y-3">
          <p className="text-sm text-mist-500">{t('wizard.colorText')}</p>
          <div className="flex items-center gap-2">
            <input type="color" aria-label={t('wizard.startColor')} value={isHex(start) ? start : '#000000'} onChange={(e) => setStart(e.target.value.toUpperCase())} className="h-10 w-14 rounded-lg border border-ink-700 bg-ink-850" />
            <input value={start} onChange={(e) => setStart(e.target.value)} aria-label={t('wizard.startColor')} className="h-10 w-28 rounded-lg border border-ink-700 bg-ink-850 px-3 font-mono text-sm" />
            <button type="button" className="nc-btn nc-btn-accent" disabled={!isHex(start)} onClick={() => onColors(oneColor(start, names))}>
              {t('wizard.takeThis')}
            </button>
          </div>
        </div>
      )}

      {mode === 'empty' && (
        <div className="space-y-3">
          <p className="text-sm text-mist-500">{t('wizard.emptyText')}</p>
          <button type="button" className="nc-btn nc-btn-accent" onClick={onEmpty}>
            {t('wizard.startEmpty')}
          </button>
        </div>
      )}
    </Panel>
  )
}

/** The logo goes into the client's files: the client is made for it, if it is not there yet. */
function LogoUpload({ ensure, logo, onChange }: { ensure: () => Promise<number>; logo?: MediaInfo; onChange: (m?: MediaInfo) => void }) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className={'nc-btn nc-btn-ghost cursor-pointer ' + (busy ? 'opacity-50' : '')}>
        <ImagePlus className="h-4 w-4" /> {t('wizard.uploadLogo')}
        <input
          type="file"
          accept=".svg,.png,.jpg,.jpeg,.webp,.gif,.avif,.bmp,.heic,.heif,image/*"
          className="sr-only"
          disabled={busy}
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (!file) return
            setBusy(true)
            setProblem(null)
            ensure()
              .then((space) => mediaApi.upload(space, file, file.name, undefined, 'picture'))
              // The server refuses what is no picture and keeps nothing of it (`expect`, F9).
              .then((m) => onChange(m))
              .catch((error) => setProblem(error instanceof ApiError ? error.code : 'internal_error'))
              .finally(() => setBusy(false))
          }}
        />
      </label>
      {logo && (
        <button type="button" className="nc-btn nc-btn-ghost" onClick={() => onChange(undefined)}>
          {t('wizard.removeLogo')}
        </button>
      )}
      <span className="text-xs text-mist-500">{logo ? t('wizard.logoUploaded') : t('wizard.noLogoYet')}</span>
      {problem && (
        <p role="alert" className="w-full text-sm text-bad-500">
          {errorText(problem)}
        </p>
      )}
    </div>
  )
}
