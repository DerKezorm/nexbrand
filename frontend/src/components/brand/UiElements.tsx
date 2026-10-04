/** UI elements drawn from a design set: buttons, a field, a switch, a card, badges, light and dark. Nothing to upload:
 * they change with the CI, and show a developer what to build. */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { pickColors, schemeOf, type BrandSet } from '../../lib/brand'
import { luminance, textOn } from '../../lib/color'
import { fontStack } from '../../lib/fonts'
import { LogoView } from './LogoView'
import { SchemeSwitch } from './SchemeSwitch'

export function UiElements({ set, name, fileUrl }: { set: BrandSet; name: string; fileUrl: (id: string) => string }) {
  const { t } = useTranslation()
  const scheme = schemeOf(set.dark, set.colors)
  const [dark, setDark] = useState(false)
  if (!set.colors.length) return <p className="text-sm text-mist-500">{t('ui.noColors')}</p>
  const picked = pickColors(set.colors, luminance)
  const g = dark && scheme
    ? { ground: scheme.ground, surface: scheme.surface, text: scheme.text, muted: scheme.muted, line: `${scheme.text}26`, primary: scheme.primary, on: scheme.on_primary }
    : { ground: picked.light, surface: '#FFFFFF', text: picked.dark, muted: `${picked.dark}B3`, line: `${picked.dark}22`, primary: picked.primary, on: textOn(picked.primary) }
  const head = fontStack(set.fonts[0], fileUrl)
  const body = fontStack(set.fonts[1] ?? set.fonts[0], fileUrl)
  const logo = dark ? (set.logos.find((l) => l.ground !== 'transparent' && luminance(l.ground) < 0.2) ?? set.logos.find((l) => l.compact)) : set.logos.find((l) => l.compact) ?? set.logos[0]
  const label = (text: string) => (
    <div className="text-[11px] font-semibold tracking-wider uppercase" style={{ color: g.muted }}>
      {text}
    </div>
  )
  return (
    <div className="space-y-3" data-testid="ui-elements">
      <div className="flex flex-wrap items-center gap-2">
        <p className="mr-auto max-w-2xl text-sm text-mist-400">{t('ui.text')}</p>
        {scheme && <SchemeSwitch dark={dark} onChange={setDark} />}
      </div>
      <div className="grid gap-6 rounded-2xl border border-ink-700 p-6 md:grid-cols-2" style={{ background: g.ground, color: g.text, fontFamily: body }} data-scheme={dark && scheme ? 'dark' : 'light'}>
        <div className="space-y-4">
          {label(t('ui.buttons'))}
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="rounded-lg px-4 py-2 font-semibold" style={{ background: g.primary, color: g.on }}>
              {t('ui.save')}
            </span>
            <span className="rounded-lg border px-4 py-2 font-semibold" style={{ borderColor: g.line }}>
              {t('ui.cancel')}
            </span>
            <span className="px-1 py-2 font-semibold underline" style={{ color: g.primary }}>
              {t('ui.link')}
            </span>
          </div>
          {label(t('ui.fields'))}
          <div className="space-y-2 text-sm">
            <div className="rounded-lg border px-3 py-2" style={{ borderColor: g.line, background: g.surface, color: g.muted }}>
              {t('ui.search')}
            </div>
            <div className="flex items-center gap-2">
              <span className="relative h-5 w-9 shrink-0 rounded-full" style={{ background: g.primary }}>
                <span className="absolute top-0.5 right-0.5 h-4 w-4 rounded-full" style={{ background: g.on }} />
              </span>
              {t('ui.switch')}
            </div>
          </div>
        </div>
        <div className="space-y-4">
          {label(t('ui.card'))}
          <div className="space-y-2 rounded-xl border p-4" style={{ borderColor: g.line, background: g.surface }}>
            <div className="flex items-center gap-2">
              {logo && <LogoView logo={logo} fonts={set.fonts} fileUrl={fileUrl} className="h-7 max-w-[8rem]" />}
              <b style={{ fontFamily: head }}>{name}</b>
              <span className="ml-auto rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ background: g.primary, color: g.on }}>
                {t('ui.new')}
              </span>
            </div>
            <p className="text-sm" style={{ color: g.muted }}>
              {t('ui.cardText')}
            </p>
          </div>
          {label(t('ui.badges'))}
          <div className="flex flex-wrap gap-2 text-xs">
            {set.colors
              .filter((c) => c.role !== 'neutral')
              .slice(0, 4)
              .map((c) => (
                <span key={c.name} className="rounded-full px-2.5 py-0.5 font-semibold" style={{ background: c.hex, color: textOn(c.hex) }}>
                  {c.name}
                </span>
              ))}
            <span className="rounded-full border px-2.5 py-0.5" style={{ borderColor: g.line }}>
              {t('ui.draft')}
            </span>
          </div>
        </div>
      </div>
      <p className="text-xs text-mist-500">{t('ui.code')}</p>
    </div>
  )
}
