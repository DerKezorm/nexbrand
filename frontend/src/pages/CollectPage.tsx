/**
 * Collecting a brand (`routers/collect.py`): websites, GitHub repositories and PDF style guides give colours, fonts
 * and logos; the values are always measured, rules or the account's AI only sort them (roles, names, what does not
 * belong). Two ways on from there:
 *
 * - **Take as draft**: a new draft of an existing client (colours and fonts replaced, the rest kept from the current
 *   version) or a new client. Nothing is published; a person does that in the client's page.
 * - **Check against the CI**: every colour found next to the nearest one of the current version (ΔE 2000): the same,
 *   nearly right (the wrong shade in a style sheet), or foreign; fonts the CI does not name.
 */
import { AlertTriangle, Check, CircleSlash, FileText, Github, Globe, Plus, Sparkles, Trash2, Wand2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { aiApi, ApiError, clientsApi, collectApi, upload, type ClientWhole, type Collected, type FontFileTaken, type FoundColor, type FoundFont, type MediaInfo, type SourceKind } from '../api/client'
import { COLOR_ROLES, type BrandColor, type BrandFont, type BrandLogo, type BrandSet, emptySet } from '../lib/brand'
import { deltaE, textOn } from '../lib/color'
import { errorText } from '../lib/errors'
import { catalogEntry, CATALOG } from '../lib/fonts'
import { useAuth } from '../state/auth'
import { useBrands } from '../state/brands'

type Source = { kind: SourceKind; value: string; file?: File; name?: string }
type Mode = 'draft' | 'audit'
type Taken = { url: string; media: MediaInfo }

const KIND_ICON = { website: Globe, repo: Github, pdf: FileText }
const FIELD = 'h-9 rounded-lg border border-ink-700 bg-ink-850 px-2 text-sm text-mist-100 outline-none focus:border-accent-500'
const MAX_SOURCES = 6

/** The nearest colour of a design set and how far it is (CIEDE2000). */
function nearest(hex: string, colors: BrandColor[]): { color: BrandColor; distance: number } | null {
  let best: { color: BrandColor; distance: number } | null = null
  for (const color of colors) {
    const distance = deltaE(hex, color.hex)
    if (!best || distance < best.distance) best = { color, distance }
  }
  return best
}

function fontOf(found: FoundFont, role: string, taken: FontFileTaken[] = [], note = ''): BrandFont {
  const known = CATALOG.find((f) => f.family.toLocaleLowerCase() === found.family.toLocaleLowerCase())
  if (known && !taken.length) return catalogEntry(known.id, role)
  // A font of unknown licence stays internal: never handed out as a file, also with files taken.
  const license = found.license === 'free' ? 'free' : 'internal'
  const weights = [...new Set(taken.map((f) => Number(/\d+/.exec(f.weight)?.[0] ?? 400)))].sort((a, b) => a - b)
  return {
    family: found.family,
    role,
    weights: weights.length ? weights : [400, 700],
    italic: taken.some((f) => f.style.toLowerCase().includes('italic')),
    license,
    ...(note ? { license_note: note } : {}),
    source: found.detail,
    files: taken.map((f) => f.id),
  }
}

/** The last part of an address, without its query: a file's name to show instead of the whole address. */
function fileName(url: string): string {
  try {
    return decodeURIComponent(new URL(url).pathname.split('/').filter(Boolean).pop() ?? url)
  } catch {
    return url
  }
}

/** The server names where a font was found in English; the few fixed phrases are said in the page's language. */
function useDetail() {
  const { t } = useTranslation()
  return (detail: string) => (detail === 'embedded in the PDF' ? t('collect.details.pdf') : detail)
}

export function CollectPage() {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const brands = useBrands()
  const detailText = useDetail()
  const writable = brands.clients.filter((c) => c.role === 'write' || c.role === 'manage')
  const [target, setTarget] = useState<string>(params.get('client') ?? '')
  const [newName, setNewName] = useState('')
  const [mode, setMode] = useState<Mode>(params.get('mode') === 'audit' ? 'audit' : 'draft')
  const [sources, setSources] = useState<Source[]>([{ kind: 'website', value: '' }])
  const [useAi, setUseAi] = useState(false)
  const [aiReady, setAiReady] = useState(false)
  const [result, setResult] = useState<Collected | null>(null)
  const [colors, setColors] = useState<FoundColor[]>([])
  const [fonts, setFonts] = useState<FoundFont[]>([])
  const [taken, setTaken] = useState<Taken[]>([])
  // Fonts whose files are to be taken (by family), and the person's word that the licence allows it.
  const [withFiles, setWithFiles] = useState<Record<string, boolean>>({})
  const [licensed, setLicensed] = useState(false)
  const [whole, setWhole] = useState<ClientWhole | null>(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  useEffect(() => {
    aiApi.state().then((s) => {
      setAiReady(s.ready)
      setUseAi(s.ready)
    }, () => setAiReady(false))
  }, [])
  useEffect(() => {
    if (!target) return setWhole(null)
    clientsApi.read(target).then((found) => {
      setWhole(found)
      // The client's addresses stand ready: with nothing typed yet, they are the sources.
      setSources((now) => (now.every((s) => !s.value.trim() && !s.file) && found.links.length ? found.links.map((l) => ({ kind: l.kind, value: l.url })) : now))
    }, () => setWhole(null))
  }, [target])
  const canKeep = !!whole && (whole.role === 'write' || whole.role === 'manage')
  const known = (url: string) => (whole?.links ?? []).some((l) => l.url.replace(/\/$/, '') === url.trim().replace(/\/$/, ''))
  const remember = (kind: SourceKind, url: string) =>
    act(async () => {
      if (!whole || kind === 'pdf') return
      await clientsApi.change(whole.id, { links: [...whole.links, { kind, url: url.trim(), label: '' }] })
      setWhole(await clientsApi.read(whole.id))
    })

  const mayCreate = !!me?.may_create_clients
  // Without the right to make clients, a draft goes to one that exists: the first one writable is chosen.
  useEffect(() => {
    if (mode === 'draft' && !target && !mayCreate && writable[0]) setTarget(writable[0].id)
  }, [mode, target, mayCreate, writable])

  /** The client the files go to: the one chosen, or a new one under the name typed, made once and then chosen. */
  const ensure = async (): Promise<{ id: string; space_id: number }> => {
    if (target) {
      if (!whole) throw new ApiError(400, 'collect_space_first')
      return { id: whole.id, space_id: whole.space_id }
    }
    if (!newName.trim()) throw new ApiError(400, 'collect_name_first')
    const fresh = await clientsApi.create({ name: newName.trim(), label: '' })
    await brands.refresh()
    setWhole(fresh)
    setTarget(fresh.id)
    return { id: fresh.id, space_id: fresh.space_id }
  }
  // The version that holds today, as the server says (`current_id`): one published to hold from a later day is not
  // what the CI is checked against, nor what a draft starts from (F2).
  const current = whole?.versions.find((v) => v.id === whole.current_id) ?? null
  const ci = useMemo(() => current?.data.colors ?? [], [current])

  const kept = colors.filter((c) => c.keep)
  const audit = useMemo(
    () =>
      colors
        .filter((c) => c.share >= 0.5)
        .map((c) => {
          const near = nearest(c.hex, ci)
          const state = !near ? 'foreign' : near.distance < 1 ? 'same' : near.distance < 8 ? 'near' : 'foreign'
          return { found: c, near, state }
        }),
    [colors, ci],
  )
  const foreignFonts = fonts.filter((f) => !(current?.data.fonts ?? []).some((own) => own.family.toLocaleLowerCase() === f.family.toLocaleLowerCase()))

  const act = async (work: () => Promise<void>) => {
    setBusy(true)
    setProblem(null)
    try {
      await work()
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
    } finally {
      setBusy(false)
    }
  }

  const run = () =>
    act(async () => {
      const sent: { kind: SourceKind; value: string }[] = []
      const next = [...sources]
      for (const [index, source] of next.entries()) {
        if (source.kind === 'pdf' && source.file && !source.value) {
          const space = (await ensure()).space_id
          const media = await upload<MediaInfo>('/api/media', { space, name: source.file.name }, source.file)
          next[index] = { ...source, value: media.id, name: media.name }
        }
        if (next[index].value.trim()) sent.push({ kind: next[index].kind, value: next[index].value.trim() })
      }
      setSources(next)
      if (sent.length === 0) throw new ApiError(400, 'collect_nothing')
      const found = await collectApi.run(sent, useAi && aiReady, i18n.language)
      setResult(found)
      setColors(found.colors)
      setFonts(found.fonts)
      setTaken([])
    })

  const takeLogo = (url: string) =>
    act(async () => {
      const media = await collectApi.logo((await ensure()).id, url)
      setTaken((list) => [...list.filter((x) => x.url !== url), { url, media }])
    })

  const designSet = (fontFiles: Record<string, FontFileTaken[]> = {}, note = ''): BrandSet => {
    const base: BrandSet = current ? structuredClone(current.data) : emptySet()
    const primary = kept.find((c) => c.role === 'primary')?.hex ?? kept[0]?.hex ?? '#000000'
    const accent = kept.find((c) => c.role === 'accent')?.hex ?? primary
    if (kept.length) base.colors = kept.map((c) => ({ name: c.name || c.hex, hex: c.hex, role: c.role, ...(c.pantone ? { pantone: c.pantone } : {}), ...(c.cmyk ? { cmyk: c.cmyk } : {}), ...(c.reason ? { note: c.reason } : {}) }))
    const keptFonts = fonts.filter((f) => f.keep)
    if (keptFonts.length) base.fonts = keptFonts.map((f) => fontOf(f, t(`collect.uses.${f.use}`), fontFiles[f.family], fontFiles[f.family]?.length ? note : ''))
    const logos: BrandLogo[] = taken.map((x, index) => ({
      id: `collect-${Date.now().toString(36)}-${index}`,
      name: x.media.name.replace(/\.[^.]+$/, ''),
      media: x.media.id,
      fg: primary,
      accent,
      ground: '#FFFFFF',
    }))
    base.logos = [...base.logos, ...logos]
    return base
  }

  const takeAsDraft = () =>
    act(async () => {
      const label = t('collect.label', { date: new Date().toLocaleDateString(i18n.language) })
      // Font files first, into the client's files: only those ticked, and only with the licence confirmed.
      const wanted = fonts.filter((f) => f.keep && withFiles[f.family] && f.files.length)
      const fontFiles: Record<string, FontFileTaken[]> = {}
      let into = target
      if (wanted.length) {
        if (!licensed) throw new ApiError(422, 'licence_not_confirmed')
        into = (await ensure()).id
        for (const font of wanted) fontFiles[font.family] = (await collectApi.fonts(into, font.family, font.files, true)).files
      }
      const note = t('collect.licenceNote', { name: me?.display_name || me?.name || '', date: new Date().toLocaleDateString(i18n.language) })
      if (into) {
        const version = await clientsApi.newVersion(into, { label, source: current && into === whole?.id ? current.id : undefined, data: designSet(fontFiles, note), origin: 'collect', note: t('collect.note', { count: sources.filter((s) => s.value).length }) })
        await brands.refresh()
        navigate(`/c/${into}?v=${version.id}`)
      } else {
        const made = await clientsApi.create({ name: newName.trim(), label, data: designSet() })
        await brands.refresh()
        navigate(`/c/${made.id}`)
      }
    })

  const ready = sources.some((s) => s.value.trim() || s.file)
  const filesWanted = fonts.some((f) => f.keep && withFiles[f.family] && f.files.length)
  // Something to take: colours, a font, or a logo. Without colours ticked, the current version's colours stay.
  const something = kept.length > 0 || fonts.some((f) => f.keep) || taken.length > 0
  const canTake = something && (target ? !!whole : newName.trim().length > 0 && mayCreate) && (!filesWanted || licensed)

  return (
    <main className="nc-scroll min-w-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl space-y-5 px-4 py-6 sm:px-6 sm:py-8">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t('collect.title')}</h1>
          <p className="mt-1 max-w-2xl text-sm text-mist-500">{t('collect.text')}</p>
        </div>

        <section className="space-y-4 rounded-2xl border border-ink-700 bg-ink-900 p-5">
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={t('collect.mode')}>
            {(['draft', 'audit'] as const).map((value) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={mode === value}
                onClick={() => setMode(value)}
                className={'rounded-full border px-3 py-1 text-sm ' + (mode === value ? 'border-accent-500/60 bg-accent-500/10 text-mist-100' : 'border-ink-700 text-mist-300 hover:bg-ink-850')}
              >
                {t(`collect.modes.${value}`)}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-sm">
              <span className="block text-xs font-medium text-mist-400">{t('collect.client')}</span>
              <select value={target} onChange={(event) => setTarget(event.target.value)} aria-label={t('collect.client')} className={FIELD + ' mt-1 w-64 max-w-full'}>
                {mode === 'draft' && mayCreate && <option value="">{t('collect.newClient')}</option>}
                {mode === 'audit' && <option value="">{t('collect.pick')}</option>}
                {(mode === 'audit' ? brands.clients : writable).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            {mode === 'draft' && !target && (
              <>
                <label className="text-sm">
                  <span className="block text-xs font-medium text-mist-400">{t('collect.newName')}</span>
                  <input value={newName} onChange={(event) => setNewName(event.target.value)} maxLength={120} className={FIELD + ' mt-1 w-56'} />
                </label>
              </>
            )}
          </div>
          {mode === 'audit' && whole && !current && <p className="text-sm text-mist-500">{t('collect.noCurrent')}</p>}

          <div className="space-y-2">
            <h2 className="text-sm font-semibold">{t('collect.sources')}</h2>
            {sources.map((source, index) => {
              const Icon = KIND_ICON[source.kind]
              const change = (patch: Partial<Source>) => setSources((list) => list.map((s, i) => (i === index ? { ...s, ...patch } : s)))
              return (
                <div key={index} className="flex flex-wrap items-center gap-2">
                  <Icon className="h-4 w-4 shrink-0 text-mist-500" aria-hidden />
                  <select
                    value={source.kind}
                    onChange={(event) => change({ kind: event.target.value as SourceKind, value: '', file: undefined, name: undefined })}
                    aria-label={t('collect.kind')}
                    className={FIELD + ' w-40'}
                  >
                    {(['website', 'repo', 'pdf'] as const).map((kind) => (
                      <option key={kind} value={kind}>
                        {t(`collect.kinds.${kind}`)}
                      </option>
                    ))}
                  </select>
                  {source.kind === 'pdf' ? (
                    <label className="flex min-w-0 flex-1 items-center gap-2 text-sm text-mist-300">
                      <input
                        type="file"
                        accept="application/pdf,.pdf"
                        aria-label={t('collect.kinds.pdf')}
                        onChange={(event) => change({ file: event.target.files?.[0], value: '', name: event.target.files?.[0]?.name })}
                        className="min-w-0 flex-1 text-xs file:mr-2 file:rounded-full file:border file:border-ink-700 file:bg-ink-850 file:px-3 file:py-1 file:text-mist-200"
                      />
                    </label>
                  ) : (
                    <input
                      value={source.value}
                      onChange={(event) => change({ value: event.target.value })}
                      placeholder={source.kind === 'repo' ? 'https://github.com/example/site' : 'https://www.example.com'}
                      aria-label={t(`collect.kinds.${source.kind}`)}
                      maxLength={2000}
                      className={FIELD + ' min-w-0 flex-1 font-mono text-xs'}
                    />
                  )}
                  {canKeep && source.kind !== 'pdf' && /^https?:\/\/\S+/.test(source.value.trim()) && !known(source.value) && (
                    <button type="button" onClick={() => void remember(source.kind, source.value)} className="nc-btn nc-btn-ghost !px-2.5 !py-0.5 !text-xs" title={t('collect.rememberHint', { name: whole?.name })}>
                      <Plus className="h-3.5 w-3.5" /> {t('collect.remember')}
                    </button>
                  )}
                  {sources.length > 1 && (
                    <button type="button" onClick={() => setSources((list) => list.filter((_, i) => i !== index))} aria-label={t('collect.remove')} className="rounded-full p-1.5 text-mist-500 hover:bg-ink-850 hover:text-bad-500">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
              )
            })}
            {sources.length < MAX_SOURCES && (
              <button type="button" onClick={() => setSources((list) => [...list, { kind: 'website', value: '' }])} className="nc-btn nc-btn-ghost !px-2.5 !py-0.5 !text-xs">
                <Plus className="h-3.5 w-3.5" /> {t('collect.add')}
              </button>
            )}
            {whole && whole.links.some((l) => !sources.some((s) => s.value.trim().replace(/\/$/, '') === l.url.replace(/\/$/, ''))) && (
              <div className="flex flex-wrap items-center gap-2 text-xs text-mist-500" data-testid="client-links">
                {t('collect.stored')}
                {whole.links
                  .filter((l) => !sources.some((s) => s.value.trim().replace(/\/$/, '') === l.url.replace(/\/$/, '')))
                  .map((l) => (
                    <button
                      key={l.url}
                      type="button"
                      onClick={() =>
                        setSources((list) => {
                          const free = list.findIndex((s) => !s.value.trim() && !s.file)
                          const item = { kind: l.kind as SourceKind, value: l.url }
                          return free >= 0 ? list.map((s, i) => (i === free ? item : s)) : [...list, item].slice(0, MAX_SOURCES)
                        })
                      }
                      className="rounded-full border border-ink-700 px-2.5 py-0.5 font-mono text-mist-300 hover:bg-ink-850"
                    >
                      {l.label || l.url.replace(/^https?:\/\//, '')}
                    </button>
                  ))}
              </div>
            )}
          </div>

          <label className="flex items-start gap-3 text-sm">
            <input type="checkbox" checked={useAi && aiReady} disabled={!aiReady} onChange={(event) => setUseAi(event.target.checked)} className="mt-1" />
            <span>
              <span className="flex items-center gap-1.5 font-medium text-mist-100">
                <Sparkles className="h-3.5 w-3.5 text-accent-400" /> {t('collect.useAi')}
              </span>
              <span className="block text-xs text-mist-500">
                {aiReady ? t('collect.useAiHint') : t('collect.aiNotReady')}{' '}
                {!aiReady && (
                  <Link to="/account?tab=ai" className="text-accent-400 hover:underline">
                    {t('collect.aiSetUp')}
                  </Link>
                )}
              </span>
            </span>
          </label>
          <p className="text-xs text-mist-500">
            {t('collect.privacy')} {me?.role === 'operator' && <Link to="/settings?tab=server&sub=outside" className="text-accent-400 hover:underline">{t('collect.operatorSwitch')}</Link>}
          </p>

          <div className="flex flex-wrap items-center gap-3">
            <button type="button" disabled={busy || !ready || (mode === 'audit' && !current)} onClick={() => void run()} className="nc-btn nc-btn-accent">
              <Wand2 className="h-4 w-4" /> {busy && !result ? t('collect.running') : t('collect.run')}
            </button>
            <div aria-live="polite">
              {problem && (
                <p role="alert" className="text-sm text-bad-500">
                  {errorText(problem)}
                </p>
              )}
            </div>
          </div>
        </section>

        {result && (
          <>
            {result.notes.length > 0 && (
              <ul className="space-y-1 rounded-xl border border-warn-500/30 bg-warn-500/8 px-4 py-3 text-sm" data-testid="collect-notes">
                {result.notes.map((note, index) => (
                  <li key={index} className="flex items-start gap-2">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warn-500" />
                    <span>
                      <span className="font-mono text-xs break-all">{note.source === 'ai' ? t('collect.theAi') : sources.find((s) => s.value === note.source)?.name ?? note.source}</span> · {note.source === 'ai' ? errorText(note.problem) : t(`collect.problems.${note.problem}`, { defaultValue: t('collect.problems.unreadable') })}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {colors.length === 0 && fonts.length === 0 && <p className="text-sm text-mist-500">{t('collect.nothing')}</p>}

            {mode === 'draft' && colors.length > 0 && (
              <section className="rounded-2xl border border-ink-700 bg-ink-900 p-5" data-testid="collect-colors">
                <h2 className="mb-1 font-semibold">{t('collect.colors')}</h2>
                <p className="mb-3 text-xs text-mist-500">{result.ai ? t('collect.sortedByAi') : t('collect.sortedByRules')}</p>
                <ul className="divide-y divide-ink-800">
                  {colors.map((color, index) => {
                    const change = (patch: Partial<FoundColor>) => setColors((list) => list.map((c, i) => (i === index ? { ...c, ...patch } : c)))
                    return (
                      <li key={color.hex} className={'flex flex-wrap items-center gap-3 py-2 ' + (color.keep ? '' : 'opacity-60')}>
                        <input type="checkbox" checked={color.keep} onChange={(event) => change({ keep: event.target.checked })} aria-label={t('collect.keep', { hex: color.hex })} />
                        <span className="grid h-9 w-14 shrink-0 place-items-center rounded-lg border border-ink-600 font-mono text-[10px]" style={{ background: color.hex, color: textOn(color.hex) }}>
                          {color.share.toLocaleString(i18n.language, { maximumFractionDigits: 1 })} %
                        </span>
                        <input value={color.name} onChange={(event) => change({ name: event.target.value })} maxLength={60} aria-label={t('collect.name')} className={FIELD + ' w-40'} />
                        <select value={color.role} onChange={(event) => change({ role: event.target.value as FoundColor['role'] })} aria-label={t('collect.role')} className={FIELD + ' w-32'}>
                          {COLOR_ROLES.map((role) => (
                            <option key={role} value={role}>
                              {t(`roles.color.${role}`)}
                            </option>
                          ))}
                        </select>
                        <span className="font-mono text-xs text-mist-300">{color.hex}</span>
                        {color.framework && (
                          <span className="shrink-0 rounded-full border border-ink-600 px-2 py-0.5 text-[11px] text-mist-400" title={t('collect.frameworkHint')}>
                            {t('collect.framework')}
                          </span>
                        )}
                        <span className="min-w-0 flex-1 truncate text-xs text-mist-500" title={color.detail}>
                          {color.reason || color.detail}
                        </span>
                      </li>
                    )
                  })}
                </ul>
              </section>
            )}

            {mode === 'audit' && current && audit.length > 0 && (
              <section className="rounded-2xl border border-ink-700 bg-ink-900 p-5" data-testid="collect-audit">
                <h2 className="mb-1 font-semibold">{t('collect.auditTitle', { label: current.label })}</h2>
                <p className="mb-3 text-xs text-mist-500">{t('collect.auditText')}</p>
                <ul className="divide-y divide-ink-800">
                  {audit.map(({ found, near, state }) => (
                    <li key={found.hex} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                      {state === 'same' ? <Check className="h-4 w-4 text-ok-500" /> : state === 'near' ? <AlertTriangle className="h-4 w-4 text-warn-500" /> : <CircleSlash className="h-4 w-4 text-mist-500" />}
                      <span className="h-7 w-10 rounded-md border border-ink-600" style={{ background: found.hex }} />
                      <span className="font-mono text-xs">{found.hex}</span>
                      {near && state !== 'foreign' && (
                        <>
                          <span className="text-mist-500">→</span>
                          <span className="h-7 w-10 rounded-md border border-ink-600" style={{ background: near.color.hex }} />
                          <span className="text-xs">
                            {near.color.name} <span className="font-mono text-mist-500">{near.color.hex}</span>
                          </span>
                        </>
                      )}
                      <span className="min-w-0 flex-1 text-xs text-mist-400">
                        {state === 'same' ? t('collect.same') : state === 'near' ? t('collect.near', { de: near!.distance.toLocaleString(i18n.language, { maximumFractionDigits: 1 }) }) : t('collect.foreign', { share: found.share.toLocaleString(i18n.language, { maximumFractionDigits: 1 }) })}
                      </span>
                      <span className="w-full truncate pl-7 text-[11px] text-mist-500 sm:w-auto sm:pl-0" title={found.detail}>
                        {found.detail}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {result.system_font && (
              <p className="rounded-xl border border-ink-700 bg-ink-900 px-4 py-3 text-sm text-mist-300" data-testid="collect-system-font">
                {t('collect.systemFont', { stack: result.system_font })}
              </p>
            )}
            {fonts.length > 0 && (
              <section className="rounded-2xl border border-ink-700 bg-ink-900 p-5">
                <h2 className="mb-1 font-semibold">{t('collect.fonts')}</h2>
                {mode === 'draft' && <p className="mb-3 text-xs text-mist-500">{t('collect.fontsHint')}</p>}
                <ul className="divide-y divide-ink-800">
                  {fonts.map((font, index) => {
                    const change = (patch: Partial<FoundFont>) => setFonts((list) => list.map((f, i) => (i === index ? { ...f, ...patch } : f)))
                    const foreign = mode === 'audit' && foreignFonts.includes(font)
                    return (
                      <li key={font.family} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                        {mode === 'draft' ? (
                          <input type="checkbox" checked={font.keep} onChange={(event) => change({ keep: event.target.checked })} aria-label={t('collect.keepFont', { family: font.family })} />
                        ) : foreign ? (
                          <AlertTriangle className="h-4 w-4 text-warn-500" />
                        ) : (
                          <Check className="h-4 w-4 text-ok-500" />
                        )}
                        <span className="w-44 truncate font-medium">{font.family}</span>
                        {mode === 'draft' && (
                          <select value={font.use} onChange={(event) => change({ use: event.target.value as FoundFont['use'] })} aria-label={t('collect.use')} className={FIELD + ' w-36'}>
                            {(['headings', 'body', 'other'] as const).map((use) => (
                              <option key={use} value={use}>
                                {t(`collect.uses.${use}`)}
                              </option>
                            ))}
                          </select>
                        )}
                        <span className={'rounded-full border px-2 py-0.5 text-[11px] ' + (font.license === 'free' ? 'border-ok-500/40 text-ok-500' : 'border-magenta-500/40 text-magenta-500')}>
                          {t(`collect.license.${font.license}`)}
                        </span>
                        <span className="min-w-0 flex-1 truncate text-xs text-mist-500">{foreign ? t('collect.fontForeign') : detailText(font.detail)}</span>
                        {mode === 'draft' && font.files.length > 0 && (
                          <label className={'flex shrink-0 items-center gap-1.5 text-xs ' + (font.keep ? 'text-mist-300' : 'text-mist-600')}>
                            <input
                              type="checkbox"
                              disabled={!font.keep}
                              checked={font.keep && !!withFiles[font.family]}
                              onChange={(event) => setWithFiles((all) => ({ ...all, [font.family]: event.target.checked }))}
                            />
                            {t('collect.takeFiles', { count: font.files.length })}
                          </label>
                        )}
                      </li>
                    )
                  })}
                </ul>
              </section>
            )}

            {mode === 'draft' && result.logos.length > 0 && (
              <section className="rounded-2xl border border-ink-700 bg-ink-900 p-5">
                <h2 className="mb-1 font-semibold">{t('collect.logos')}</h2>
                <p className="mb-3 text-xs text-mist-500">{t('collect.logosText')}</p>
                <ul className="grid gap-2 sm:grid-cols-2">
                  {result.logos.map((logo) => {
                    const done = taken.some((x) => x.url === logo.url)
                    return (
                      <li key={logo.url} className="flex items-center gap-3 rounded-xl border border-ink-700 p-2 text-xs">
                        <span className="nb-checker grid h-14 w-20 shrink-0 place-items-center overflow-hidden rounded-lg border border-ink-700">
                          <img src={collectApi.previewUrl(logo.url)} alt={fileName(logo.url)} loading="lazy" className="max-h-12 max-w-[4.5rem] object-contain" onError={(event) => (event.currentTarget.style.visibility = 'hidden')} />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-medium text-mist-200" title={logo.url}>
                            {fileName(logo.url)}
                          </span>
                          <span className="block truncate text-mist-500">{t(`collect.logoKinds.${logo.kind}`, { defaultValue: logo.kind })}</span>
                        </span>
                        <button type="button" disabled={busy || done || (!target && !newName.trim())} onClick={() => void takeLogo(logo.url)} className="nc-btn nc-btn-ghost !px-2.5 !py-0.5 !text-xs">
                          {done ? <Check className="h-3.5 w-3.5" /> : null} {done ? t('collect.logoTaken') : t('collect.logoTake')}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </section>
            )}

            {mode === 'draft' && (colors.length > 0 || fonts.length > 0 || result.logos.length > 0) && (
              <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-accent-500/40 bg-accent-500/8 p-4">
                <span className="flex-1 text-sm">
                  {!target ? t('collect.takeNewHint', { count: kept.length }) : kept.length ? t('collect.takeHint', { count: kept.length }) : t('collect.takeKeepColors')}
                </span>
                {filesWanted && (
                  <label className="flex w-full items-start gap-2 rounded-xl border border-warn-500/40 bg-warn-500/8 px-3 py-2 text-sm" data-testid="font-licence">
                    <input type="checkbox" className="mt-1" checked={licensed} onChange={(event) => setLicensed(event.target.checked)} />
                    <span>{t('collect.licence')}</span>
                  </label>
                )}
                <button type="button" disabled={busy || !canTake} onClick={() => void takeAsDraft()} className="nc-btn nc-btn-accent">
                  {t('collect.take')}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </main>
  )
}
