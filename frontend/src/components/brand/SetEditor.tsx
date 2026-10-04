/** Editing a draft: colours, fonts, logos, sizes, rules and examples, with the checks and a sample page beside it. */
import { AlertTriangle, ArrowDown, ArrowUp, Ban, FileText, Palette, Plus, Shapes, Trash2, Type, Upload, Wand2 } from 'lucide-react'
import { useMemo, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, mediaApi, type FileInfo, type MediaInfo } from '../../api/client'
import { COLOR_ROLES, RULE_TOPICS, RULE_USES, SCALE_USES, type BrandColor, type BrandFont, type BrandLogo, type BrandSet, type ColorRole, type FontLicense, type Rule, type RuleKind, type RuleTopic, type RuleUse, type ScaleStep } from '../../lib/brand'
import { check, type Hint } from '../../lib/checks'
import { contrast, formatRatio, isHex, normalHex, scaleOf } from '../../lib/color'
import { errorText } from '../../lib/errors'
import { CATALOG, catalogEntry, findFont, fontStack } from '../../lib/fonts'
import { harmonies, neutralsFor, RATIOS, sameRule, startRules, typeScale, wordmarks, type Names } from '../../lib/generate'
import { TabRow, type Tab } from '../../pages/settings/ui'
import { HintList, useHintText } from './Checks'
import { CheckedMark, typeOf, useRuleWords, type RuleType } from './rules'
import { LogoView } from './LogoView'
import { WebPreview } from './WebPreview'

export type FileMap = Record<string, FileInfo>

type Ctx = { space: number; files: FileMap; addFile: (m: MediaInfo) => void; fileUrl: (id: string) => string }

const FONT_KINDS = new Set(['woff2', 'woff', 'otf', 'ttf'])
const PICTURE_KINDS = new Set(['svg', 'png', 'jpeg', 'webp', 'gif', 'avif'])

/** The words the generators need, in the language of the page. */
// eslint-disable-next-line react-refresh/only-export-components
export function useNames(): Names {
  const { t } = useTranslation()
  return {
    primary: t('gen.primary'),
    accent: t('gen.accent'),
    second: t('gen.second'),
    paper: t('gen.paper'),
    stone: t('gen.stone'),
    ink: t('gen.ink'),
    white: t('gen.white'),
    light: t('gen.light'),
    dark: t('gen.dark'),
  }
}

function useUpload(ctx: Ctx) {
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const send = async (file: File): Promise<MediaInfo | null> => {
    setBusy(true)
    setProblem(null)
    try {
      const made = await mediaApi.upload(ctx.space, file, file.name)
      ctx.addFile(made)
      return made
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
      return null
    } finally {
      setBusy(false)
    }
  }
  return { busy, problem, send }
}

function FileButton({ label, accept, onFiles, busy = false, multiple = false }: { label: string; accept?: string; onFiles: (files: File[]) => void; busy?: boolean; multiple?: boolean }) {
  const input = useRef<HTMLInputElement>(null)
  return (
    <label className={'nc-btn nc-btn-ghost cursor-pointer ' + (busy ? 'opacity-50' : '')}>
      <Upload className="h-4 w-4" /> {label}
      <input
        ref={input}
        type="file"
        accept={accept}
        multiple={multiple}
        className="sr-only"
        disabled={busy}
        onChange={(e) => {
          const files = [...(e.target.files ?? [])]
          if (files.length) onFiles(files)
          if (input.current) input.current.value = ''
        }}
      />
    </label>
  )
}

export function ColorField({ value, onChange, label, transparent = false }: { value: string; onChange: (v: string) => void; label: string; transparent?: boolean }) {
  return (
    <span className="flex items-center gap-1.5">
      <input type="color" aria-label={label} value={isHex(value) ? value : '#000000'} onChange={(e) => onChange(e.target.value.toUpperCase())} className="h-9 w-10 shrink-0 rounded-lg border border-ink-700 bg-ink-900" disabled={value === 'transparent'} />
      <input value={value} aria-label={label} onChange={(e) => onChange(e.target.value)} onBlur={(e) => onChange(transparent && e.target.value === 'transparent' ? 'transparent' : normalHex(e.target.value))} className={'h-9 w-24 rounded-lg border bg-ink-900 px-2 font-mono text-sm ' + (isHex(value) || (transparent && value === 'transparent') ? 'border-ink-700' : 'border-bad-500')} />
    </span>
  )
}

const field = 'h-9 rounded-lg border border-ink-700 bg-ink-900 px-2 text-sm text-mist-100'

function Row({ children, onRemove, onUp, onDown, label }: { children: ReactNode; onRemove: () => void; onUp?: () => void; onDown?: () => void; label: string }) {
  const { t } = useTranslation()
  return (
    <div className="rounded-xl border border-ink-700 bg-ink-850 p-2">
      <div className="flex flex-wrap items-start gap-2">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">{children}</div>
        <span className="ml-auto flex shrink-0 items-center">
          {onUp && (
            <button type="button" onClick={onUp} aria-label={t('editor.up', { name: label })} className="rounded-full p-1.5 text-mist-500 hover:text-mist-100">
              <ArrowUp className="h-3.5 w-3.5" />
            </button>
          )}
          {onDown && (
            <button type="button" onClick={onDown} aria-label={t('editor.down', { name: label })} className="rounded-full p-1.5 text-mist-500 hover:text-mist-100">
              <ArrowDown className="h-3.5 w-3.5" />
            </button>
          )}
          <button type="button" onClick={onRemove} aria-label={t('editor.remove', { name: label })} className="rounded-full p-1.5 text-mist-500 hover:text-bad-500">
            <Trash2 className="h-4 w-4" />
          </button>
        </span>
      </div>
    </div>
  )
}

function move<T>(list: T[], from: number, to: number): T[] {
  if (to < 0 || to >= list.length) return list
  const copy = [...list]
  const [item] = copy.splice(from, 1)
  copy.splice(to, 0, item)
  return copy
}

function uniqueName(base: string, taken: string[]): string {
  let name = base
  for (let n = 2; taken.some((x) => x.toLocaleLowerCase() === name.toLocaleLowerCase()); n++) name = `${base} ${n}`
  return name
}

// --- Colours ---------------------------------------------------------------------------------------------------------

export function ColorsEditor({ colors, onChange }: { colors: BrandColor[]; onChange: (c: BrandColor[]) => void }) {
  const { t, i18n } = useTranslation()
  const names = useNames()
  const [open, setOpen] = useState<number | null>(null)
  const primary = colors.find((c) => c.role === 'primary' && isHex(c.hex))?.hex
  const edit = (i: number, patch: Partial<BrandColor>) => onChange(colors.map((c, j) => (j === i ? { ...c, ...patch } : c)))
  const add = (c: BrandColor) => onChange([...colors, { ...c, name: uniqueName(c.name, colors.map((x) => x.name)) }])
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        {colors.map((c, i) => (
          <Row key={i} label={c.name} onRemove={() => onChange(colors.filter((_, j) => j !== i))} onUp={i ? () => onChange(move(colors, i, i - 1)) : undefined} onDown={i < colors.length - 1 ? () => onChange(move(colors, i, i + 1)) : undefined}>
            <ColorField value={c.hex} onChange={(hex) => edit(i, { hex })} label={t('editor.colorValue', { name: c.name })} />
            <input value={c.name} onChange={(e) => edit(i, { name: e.target.value })} aria-label={t('editor.name')} className={field + ' w-36'} />
            <select value={c.role} onChange={(e) => edit(i, { role: e.target.value as ColorRole })} aria-label={t('editor.role')} className={field}>
              {COLOR_ROLES.map((r) => (
                <option key={r} value={r}>
                  {t(`roles.color.${r}`)}
                </option>
              ))}
            </select>
            <input value={c.pantone ?? ''} onChange={(e) => edit(i, { pantone: e.target.value })} placeholder="Pantone" aria-label="Pantone" className={field + ' w-28'} />
            <input value={c.cmyk ?? ''} onChange={(e) => edit(i, { cmyk: e.target.value })} placeholder={t('editor.cmykGiven')} aria-label={t('editor.cmykGiven')} title={t('editor.cmykGiven')} className={field + ' w-40'} />
            <span className="text-xs text-mist-500">{isHex(c.hex) ? t('editor.onWhite', { ratio: formatRatio(contrast(c.hex, '#FFFFFF'), i18n.language) }) : t('editor.badHex')}</span>
            <button type="button" className="nc-btn nc-btn-ghost !px-2.5 !py-0.5 !text-xs" onClick={() => setOpen(open === i ? null : i)} aria-expanded={open === i}>
              {t('editor.scale')}
            </button>
            <input value={c.note ?? ''} onChange={(e) => edit(i, { note: e.target.value })} placeholder={t('editor.note')} aria-label={t('editor.note')} className={field + ' w-full'} />
            {open === i && isHex(c.hex) && <ScaleRow color={c} onAdd={add} />}
          </Row>
        ))}
        {!colors.length && <p className="text-sm text-mist-500">{t('editor.noColors')}</p>}
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="nc-btn nc-btn-ghost" onClick={() => add({ name: t('editor.newColor'), hex: '#888888', role: colors.length ? 'secondary' : 'primary' })}>
          <Plus className="h-4 w-4" /> {t('editor.addColor')}
        </button>
        {primary && (
          <button type="button" className="nc-btn nc-btn-ghost" onClick={() => onChange([...colors, ...neutralsFor(primary, names).map((n) => ({ ...n, name: uniqueName(n.name, colors.map((x) => x.name)) }))])}>
            <Wand2 className="h-4 w-4" /> {t('editor.neutrals')}
          </button>
        )}
      </div>
      {primary && (
        <section>
          <h4 className="text-sm font-semibold">{t('editor.fits')}</h4>
          <p className="text-xs text-mist-500">{t('editor.fitsText')}</p>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {harmonies(primary).map((h) => (
              <div key={h.key} className="rounded-xl border border-ink-700 p-3">
                <div className="flex items-center gap-2">
                  <span className="h-6 w-6 rounded-md border border-ink-600" style={{ background: primary }} />
                  {h.colors.map((c) => (
                    <button
                      key={c}
                      type="button"
                      title={t('editor.take', { hex: c })}
                      aria-label={t('editor.take', { hex: c })}
                      onClick={() => add({ name: h.key === 'complement' ? names.accent : names.second, hex: c, role: h.key === 'complement' ? 'accent' : 'secondary' })}
                      className="h-6 w-6 rounded-md border border-ink-600 hover:ring-2 hover:ring-accent-500"
                      style={{ background: c }}
                    />
                  ))}
                  <span className="ml-1 text-sm font-semibold">{t(`editor.harmony.${h.key}`)}</span>
                </div>
                <p className="mt-1 text-xs text-mist-500">{t(`editor.harmony.${h.key}Text`)}</p>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

/** 50 to 950 for one colour, with what each step can carry. */
function ScaleRow({ color, onAdd }: { color: BrandColor; onAdd: (c: BrandColor) => void }) {
  const { t } = useTranslation()
  return (
    <div className="mt-2 w-full border-t border-ink-700 pt-2">
      <div className="grid grid-cols-6 gap-1 sm:grid-cols-11">
        {scaleOf(color.hex).map(({ step, hex }) => {
          const w = contrast(hex, '#FFFFFF')
          const k = contrast(hex, '#14141A')
          return (
            <button key={step} type="button" title={t('editor.takeStep', { name: color.name, step })} onClick={() => onAdd({ name: `${color.name} ${step}`, hex, role: color.role })} className="overflow-hidden rounded-md border border-ink-700 text-left hover:ring-2 hover:ring-accent-500">
              <span className="block h-10" style={{ background: hex }} />
              <span className="block px-1 py-0.5 text-[10px] text-mist-400">{step}</span>
              <span className={'block px-1 pb-0.5 text-[9px] ' + (w >= 4.5 ? 'text-ok-500' : k >= 4.5 ? 'text-accent-400' : 'text-mist-600')}>{t(w >= 4.5 ? 'editor.stepText' : k >= 4.5 ? 'editor.stepGround' : 'editor.stepArea')}</span>
            </button>
          )
        })}
      </div>
      <p className="mt-1 text-[11px] text-mist-500">{t('editor.scaleNote')}</p>
    </div>
  )
}

// --- Fonts -----------------------------------------------------------------------------------------------------------

function FontsEditor({ fonts, onChange, ctx }: { fonts: BrandFont[]; onChange: (f: BrandFont[]) => void; ctx: Ctx }) {
  const { t } = useTranslation()
  const upload = useUpload(ctx)
  const [shipped, setShipped] = useState('')
  const edit = (i: number, patch: Partial<BrandFont>) => onChange(fonts.map((f, j) => (j === i ? { ...f, ...patch } : f)))
  const addFiles = async (files: File[], into?: number) => {
    const ids: string[] = []
    for (const file of files) {
      const made = await upload.send(file)
      if (made && FONT_KINDS.has(made.kind)) ids.push(made.id)
    }
    if (!ids.length) return
    if (into !== undefined) edit(into, { files: [...(fonts[into].files ?? []), ...ids] })
    else {
      const family = files[0].name.replace(/\.[^.]+$/, '').replace(/[-_](regular|bold|italic|light|medium|semibold|black|thin|variable|vf)\b/gi, '').replace(/[-_]+/g, ' ').trim() || 'Font'
      onChange([...fonts, { family, role: '', weights: [400], license: 'internal', files: ids, fallback: 'sans-serif', source: t('editor.uploaded') }])
    }
  }
  return (
    <div className="space-y-3">
      {fonts.map((f, i) => (
        <Row key={i} label={f.family} onRemove={() => onChange(fonts.filter((_, j) => j !== i))} onUp={i ? () => onChange(move(fonts, i, i - 1)) : undefined} onDown={i < fonts.length - 1 ? () => onChange(move(fonts, i, i + 1)) : undefined}>
          <div className="w-full text-2xl" style={{ fontFamily: fontStack(f, ctx.fileUrl), fontStyle: f.italic ? 'italic' : undefined }}>
            {f.family} <span className="text-base text-mist-500">Aa Bb Cc 123</span>
          </div>
          <input value={f.family} onChange={(e) => edit(i, { family: e.target.value.replace(/["'\\;{}<>]/g, '') })} aria-label={t('editor.family')} className={field + ' w-44'} disabled={!!f.catalog} />
          <input value={f.role} onChange={(e) => edit(i, { role: e.target.value })} placeholder={t('editor.fontRole')} aria-label={t('editor.fontRole')} className={field + ' w-44'} />
          <select value={f.license} onChange={(e) => edit(i, { license: e.target.value as FontLicense })} aria-label={t('editor.license')} className={field} disabled={!!f.catalog}>
            {(['free', 'internal', 'system'] as FontLicense[]).map((l) => (
              <option key={l} value={l}>
                {t(`set.license.${l}`)}
              </option>
            ))}
          </select>
          <input
            value={f.weights.join(', ')}
            onChange={(e) => {
              const weights = e.target.value.split(/[ ,;]+/).map(Number).filter((n) => Number.isInteger(n) && n >= 100 && n <= 1000)
              if (weights.length) edit(i, { weights })
            }}
            aria-label={t('editor.weights')}
            title={t('editor.weights')}
            className={field + ' w-32'}
          />
          <label className="flex items-center gap-1.5 text-xs text-mist-400">
            <input type="checkbox" checked={!!f.italic} onChange={(e) => edit(i, { italic: e.target.checked })} className="accent-accent-500" />
            {t('editor.italic')}
          </label>
          <select value={f.fallback ?? 'sans-serif'} onChange={(e) => edit(i, { fallback: e.target.value as BrandFont['fallback'] })} aria-label={t('editor.fallback')} className={field}>
            {['sans-serif', 'serif', 'monospace', 'cursive'].map((fb) => (
              <option key={fb}>{fb}</option>
            ))}
          </select>
          <input value={f.license_note ?? ''} onChange={(e) => edit(i, { license_note: e.target.value })} placeholder={t('editor.licenseNote')} aria-label={t('editor.licenseNote')} className={field + ' min-w-0 flex-1'} />
          {!f.catalog && (
            <div className="flex w-full flex-wrap items-center gap-2 text-xs text-mist-500">
              {(f.files ?? []).map((id) => (
                <span key={id} className="inline-flex items-center gap-1 rounded-full border border-ink-700 px-2 py-0.5">
                  {ctx.files[id]?.name ?? id}
                  <button type="button" aria-label={t('editor.removeFile')} onClick={() => edit(i, { files: (f.files ?? []).filter((x) => x !== id) })} className="text-mist-500 hover:text-bad-500">
                    ×
                  </button>
                </span>
              ))}
              <FileButton label={t('editor.addFontFiles')} accept=".woff2,.woff,.otf,.ttf" multiple busy={upload.busy} onFiles={(files) => void addFiles(files, i)} />
            </div>
          )}
        </Row>
      ))}
      {!fonts.length && <p className="text-sm text-mist-500">{t('editor.noFonts')}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <select value={shipped} onChange={(e) => setShipped(e.target.value)} aria-label={t('editor.fromCatalog')} className={field}>
          <option value="">{t('editor.fromCatalog')}</option>
          {CATALOG.map((c) => (
            <option key={c.id} value={c.id}>
              {c.family}
            </option>
          ))}
        </select>
        <button type="button" className="nc-btn nc-btn-ghost" disabled={!shipped} onClick={() => (onChange([...fonts, catalogEntry(shipped, fonts.length ? t('editor.roleBody') : t('editor.roleHead'))]), setShipped(''))}>
          <Plus className="h-4 w-4" /> {t('editor.addShipped')}
        </button>
        <FileButton label={t('editor.uploadFont')} accept=".woff2,.woff,.otf,.ttf" multiple busy={upload.busy} onFiles={(files) => void addFiles(files)} />
        <button type="button" className="nc-btn nc-btn-ghost" onClick={() => onChange([...fonts, { family: t('editor.newFont'), role: fonts.length ? t('editor.roleBody') : t('editor.roleHead'), weights: [400], license: 'system', fallback: 'sans-serif' }])}>
          <Plus className="h-4 w-4" /> {t('editor.fontByName')}
        </button>
      </div>
      <p className="text-xs text-mist-500">{t('editor.fontLicenseNote')}</p>
      {upload.problem && <p role="alert" className="text-sm text-bad-500">{errorText(upload.problem)}</p>}
    </div>
  )
}

// --- Logos -----------------------------------------------------------------------------------------------------------

function GroundSelect({ value, colors, onChange, label }: { value: string; colors: BrandColor[]; onChange: (v: string) => void; label: string }) {
  const { t } = useTranslation()
  return (
    <span className="flex items-center gap-1.5">
      <select value={colors.some((c) => c.hex === value) || value === 'transparent' ? value : ''} onChange={(e) => e.target.value && onChange(e.target.value)} aria-label={label} className={field + ' max-w-36'}>
        <option value="">{t('editor.ownValue')}</option>
        <option value="transparent">{t('editor.transparent')}</option>
        {colors.map((c) => (
          <option key={c.name} value={c.hex}>
            {c.name}
          </option>
        ))}
      </select>
      {value !== 'transparent' && <ColorField value={value} onChange={onChange} label={label} />}
    </span>
  )
}

function LogosEditor({ logos, colors, fonts, name, onChange, ctx }: { logos: BrandLogo[]; colors: BrandColor[]; fonts: BrandFont[]; name: string; onChange: (l: BrandLogo[]) => void; ctx: Ctx }) {
  const { t } = useTranslation()
  const upload = useUpload(ctx)
  const edit = (i: number, patch: Partial<BrandLogo>) => onChange(logos.map((l, j) => (j === i ? { ...l, ...patch } : l)))
  const newId = (base: string) => {
    let id = base
    for (let n = 2; logos.some((l) => l.id === id); n++) id = `${base}-${n}`
    return id
  }
  const addPictures = async (files: File[]) => {
    const made: BrandLogo[] = []
    for (const file of files) {
      const m = await upload.send(file)
      if (m && PICTURE_KINDS.has(m.kind))
        made.push({ id: newId('logo-' + (logos.length + made.length + 1)), name: file.name.replace(/\.[^.]+$/, ''), media: m.id, fg: '#000000', accent: '#000000', ground: '#FFFFFF', files: [] })
    }
    if (made.length) onChange([...logos, ...made])
  }
  const head = fonts[0]?.family ?? 'Inter'
  return (
    <div className="space-y-3">
      {logos.map((l, i) => (
        <Row key={l.id} label={l.name} onRemove={() => onChange(logos.filter((_, j) => j !== i))} onUp={i ? () => onChange(move(logos, i, i - 1)) : undefined} onDown={i < logos.length - 1 ? () => onChange(move(logos, i, i + 1)) : undefined}>
          {/* The logo itself, on the ground chosen for it: a row of fields alone did not show it (04.10.2026). */}
          <span
            className={'grid h-16 w-32 shrink-0 place-items-center overflow-hidden rounded-lg border border-ink-700 p-2 ' + (l.ground === 'transparent' ? 'nb-checker' : '')}
            style={l.ground === 'transparent' ? undefined : { background: l.ground }}
            data-testid="logo-thumb"
          >
            <LogoView logo={l} fonts={fonts} fileUrl={ctx.fileUrl} className={l.compact ? 'h-12' : 'h-10'} />
          </span>
          <input value={l.name} onChange={(e) => edit(i, { name: e.target.value })} aria-label={t('editor.name')} className={field + ' w-40'} />
          {l.wordmark ? (
            <>
              <input value={l.wordmark.text} onChange={(e) => edit(i, { wordmark: { ...l.wordmark!, text: e.target.value } })} aria-label={t('editor.wordmarkText')} className={field + ' w-40'} />
              <select value={l.wordmark.font} onChange={(e) => edit(i, { wordmark: { ...l.wordmark!, font: e.target.value } })} aria-label={t('editor.wordmarkFont')} className={field}>
                {[...new Set([...fonts.map((f) => f.family), ...CATALOG.map((c) => c.family)])].map((f) => (
                  <option key={f}>{f}</option>
                ))}
              </select>
              <span className="text-xs text-mist-500">{t('editor.textColor')}</span>
              <ColorField value={l.fg} onChange={(fg) => edit(i, { fg })} label={t('editor.textColor')} />
              <span className="text-xs text-mist-500">{t('editor.markColor')}</span>
              <ColorField value={l.accent} onChange={(accent) => edit(i, { accent })} label={t('editor.markColor')} />
              <label className="flex items-center gap-1.5 text-xs text-mist-400">
                <input type="checkbox" checked={!!l.compact} onChange={(e) => edit(i, { compact: e.target.checked })} className="accent-accent-500" />
                {t('editor.compact')}
              </label>
            </>
          ) : (
            <span className="text-xs text-mist-500">{ctx.files[l.media ?? '']?.name ?? l.media}</span>
          )}
          <span className="text-xs text-mist-500">{t('editor.ground')}</span>
          <GroundSelect value={l.ground} colors={colors} onChange={(ground) => edit(i, { ground })} label={t('editor.ground')} />
          <input value={l.min_width ?? ''} onChange={(e) => edit(i, { min_width: e.target.value })} placeholder={t('editor.minWidth')} aria-label={t('editor.minWidth')} className={field + ' w-36'} />
          <input value={l.clear_space ?? ''} onChange={(e) => edit(i, { clear_space: e.target.value })} placeholder={t('editor.clearSpace')} aria-label={t('editor.clearSpace')} className={field + ' w-44'} />
          <div className="flex w-full flex-wrap items-center gap-2 text-xs text-mist-500">
            {(l.files ?? []).map((id) => (
              <span key={id} className="inline-flex items-center gap-1 rounded-full border border-ink-700 px-2 py-0.5">
                {ctx.files[id]?.name ?? id}
                <button type="button" aria-label={t('editor.removeFile')} onClick={() => edit(i, { files: (l.files ?? []).filter((x) => x !== id) })} className="hover:text-bad-500">
                  ×
                </button>
              </span>
            ))}
            <FileButton
              label={t('editor.moreFormats')}
              multiple
              busy={upload.busy}
              onFiles={(files) =>
                void (async () => {
                  const ids: string[] = []
                  for (const f of files) {
                    const m = await upload.send(f)
                    if (m) ids.push(m.id)
                  }
                  if (ids.length) edit(i, { files: [...(l.files ?? []), ...ids] })
                })()
              }
            />
          </div>
        </Row>
      ))}
      {!logos.length && <p className="text-sm text-mist-500">{t('editor.noLogos')}</p>}
      <div className="flex flex-wrap gap-2">
        <FileButton label={t('editor.uploadLogo')} accept=".svg,.png,.jpg,.jpeg,.webp,.gif,.avif,image/*" multiple busy={upload.busy} onFiles={(files) => void addPictures(files)} />
        <button
          type="button"
          className="nc-btn nc-btn-ghost"
          onClick={() => onChange([...logos, ...wordmarks(name, colors, head, { positive: t('gen.wordPositive'), negative: t('gen.wordNegative'), monogram: t('gen.monogram') }).map((w) => ({ ...w, id: newId(w.id) }))])}
        >
          <Wand2 className="h-4 w-4" /> {t('editor.addWordmarks')}
        </button>
      </div>
      <p className="text-xs text-mist-500">{t('editor.logoNote')}</p>
      {upload.problem && <p role="alert" className="text-sm text-bad-500">{errorText(upload.problem)}</p>}
    </div>
  )
}

// --- Type scale ------------------------------------------------------------------------------------------------------

function ScaleEditor({ scale, fonts, onChange }: { scale: ScaleStep[]; fonts: BrandFont[]; onChange: (s: ScaleStep[]) => void }) {
  const { t } = useTranslation()
  const families = [...new Set([...fonts.map((f) => f.family), ...CATALOG.map((c) => c.family)])]
  const [base, setBase] = useState(scale.find((s) => s.use === 'body')?.size ?? 17)
  const [ratio, setRatio] = useState(1.25)
  const [head, setHead] = useState(fonts[0]?.family ?? 'Inter')
  const [body, setBody] = useState(fonts[1]?.family ?? fonts[0]?.family ?? 'Inter')
  const edit = (i: number, patch: Partial<ScaleStep>) => onChange(scale.map((s, j) => (j === i ? { ...s, ...patch } : s)))
  const names = { h1: t('gen.h1'), h2: t('gen.h2'), h3: t('gen.h3'), lead: t('gen.lead'), body: t('gen.body'), small: t('gen.small') }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2 rounded-xl border border-ink-700 p-3">
        <label className="text-xs text-mist-400">
          {t('editor.base', { size: base })}
          <input type="range" min={14} max={21} value={base} onChange={(e) => setBase(Number(e.target.value))} className="mt-2 block w-40 accent-accent-500" />
        </label>
        <label className="text-xs text-mist-400">
          {t('editor.ratio')}
          <select value={ratio} onChange={(e) => setRatio(Number(e.target.value))} className={field + ' mt-1 block'}>
            {RATIOS.map((r) => (
              <option key={r} value={r}>
                {t(`editor.ratios.${String(r).replace('.', '_')}`)}
              </option>
            ))}
          </select>
        </label>
        {(
          [
            [head, setHead, 'editor.headFont'],
            [body, setBody, 'editor.bodyFont'],
          ] as const
        ).map(([value, set, label]) => (
          <label key={label} className="text-xs text-mist-400">
            {t(label)}
            <select value={value} onChange={(e) => set(e.target.value)} className={field + ' mt-1 block'}>
              {families.map((f) => (
                <option key={f}>{f}</option>
              ))}
            </select>
          </label>
        ))}
        <button type="button" className="nc-btn nc-btn-ghost" onClick={() => onChange(typeScale(base, ratio, head, body, names))}>
          <Wand2 className="h-4 w-4" /> {t('editor.computeScale')}
        </button>
        {base < 16 && <p className="w-full text-xs text-warn-500">{t('checks.body_small.text', { size: base })}</p>}
      </div>
      <div className="space-y-2">
        {scale.map((s, i) => (
          <Row key={i} label={s.name} onRemove={() => onChange(scale.filter((_, j) => j !== i))} onUp={i ? () => onChange(move(scale, i, i - 1)) : undefined} onDown={i < scale.length - 1 ? () => onChange(move(scale, i, i + 1)) : undefined}>
            <input value={s.name} onChange={(e) => edit(i, { name: e.target.value })} aria-label={t('editor.name')} className={field + ' w-36'} />
            <select value={s.use ?? ''} onChange={(e) => edit(i, { use: e.target.value as ScaleStep['use'] })} aria-label={t('editor.use')} className={field}>
              {SCALE_USES.map((u) => (
                <option key={u} value={u}>
                  {u ? t(`set.use.${u}`) : t('editor.noUse')}
                </option>
              ))}
            </select>
            <input type="number" min={6} max={400} value={s.size} onChange={(e) => edit(i, { size: Number(e.target.value) })} aria-label={t('editor.size')} className={field + ' w-20'} />
            <span className="text-xs text-mist-500">px</span>
            <input type="number" min={100} max={1000} step={100} value={s.weight} onChange={(e) => edit(i, { weight: Number(e.target.value) })} aria-label={t('editor.weight')} className={field + ' w-20'} />
            <select value={s.font} onChange={(e) => edit(i, { font: e.target.value })} aria-label={t('editor.font')} className={field}>
              {[...new Set([s.font, ...families])].map((f) => (
                <option key={f}>{f}</option>
              ))}
            </select>
            <input type="number" min={0.5} max={4} step={0.05} value={s.line_height} onChange={(e) => edit(i, { line_height: Number(e.target.value) })} aria-label={t('editor.lineHeight')} className={field + ' w-20'} />
            <span className="w-full truncate" style={{ fontFamily: fontStack(findFont(fonts, s.font), () => ''), fontSize: Math.min(s.size, 44), fontWeight: s.weight }}>
              {t('set.scaleSample')}
            </span>
          </Row>
        ))}
      </div>
      <button type="button" className="nc-btn nc-btn-ghost" onClick={() => onChange([...scale, { name: t('editor.newStep'), use: '', size: 16, weight: 400, font: body, line_height: 1.5 }])}>
        <Plus className="h-4 w-4" /> {t('editor.addStep')}
      </button>
    </div>
  )
}

// --- Rules and examples ----------------------------------------------------------------------------------------------

function RulesEditor({ value, hints, onChange }: { value: BrandSet; hints: Hint[]; onChange: (r: Rule[]) => void }) {
  const { t } = useTranslation()
  const words = useRuleWords()
  const hintWords = useHintText()
  const rules = value.rules
  const colors = value.colors.filter((c) => isHex(c.hex))
  const names = colors.map((c) => c.name)
  const families = value.fonts.map((f) => f.family)
  const replace = (i: number, rule: Rule) => onChange(rules.map((r, j) => (j === i ? rule : r)))
  const options = (current: string, list: string[]) => [...new Set([current, ...list])].filter((x) => x !== '' || current === '')
  const suggest = () => {
    const made = startRules(colors, { clear: t('gen.clear'), distort: t('gen.distort') })
    onChange([...rules, ...made.filter((m) => !rules.some((r) => sameRule(r, m)))])
  }
  const firstLogo = value.logos[0]
  const groundOf = (logo: BrandLogo) => colors.find((c) => c.hex.toUpperCase() === (logo.ground ?? '').toUpperCase())?.name ?? names[0]
  const fresh: Record<RuleType, Rule | null> = {
    pair: names.length >= 2 ? { type: 'pair', kind: 'do', fg: names[names.length - 1], bg: names[0], size: 'text' } : null,
    logo: firstLogo && names.length ? { type: 'logo', kind: 'do', logo: firstLogo.id, grounds: [groundOf(firstLogo)] } : null,
    font: families.length ? { type: 'font', kind: 'do', font: families[families.length > 1 ? 1 : 0], use: 'body', min_size: 0 } : null,
    text: { type: 'text', kind: 'do', topic: '', text: '' },
  }
  return (
    <div className="space-y-3">
      <p className="text-sm text-mist-400">{t('rules.intro')}</p>
      {rules.map((r, i) => {
        const mine = hints.filter((h) => h.rule === i)
        const label = words.sentence(r, value.logos).slice(0, 40)
        return (
          <Row key={i} label={label} onRemove={() => onChange(rules.filter((_, j) => j !== i))} onUp={i ? () => onChange(move(rules, i, i - 1)) : undefined} onDown={i < rules.length - 1 ? () => onChange(move(rules, i, i + 1)) : undefined}>
            <span className="text-xs font-semibold tracking-wide text-mist-500 uppercase">{t(`rules.type.${typeOf(r)}`)}</span>
            <select value={r.kind} onChange={(e) => replace(i, { ...r, kind: e.target.value as RuleKind })} aria-label={t('editor.ruleKind')} className={field}>
              <option value="do">{t(`rules.kind.${typeOf(r)}.do`)}</option>
              <option value="dont">{t(`rules.kind.${typeOf(r)}.dont`)}</option>
            </select>
            {r.type === 'pair' && (
              <>
                <span className="text-sm text-mist-400">{t('rules.text')}</span>
                <select value={r.fg} onChange={(e) => replace(i, { ...r, fg: e.target.value })} aria-label={t('rules.text')} className={field}>
                  {options(r.fg, names).map((n) => (
                    <option key={n}>{n}</option>
                  ))}
                </select>
                <span className="text-sm text-mist-400">{t('rules.on')}</span>
                <select value={r.bg} onChange={(e) => replace(i, { ...r, bg: e.target.value })} aria-label={t('editor.ground')} className={field}>
                  {options(r.bg, names).map((n) => (
                    <option key={n}>{n}</option>
                  ))}
                </select>
                {r.kind === 'do' && (
                  <select value={r.size ?? 'text'} onChange={(e) => replace(i, { ...r, size: e.target.value as 'text' | 'large' })} aria-label={t('editor.size')} className={field}>
                    <option value="text">{t('rules.size.text')}</option>
                    <option value="large">{t('rules.size.large')}</option>
                  </select>
                )}
                <PairRatio rule={r} colors={colors} />
              </>
            )}
            {r.type === 'logo' && (
              <>
                <select value={r.logo} onChange={(e) => replace(i, { ...r, logo: e.target.value })} aria-label={t('rules.type.logo')} className={field}>
                  {!value.logos.some((l) => l.id === r.logo) && <option value={r.logo}>{r.logo}</option>}
                  {value.logos.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.name}
                    </option>
                  ))}
                </select>
                <div className="flex w-full flex-wrap gap-1.5" role="group" aria-label={t('rules.grounds')}>
                  {options('', [...r.grounds, ...names]).filter(Boolean).map((n) => {
                    const on = r.grounds.includes(n)
                    const c = colors.find((x) => x.name === n)
                    return (
                      <button
                        key={n}
                        type="button"
                        aria-pressed={on}
                        onClick={() => {
                          const grounds = on ? r.grounds.filter((g) => g !== n) : [...r.grounds, n]
                          if (grounds.length) replace(i, { ...r, grounds })
                        }}
                        className={'flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ' + (on ? 'border-accent-400 bg-accent-400/12 text-mist-100' : 'border-ink-700 text-mist-400 hover:text-mist-100')}
                      >
                        <span className="h-3.5 w-3.5 rounded-full border border-edge" style={{ background: c?.hex ?? 'transparent' }} aria-hidden />
                        {n}
                      </button>
                    )
                  })}
                </div>
              </>
            )}
            {r.type === 'font' && (
              <>
                <select value={r.font} onChange={(e) => replace(i, { ...r, font: e.target.value })} aria-label={t('editor.font')} className={field}>
                  {options(r.font, families).map((f) => (
                    <option key={f}>{f}</option>
                  ))}
                </select>
                <span className="text-sm text-mist-400">{t('rules.for')}</span>
                <select value={r.use ?? ''} onChange={(e) => replace(i, { ...r, use: e.target.value as RuleUse })} aria-label={t('editor.use')} className={field}>
                  {RULE_USES.map((u) => (
                    <option key={u} value={u}>
                      {words.labelOfUse(u)}
                    </option>
                  ))}
                </select>
                {r.kind === 'do' && (
                  <>
                    <span className="text-sm text-mist-400">{t('rules.atLeast')}</span>
                    <input type="number" min={0} max={400} value={r.min_size || ''} placeholder="0" onChange={(e) => replace(i, { ...r, min_size: Number(e.target.value) || 0 })} aria-label={t('rules.atLeast')} className={field + ' w-20'} />
                    <span className="text-xs text-mist-500">px</span>
                  </>
                )}
              </>
            )}
            {typeOf(r) === 'text' ? (
              <>
                <select value={(r.type === 'text' || !r.type ? r.topic : '') || ''} onChange={(e) => replace(i, { ...(r as Extract<Rule, { kind: RuleKind; text: string }>), type: 'text', topic: e.target.value as RuleTopic })} aria-label={t('rules.topicLabel')} className={field}>
                  {RULE_TOPICS.map((topic) => (
                    <option key={topic} value={topic}>
                      {t(`rules.topic.${topic || 'none'}`)}
                    </option>
                  ))}
                </select>
                <CheckedMark rule={r} />
                <textarea value={r.text} onChange={(e) => replace(i, { ...r, text: e.target.value })} rows={2} aria-label={t('editor.ruleText')} className="w-full min-w-0 rounded-lg border border-ink-700 bg-ink-900 px-2 py-1.5 text-sm" />
              </>
            ) : (
              <input value={r.text ?? ''} onChange={(e) => replace(i, { ...r, text: e.target.value })} placeholder={t('rules.note')} aria-label={t('rules.note')} maxLength={400} className={field + ' w-full'} />
            )}
            {mine.length > 0 && (
              <ul className="w-full space-y-1">
                {mine.map((h, j) => (
                  <li key={j} className={'flex items-center gap-1.5 text-xs ' + (h.level === 'bad' ? 'text-bad-500' : 'text-warn-500')}>
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden /> {hintWords(h).title}
                  </li>
                ))}
              </ul>
            )}
          </Row>
        )
      })}
      {!rules.length && <p className="text-sm text-mist-500">{t('editor.noRules')}</p>}
      <div className="flex flex-wrap gap-2">
        {(['pair', 'logo', 'font', 'text'] as const).map((type) => {
          const made = fresh[type]
          return (
            <button key={type} type="button" className="nc-btn nc-btn-ghost" disabled={!made} onClick={() => made && onChange([...rules, made])}>
              <Plus className="h-4 w-4" /> {t(`rules.add.${type}`)}
            </button>
          )
        })}
        <button type="button" className="nc-btn nc-btn-ghost" onClick={suggest}>
          <Wand2 className="h-4 w-4" /> {t('editor.suggestRules')}
        </button>
      </div>
    </div>
  )
}

function PairRatio({ rule, colors }: { rule: Extract<Rule, { type: 'pair' }>; colors: BrandColor[] }) {
  const { i18n } = useTranslation()
  const fg = colors.find((c) => c.name === rule.fg)
  const bg = colors.find((c) => c.name === rule.bg)
  if (!fg || !bg) return null
  return (
    <span className="flex items-center gap-1.5 text-xs text-mist-400">
      <span className="rounded-md border border-edge px-2 py-0.5 text-sm font-semibold" style={{ color: fg.hex, background: bg.hex }} aria-hidden>
        Aa
      </span>
      {formatRatio(contrast(fg.hex, bg.hex), i18n.language)}
    </span>
  )
}

/** A colour or font renamed in the editor: the rules pointing at it follow. */
function renamed(before: string[], after: string[]): Map<string, string> {
  if (before.length !== after.length) return new Map()
  return new Map(before.map((b, i) => [b, after[i]] as const).filter(([b, a]) => b !== a))
}

function followNames(rules: Rule[], colorNames: Map<string, string>, fontNames: Map<string, string>): Rule[] {
  if (!colorNames.size && !fontNames.size) return rules
  const color = (name: string) => colorNames.get(name) ?? name
  return rules.map((r) => {
    if (r.type === 'pair') return { ...r, fg: color(r.fg), bg: color(r.bg) }
    if (r.type === 'logo') return { ...r, grounds: r.grounds.map(color) }
    if (r.type === 'font') return { ...r, font: fontNames.get(r.font) ?? r.font }
    return r
  })
}

function SamplesEditor({ samples, onChange, ctx }: { samples: BrandSet['samples']; onChange: (s: BrandSet['samples']) => void; ctx: Ctx }) {
  const { t } = useTranslation()
  const upload = useUpload(ctx)
  return (
    <div className="space-y-3">
      {samples.map((s, i) => (
        <Row key={s.media + i} label={s.name} onRemove={() => onChange(samples.filter((_, j) => j !== i))} onUp={i ? () => onChange(move(samples, i, i - 1)) : undefined} onDown={i < samples.length - 1 ? () => onChange(move(samples, i, i + 1)) : undefined}>
          <input value={s.name} onChange={(e) => onChange(samples.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} aria-label={t('editor.name')} className={field + ' w-64'} />
          <span className="text-xs text-mist-500">{ctx.files[s.media]?.name ?? s.media}</span>
        </Row>
      ))}
      {!samples.length && <p className="text-sm text-mist-500">{t('editor.noSamples')}</p>}
      <FileButton
        label={t('editor.uploadSamples')}
        multiple
        busy={upload.busy}
        onFiles={(files) =>
          void (async () => {
            const added: BrandSet['samples'] = []
            for (const f of files) {
              const m = await upload.send(f)
              if (m) added.push({ name: f.name.replace(/\.[^.]+$/, ''), media: m.id })
            }
            if (added.length) onChange([...samples, ...added])
          })()
        }
      />
      {upload.problem && <p role="alert" className="text-sm text-bad-500">{errorText(upload.problem)}</p>}
    </div>
  )
}

// --- The editor ------------------------------------------------------------------------------------------------------

export function SetEditor({ value, onChange, name, ctx }: { value: BrandSet; onChange: (s: BrandSet) => void; name: string; ctx: Ctx }) {
  const { t } = useTranslation()
  const [tab, setTab] = useState('colors')
  const set = (patch: Partial<BrandSet>) => onChange({ ...value, ...patch })
  const hints = useMemo(() => check(value), [value])
  const serious = hints.filter((h) => h.level !== 'info')
  const tabs: Tab<string>[] = [
    { value: 'colors', label: t('set.tabs.colors', { count: value.colors.length }), icon: Palette },
    { value: 'fonts', label: t('set.tabs.fonts', { count: value.fonts.length }), icon: Type },
    { value: 'logos', label: t('set.tabs.logos', { count: value.logos.length }), icon: Shapes },
    { value: 'scale', label: t('editor.tabScale'), icon: Type },
    { value: 'rules', label: t('set.tabs.rules'), icon: Ban },
    { value: 'samples', label: t('set.tabs.samples'), icon: FileText },
  ]
  const valid = value.colors.filter((c) => isHex(c.hex))
  const head = value.fonts[0]
  const body = value.fonts[1] ?? value.fonts[0]
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="min-w-0 space-y-4">
        <TabRow tabs={tabs} active={tab} onChange={setTab} label={t('set.tabsLabel')} />
        {tab === 'colors' && <ColorsEditor colors={value.colors} onChange={(colors) => set({ colors, rules: followNames(value.rules, renamed(value.colors.map((c) => c.name), colors.map((c) => c.name)), new Map()) })} />}
        {tab === 'fonts' && <FontsEditor fonts={value.fonts} onChange={(fonts) => set({ fonts, rules: followNames(value.rules, new Map(), renamed(value.fonts.map((f) => f.family), fonts.map((f) => f.family))) })} ctx={ctx} />}
        {tab === 'logos' && <LogosEditor logos={value.logos} colors={valid} fonts={value.fonts} name={name} onChange={(logos) => set({ logos })} ctx={ctx} />}
        {tab === 'scale' && <ScaleEditor scale={value.scale} fonts={value.fonts} onChange={(scale) => set({ scale })} />}
        {tab === 'rules' && <RulesEditor value={value} hints={hints} onChange={(rules) => set({ rules })} />}
        {tab === 'samples' && <SamplesEditor samples={value.samples} onChange={(samples) => set({ samples })} ctx={ctx} />}
      </div>
      <aside className="space-y-3 xl:sticky xl:top-4 xl:self-start" aria-label={t('editor.live')}>
        {valid.length > 0 && <WebPreview colors={valid} head={fontStack(head, ctx.fileUrl)} body={fontStack(body, ctx.fileUrl)} name={name} logo={value.logos.find((l) => !l.compact)} fonts={value.fonts} fileUrl={ctx.fileUrl} compact />}
        <section className="rounded-2xl border border-ink-700 bg-ink-900 p-3">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold">{t('editor.live')}</h3>
            <span className={'rounded-full border px-2 py-0.5 text-[11px] ' + (serious.length ? 'border-warn-500/40 text-warn-500' : 'border-ok-500/40 text-ok-500')}>{serious.length ? t('editor.hints', { count: serious.length }) : t('editor.allGood')}</span>
          </div>
          <div className="nc-scroll max-h-96 overflow-y-auto">
            <HintList hints={serious} />
          </div>
        </section>
      </aside>
    </div>
  )
}
