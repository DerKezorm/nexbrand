/** One design set, shown the same way for a client, a project, a public page and a review. */
import { Ban, Check, Copy, Download, FileText, Lock, Moon, Palette, Shapes, ShieldCheck, Type, XCircle, type LucideIcon } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import type { FileInfo } from '../../api/client'
import { DARK_PARTS, schemeOf, type BrandFont, type BrandLogo, type BrandSet, type Sample, type ScaleStep, type ShownColor } from '../../lib/brand'
import { check } from '../../lib/checks'
import { cmyk, contrast, formatRatio, hsl, rgb, slug, textOn } from '../../lib/color'
import { copyText } from '../../lib/copy'
import { findFont, fontStack } from '../../lib/fonts'
import { TabRow, type Tab } from '../../pages/settings/ui'
import { HintList, Matrix, VisionPanel } from './Checks'
import { LogoView } from './LogoView'
import { WebPreview } from './WebPreview'
import { CheckedMark, RuleSwatch, typeOf, useRuleWords } from './rules'

export type ExtraTab = { value: string; label: string; icon: LucideIcon; content: ReactNode }

export function SetView({
  set,
  colors,
  fileUrl,
  files = {},
  extra = [],
  publicMode = false,
  actions,
  initialTab = 'colors',
  tab: chosenTab,
  onTab,
}: {
  set: BrandSet
  /** The colours to show instead of the set's own (a project's, with its own ones). */
  colors?: ShownColor[]
  fileUrl: (id: string) => string
  /** What is known of the files (names, kinds), for the downloads. */
  files?: Record<string, FileInfo>
  extra?: ExtraTab[]
  publicMode?: boolean
  actions?: ReactNode
  initialTab?: string
  /** The tab, held by the page (in its address): a button elsewhere on the page can open one. */
  tab?: string
  onTab?: (tab: string) => void
}) {
  const { t } = useTranslation()
  const shown: ShownColor[] = colors ?? set.colors
  const hints = useMemo(() => check(set, shown), [set, shown])
  const serious = hints.filter((h) => h.level !== 'info').length
  const [ownTab, setOwnTab] = useState<string>(initialTab)
  const tab = chosenTab ?? ownTab
  const setTab = onTab ?? setOwnTab
  const tabs: Tab<string>[] = [
    { value: 'colors', label: t('set.tabs.colors', { count: shown.length }), icon: Palette },
    { value: 'fonts', label: t('set.tabs.fonts', { count: set.fonts.length }), icon: Type },
    { value: 'logos', label: t('set.tabs.logos', { count: set.logos.length }), icon: Shapes },
    { value: 'samples', label: t('set.tabs.samples'), icon: FileText },
    { value: 'rules', label: t('set.tabs.rules'), icon: Ban },
    ...(publicMode ? [] : [{ value: 'checks', label: serious ? t('set.tabs.checksCount', { count: serious }) : t('set.tabs.checks'), icon: ShieldCheck }]),
    ...extra.map(({ value, label, icon }) => ({ value, label, icon })),
  ]
  const head = set.fonts[0]
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <TabRow tabs={tabs} active={tab} onChange={setTab} label={t('set.tabsLabel')} />
        {actions}
      </div>
      {tab === 'colors' && (
        <>
          <Colors colors={shown} />
          {set.dark && <DarkView set={set} colors={shown} fileUrl={fileUrl} />}
        </>
      )}
      {tab === 'fonts' && <Fonts fonts={set.fonts} scale={set.scale} fileUrl={fileUrl} files={files} publicMode={publicMode} />}
      {tab === 'logos' && <Logos logos={set.logos} fonts={set.fonts} fileUrl={fileUrl} files={files} />}
      {tab === 'samples' && <Samples samples={set.samples} fileUrl={fileUrl} files={files} />}
      {tab === 'rules' && <Rules set={set} colors={shown} />}
      {tab === 'checks' && (
        <div className="space-y-4">
          <HintList hints={hints} />
          <Matrix colors={shown} headFont={fontStack(head, fileUrl)} />
          <VisionPanel colors={shown} />
        </div>
      )}
      {extra.map((e) => tab === e.value && <div key={e.value}>{e.content}</div>)}
    </div>
  )
}

function CopyRow({ label, value }: { label: string; value: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      onClick={() => void copyText(value).then((ok) => (setCopied(ok), window.setTimeout(() => setCopied(false), 1200)))}
      className="group flex w-full items-center justify-between gap-2 rounded-md px-1.5 py-0.5 text-left hover:bg-ink-800"
      title={t('common.copy')}
    >
      <span className="text-[11px] text-mist-600">{label}</span>
      <span className="flex items-center gap-1.5 font-mono text-xs text-mist-200">
        {copied ? '✓' : value}
        <Copy className="h-3 w-3 text-mist-600 opacity-0 group-hover:opacity-100" aria-hidden />
      </span>
    </button>
  )
}

const FROM_TONE = { own: 'border-accent-500/40 text-accent-400', replaced: 'border-magenta-500/50 text-magenta-text', inherited: 'border-ink-700 text-mist-500' }

export function Chip({ children, className = 'border-ink-700 text-mist-500' }: { children: ReactNode; className?: string }) {
  return <span className={'inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ' + className}>{children}</span>
}

function Colors({ colors }: { colors: ShownColor[] }) {
  const { t, i18n } = useTranslation()
  if (!colors.length) return <p className="text-sm text-mist-500">{t('set.noColors')}</p>
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {colors.map((c) => {
        const on = textOn(c.hex)
        const [cc, mm, yy, kk] = cmyk(c.hex)
        const [h, s, l] = hsl(c.hex)
        return (
          <article key={c.name} className="overflow-hidden rounded-2xl border border-ink-700 bg-ink-900">
            <div className="flex h-28 items-end justify-between p-3" style={{ background: c.hex, boxShadow: 'inset 0 -1px 0 rgb(0 0 0 / .08)' }}>
              <span className="text-2xl font-semibold" style={{ color: on, fontFamily: "'Fraunces Variable', serif" }}>
                Aa
              </span>
              <span className="rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ color: on, border: `1px solid ${on}55` }}>
                {t(on === '#FFFFFF' ? 'set.whiteOn' : 'set.darkOn', { ratio: formatRatio(contrast(on, c.hex), i18n.language) })}
              </span>
            </div>
            <div className="space-y-2 p-3">
              <div className="flex flex-wrap items-center gap-1.5">
                <h3 className="mr-auto font-semibold">{c.name}</h3>
                <Chip>{t(`roles.color.${c.role}`)}</Chip>
                {c.from && <Chip className={FROM_TONE[c.from]}>{t(`set.from.${c.from}`)}</Chip>}
              </div>
              {c.note && <p className="text-xs text-mist-500">{c.note}</p>}
              <div>
                <CopyRow label="HEX" value={c.hex.toUpperCase()} />
                <CopyRow label="RGB" value={rgb(c.hex).join(', ')} />
                <CopyRow label="HSL" value={`${h}° ${s} % ${l} %`} />
                {c.cmyk ? <CopyRow label={t('set.cmykGiven')} value={c.cmyk} /> : <CopyRow label={t('set.cmykComputed')} value={`${cc} ${mm} ${yy} ${kk}`} />}
                {c.pantone && <CopyRow label="Pantone" value={c.pantone} />}
                <CopyRow label={t('set.token')} value={`--color-${slug(c.name)}`} />
              </div>
            </div>
          </article>
        )
      })}
    </div>
  )
}

const LICENSE_TONE = { free: 'border-ok-500/40 text-ok-500', internal: 'border-magenta-500/50 text-magenta-text', system: 'border-ink-700 text-mist-500' }

function Fonts({ fonts, scale, fileUrl, files, publicMode }: { fonts: BrandFont[]; scale: ScaleStep[]; fileUrl: (id: string) => string; files: Record<string, FileInfo>; publicMode: boolean }) {
  const { t } = useTranslation()
  if (!fonts.length) return <p className="text-sm text-mist-500">{t('set.noFonts')}</p>
  return (
    <div className="space-y-3">
      {fonts.map((f) => {
        const stack = fontStack(f, fileUrl)
        const style = { fontFamily: stack, fontStyle: f.italic ? 'italic' : undefined }
        const downloads = (f.files ?? []).filter(() => !publicMode || f.license === 'free')
        return (
          <article key={f.family} className="rounded-2xl border border-ink-700 bg-ink-900 p-5">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="mr-auto font-semibold">
                {f.family} {f.role && <span className="font-normal text-mist-500">· {f.role}</span>}
              </h3>
              <Chip className={LICENSE_TONE[f.license]}>
                {f.license === 'internal' && <Lock className="h-3 w-3" aria-hidden />}
                {t(`set.license.${f.license}`)}
              </Chip>
              {f.catalog && <Chip>{t('set.shipped')}</Chip>}
            </div>
            <p className="mt-4 text-4xl leading-tight text-mist-100" style={{ ...style, fontWeight: f.weights[Math.min(1, f.weights.length - 1)] }}>
              {t('set.pangram')}
            </p>
            <p className="mt-2 text-lg text-mist-300" style={style}>
              ABCDEFGHIJKLM abcdefghijklm 0123456789 äöüß € &amp; ?!
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {f.weights.map((w) => (
                <span key={w} className="rounded-lg border border-ink-700 px-2.5 py-1 text-sm text-mist-200" style={{ ...style, fontWeight: w }}>
                  {w} Aa
                </span>
              ))}
            </div>
            {(f.license_note || f.source) && <p className="mt-3 text-xs text-mist-500">{[f.license_note, f.source].filter(Boolean).join(' · ')}</p>}
            {downloads.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {downloads.map((id) => (
                  <a key={id} href={fileUrl(id) + (fileUrl(id).includes('?') ? '&' : '?') + 'download=true'} className="nc-btn nc-btn-ghost !px-2.5 !py-0.5 !text-xs">
                    <Download className="h-3.5 w-3.5" /> {files[id]?.name ?? t('set.file')}
                  </a>
                ))}
              </div>
            )}
          </article>
        )
      })}
      {scale.length > 0 && (
        <section className="rounded-2xl border border-ink-700 bg-ink-900 p-5">
          <h3 className="font-semibold">{t('set.scale')}</h3>
          <div className="mt-3 divide-y divide-ink-700">
            {scale.map((s) => (
              <div key={s.name} className="flex items-baseline gap-4 py-2.5">
                <span className="w-36 shrink-0 text-xs text-mist-500">
                  {s.name}
                  {s.use && <span className="ml-1 text-mist-600">({t(`set.use.${s.use}`)})</span>}
                  <br />
                  <span className="font-mono">
                    {s.size} px · {s.weight} · {s.line_height}
                  </span>
                </span>
                <span className="min-w-0 truncate text-mist-100" style={{ fontFamily: fontStack(findFont(fonts, s.font), fileUrl), fontSize: Math.min(s.size, 56), fontWeight: s.weight, lineHeight: s.line_height }}>
                  {t('set.scaleSample')}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

function Logos({ logos, fonts, fileUrl, files }: { logos: BrandLogo[]; fonts: BrandFont[]; fileUrl: (id: string) => string; files: Record<string, FileInfo> }) {
  const { t } = useTranslation()
  const [zone, setZone] = useState(false)
  if (!logos.length) return <p className="text-sm text-mist-500">{t('set.noLogos')}</p>
  return (
    <div className="space-y-3">
      <label className="flex w-fit items-center gap-2 text-sm text-mist-400">
        <input type="checkbox" checked={zone} onChange={(e) => setZone(e.target.checked)} className="h-4 w-4 accent-accent-500" />
        {t('set.clearSpace')}
      </label>
      <div className="grid gap-3 sm:grid-cols-2">
        {logos.map((l) => {
          const drawn = !l.media && l.ground !== 'transparent'
          const low = drawn && Math.min(contrast(l.accent, l.ground), l.compact ? 99 : contrast(l.fg, l.ground)) < 3
          const downloads = [l.media, ...(l.files ?? [])].filter((id): id is string => !!id)
          return (
            <article key={l.id} className="overflow-hidden rounded-2xl border border-ink-700 bg-ink-900">
              <div className={'grid h-40 place-items-center px-6 ' + (l.ground === 'transparent' ? 'nb-checker' : '')} style={l.ground !== 'transparent' ? { background: l.ground } : undefined}>
                <div className={zone ? 'outline-2 outline-offset-[14px] outline-dashed' : ''} style={{ outlineColor: zone ? '#e255f5' : undefined }}>
                  <LogoView logo={l} fonts={fonts} fileUrl={fileUrl} className={l.compact ? 'h-16' : 'h-14'} />
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2 p-3">
                <h3 className="mr-auto text-sm font-semibold">{l.name}</h3>
                {l.wordmark && <Chip className="border-gelb-500/50 text-gelb-text">{t('set.wordmark')}</Chip>}
                {drawn && (low ? <Chip className="border-warn-500/40 text-warn-500">{t('set.logoLow')}</Chip> : <Chip className="border-ok-500/40 text-ok-500">{t('set.logoOk')}</Chip>)}
              </div>
              {(l.min_width || l.clear_space || l.ground !== 'transparent') && (
                <p className="px-3 text-xs text-mist-500">
                  {[l.ground !== 'transparent' ? t('set.ground', { hex: l.ground }) : '', l.min_width ? t('set.minWidth', { value: l.min_width }) : '', l.clear_space ? t('set.clearSpaceIs', { value: l.clear_space }) : '']
                    .filter(Boolean)
                    .join(' · ')}
                </p>
              )}
              {downloads.length > 0 && (
                <div className="flex flex-wrap gap-2 p-3">
                  {downloads.map((id) => (
                    <a key={id} href={fileUrl(id) + (fileUrl(id).includes('?') ? '&' : '?') + 'download=true'} className="nc-btn nc-btn-ghost !px-2.5 !py-0.5 !text-xs">
                      <Download className="h-3.5 w-3.5" /> {(files[id]?.kind ?? t('set.file')).toUpperCase()}
                    </a>
                  ))}
                </div>
              )}
              {!downloads.length && <div className="h-3" />}
            </article>
          )
        })}
      </div>
    </div>
  )
}

const PICTURES = new Set(['svg', 'png', 'jpeg', 'webp', 'gif', 'avif'])

function Samples({ samples, fileUrl, files }: { samples: Sample[]; fileUrl: (id: string) => string; files: Record<string, FileInfo> }) {
  const { t } = useTranslation()
  if (!samples.length) return <p className="text-sm text-mist-500">{t('set.noSamples')}</p>
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {samples.map((s) => {
        const info = files[s.media]
        const picture = info && PICTURES.has(info.kind)
        return (
          <a key={s.media + s.name} href={fileUrl(s.media) + (picture ? '' : (fileUrl(s.media).includes('?') ? '&' : '?') + 'download=true')} target={picture ? '_blank' : undefined} rel="noreferrer" className="overflow-hidden rounded-2xl border border-ink-700 bg-ink-900 hover:border-ink-600">
            <div className="grid h-36 place-items-center bg-ink-800">
              {picture ? <img src={fileUrl(s.media)} alt="" className="h-full w-full object-cover" /> : <FileText className="h-10 w-10 text-mist-600" />}
            </div>
            <div className="p-3">
              <div className="text-sm font-semibold">{s.name}</div>
              <div className="text-xs text-mist-500">{info ? `${info.kind.toUpperCase()}${info.size ? ' · ' + Math.max(1, Math.round(info.size / 1024)) + ' KB' : ''}` : ''}</div>
            </div>
          </a>
        )
      })}
    </div>
  )
}

function DarkView({ set, colors, fileUrl }: { set: BrandSet; colors: ShownColor[]; fileUrl: (id: string) => string }) {
  const { t } = useTranslation()
  const scheme = schemeOf(set.dark, colors)
  if (!set.dark) return null
  return (
    <section className="mt-5 grid gap-4 rounded-2xl border border-ink-700 bg-ink-900 p-5 lg:grid-cols-[18rem_1fr]" data-testid="dark-view">
      <div>
        <h3 className="mb-3 flex items-center gap-2 font-semibold">
          <Moon className="h-4 w-4 text-accent-400" /> {t('dark.title')}
        </h3>
        <dl className="space-y-1.5 text-sm">
          {DARK_PARTS.map((part) => {
            const color = colors.find((c) => c.name.toLowerCase() === set.dark![part].toLowerCase())
            return (
              <div key={part} className="flex items-center gap-2">
                <span className="h-5 w-5 shrink-0 rounded border border-edge" style={{ background: color?.hex ?? 'transparent' }} aria-hidden />
                <dt className="w-36 shrink-0 text-mist-400">{t(`dark.part.${part}`)}</dt>
                <dd className="truncate text-mist-100">{set.dark![part]}</dd>
              </div>
            )
          })}
        </dl>
      </div>
      {scheme && <WebPreview colors={colors} head={fontStack(set.fonts[0], fileUrl)} body={fontStack(set.fonts[1] ?? set.fonts[0], fileUrl)} name="" logo={set.logos.find((l) => !l.compact)} logos={set.logos} fonts={set.fonts} fileUrl={fileUrl} scheme={scheme} compact />}
    </section>
  )
}

function Rules({ set, colors }: { set: BrandSet; colors: ShownColor[] }) {
  const { t } = useTranslation()
  const words = useRuleWords()
  const rules = set.rules
  if (!rules.length) return <p className="text-sm text-mist-500">{t('set.noRules')}</p>
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {(['do', 'dont'] as const).map((kind) => (
        <section key={kind} className="rounded-2xl border border-ink-700 bg-ink-900 p-5">
          <h3 className={'mb-3 flex items-center gap-2 font-semibold ' + (kind === 'do' ? 'text-ok-500' : 'text-bad-500')}>
            {kind === 'do' ? <Check className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
            {t(`set.rule.${kind}`)}
          </h3>
          <ul className="space-y-2 text-sm text-mist-200">
            {rules
              .filter((r) => r.kind === kind)
              .map((r, i) => (
                <li key={i} className="rounded-lg bg-ink-850 px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <RuleSwatch rule={r} colors={colors} />
                    <span className="min-w-0 flex-1 whitespace-pre-line">{words.sentence(r, set.logos)}</span>
                    <CheckedMark rule={r} />
                  </div>
                  {typeOf(r) !== 'text' && r.text && <p className="mt-1 text-xs text-mist-400">{r.text}</p>}
                </li>
              ))}
          </ul>
        </section>
      ))}
    </div>
  )
}
