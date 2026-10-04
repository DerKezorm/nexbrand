/** How a rule reads, the same in the editor and in the view. */
import { ShieldCheck, Type } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import type { BrandColor, BrandLogo, Rule, RuleUse } from '../../lib/brand'

export type RuleType = 'text' | 'pair' | 'logo' | 'font'

// eslint-disable-next-line react-refresh/only-export-components
export const typeOf = (rule: Rule): RuleType => rule.type ?? 'text'

/** The words of a rule: one line, from the names it points at. */
// eslint-disable-next-line react-refresh/only-export-components
export function useRuleWords() {
  const { t, i18n } = useTranslation()
  const labelOfUse = (use: RuleUse | undefined) => (!use ? t('rules.use.all') : use === 'headings' ? t('rules.use.headings') : t(`set.use.${use}`))
  const list = (names: string[]) => new Intl.ListFormat(i18n.language, { type: 'conjunction' }).format(names)
  return {
    labelOfUse,
    kind: (rule: Rule) => t(`rules.kind.${typeOf(rule)}.${rule.kind}`),
    sentence(rule: Rule, logos: BrandLogo[]): string {
      if (rule.type === 'pair') return t(rule.size === 'large' ? 'rules.sentence.pairLarge' : 'rules.sentence.pair', { fg: rule.fg, bg: rule.bg })
      if (rule.type === 'logo') {
        const logo = logos.find((l) => l.id === rule.logo)?.name ?? rule.logo
        return t(rule.kind === 'do' ? 'rules.sentence.logoDo' : 'rules.sentence.logoDont', { logo, grounds: list(rule.grounds) })
      }
      if (rule.type === 'font') {
        const values = { font: rule.font, use: labelOfUse(rule.use), min: rule.min_size }
        return t(rule.kind === 'do' && rule.min_size ? 'rules.sentence.fontMin' : 'rules.sentence.font', values)
      }
      return rule.text
    },
  }
}

/** Whether a rule is checked: a small mark beside it. */
export function CheckedMark({ rule }: { rule: Rule }) {
  const { t } = useTranslation()
  const checked = typeOf(rule) !== 'text'
  const Icon = checked ? ShieldCheck : Type
  return (
    <span className={'inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] ' + (checked ? 'bg-ok-500/12 text-ok-500' : 'bg-ink-800 text-mist-500')}>
      <Icon className="h-3 w-3" aria-hidden /> {checked ? t('rules.checked') : t('rules.unchecked')}
    </span>
  )
}

/** The colours a rule shows: a text sample for a pair, dots for grounds. */
export function RuleSwatch({ rule, colors }: { rule: Rule; colors: BrandColor[] }) {
  const find = (name: string) => colors.find((c) => c.name.toLowerCase() === name.toLowerCase())
  if (rule.type === 'pair') {
    const fg = find(rule.fg)
    const bg = find(rule.bg)
    if (!fg || !bg) return null
    return (
      <span className="shrink-0 rounded-md border border-edge px-2 py-0.5 text-sm font-semibold" style={{ color: fg.hex, background: bg.hex }} aria-hidden>
        Aa
      </span>
    )
  }
  if (rule.type === 'logo')
    return (
      <span className="flex shrink-0 -space-x-1" aria-hidden>
        {rule.grounds.map((name) => {
          const c = find(name)
          return c ? <span key={name} className="h-5 w-5 rounded-full border border-edge" style={{ background: c.hex }} /> : null
        })}
      </span>
    )
  return null
}
