/**
 * The checks a design set runs on itself, live while somebody edits: every hint comes from the numbers.
 *
 * The same rules and codes as the server (`backend/app/services/checks.py`), which hands them to programs and AI;
 * `checks.test.ts` holds both to the same answers. The words come from `checks.*` in the language files.
 */

import type { BrandColor, BrandLogo, BrandSet, Rule } from './brand'
import { contrast, deltaE, luminance, simulate, type Vision } from './color'

export type HintLevel = 'bad' | 'warn' | 'info'

export type Hint = {
  level: HintLevel
  code: string
  colors?: string[]
  hex?: string[]
  ratio?: number
  delta_e?: number
  better?: string
  better_ratio?: number
  logo?: string
  size?: number
  font?: string
  /** The rule a hint is about (its place in the list). */
  rule?: number
  missing?: string
  need?: number
  step?: string
  min?: number
}

const HEADINGS = ['h1', 'h2', 'h3', 'h4']

const WHITE = '#FFFFFF'
const r2 = (n: number) => Math.round(n * 100) / 100

export function visionClashes(items: BrandColor[], vision: Vision): [BrandColor, BrandColor, number][] {
  const loud = items.filter((c) => c.role !== 'neutral')
  const out: [BrandColor, BrandColor, number][] = []
  for (let i = 0; i < loud.length; i++)
    for (let j = i + 1; j < loud.length; j++) {
      const a = loud[i]
      const b = loud[j]
      if (deltaE(a.hex, b.hex) < 15) continue
      const d = deltaE(simulate(a.hex, vision), simulate(b.hex, vision))
      if (d < 10) out.push([a, b, d])
    }
  return out
}

/** The colours of a logo drawn from values here; an uploaded file keeps its own. */
function drawn(logo: BrandLogo): string[] {
  if (!logo.wordmark) return []
  return [logo.accent, ...(logo.compact ? [] : [logo.fg])]
}

/** What the rules of a set say against the set itself. A `text` rule is words: nothing here reads it. */
export function ruleHints(set: Pick<BrandSet, 'fonts' | 'logos' | 'scale'> & { rules?: Rule[] }, items: BrandColor[]): Hint[] {
  const byName = new Map(items.map((c) => [c.name.toLowerCase(), c] as const))
  const byHex = new Map(items.map((c) => [c.hex.toUpperCase(), c] as const).reverse())
  const logos = new Map(set.logos.map((l) => [l.id, l] as const))
  const families = new Set(set.fonts.map((f) => f.family.toLowerCase()))
  const rules = set.rules ?? []
  const hints: Hint[] = []
  const missing = (rule: number, name: string): Hint => ({ level: 'warn', code: 'rule_missing', rule, missing: name })
  const forbidden = new Set(rules.filter((r) => r.type === 'pair' && r.kind === 'dont').map((r) => (r.type === 'pair' ? r.fg.toLowerCase() + '\u0000' + r.bg.toLowerCase() : '')))

  rules.forEach((rule, index) => {
    if (rule.type === 'pair') {
      const fg = byName.get(rule.fg.toLowerCase())
      const bg = byName.get(rule.bg.toLowerCase())
      if (!fg || !bg) {
        for (const [name, found] of [[rule.fg, fg], [rule.bg, bg]] as const) if (!found) hints.push(missing(index, name))
        return
      }
      const ratio = contrast(fg.hex, bg.hex)
      if (rule.kind === 'do') {
        const need = (rule.size ?? 'text') === 'text' ? 4.5 : 3
        if (ratio < need) hints.push({ level: ratio < 3 ? 'bad' : 'warn', code: 'rule_pair_low', rule: index, colors: [fg.name, bg.name], hex: [fg.hex, bg.hex], ratio: r2(ratio), need })
        if (forbidden.has(fg.name.toLowerCase() + '\u0000' + bg.name.toLowerCase())) hints.push({ level: 'bad', code: 'rule_conflict', rule: index, colors: [fg.name, bg.name], hex: [fg.hex, bg.hex] })
      } else
        for (const logo of set.logos) {
          const ground = (logo.ground ?? 'transparent').toUpperCase()
          if (ground === bg.hex.toUpperCase() && drawn(logo).some((v) => v.toUpperCase() === fg.hex.toUpperCase()))
            hints.push({ level: 'bad', code: 'rule_pair_logo', rule: index, logo: logo.name, colors: [fg.name, bg.name], hex: [fg.hex, bg.hex] })
        }
    } else if (rule.type === 'logo') {
      const logo = logos.get(rule.logo)
      if (!logo) {
        hints.push(missing(index, rule.logo))
        return
      }
      const grounds: BrandColor[] = []
      for (const name of rule.grounds) {
        const found = byName.get(name.toLowerCase())
        if (found) grounds.push(found)
        else hints.push(missing(index, name))
      }
      const ground = logo.ground ?? 'transparent'
      if (ground !== 'transparent' && grounds.length) {
        const listed = grounds.some((g) => g.hex.toUpperCase() === ground.toUpperCase())
        if (listed !== (rule.kind === 'do')) {
          const named = byHex.get(ground.toUpperCase())
          hints.push({ level: listed ? 'bad' : 'warn', code: `rule_logo_ground_${rule.kind}`, rule: index, logo: logo.name, colors: [named ? named.name : ground], hex: [ground] })
        }
      }
      if (rule.kind === 'do')
        for (const g of grounds) {
          const values = drawn(logo)
          const ratios = values.map((v) => contrast(v, g.hex))
          if (!ratios.length) continue
          const least = Math.min(...ratios)
          if (least < 3) hints.push({ level: 'warn', code: 'rule_logo_contrast', rule: index, logo: logo.name, colors: [g.name], hex: [values[ratios.indexOf(least)], g.hex], ratio: r2(least) })
        }
    } else if (rule.type === 'font') {
      const family = rule.font
      if (!families.has(family.toLowerCase())) {
        hints.push(missing(index, family))
        return
      }
      const use = rule.use ?? ''
      const steps = set.scale.filter((s) => !use || s.use === use || (use === 'headings' && HEADINGS.includes(s.use ?? '')))
      for (const step of steps) {
        const same = (step.font || '').toLowerCase() === family.toLowerCase()
        if (rule.kind === 'dont' && same) hints.push({ level: 'bad', code: 'rule_font_forbidden', rule: index, font: family, step: step.name })
        else if (rule.kind === 'do' && step.font && !same) hints.push({ level: 'warn', code: 'rule_font_wrong', rule: index, font: family, step: step.name })
        if (rule.kind === 'do' && rule.min_size && step.size < rule.min_size) hints.push({ level: 'warn', code: 'rule_font_small', rule: index, font: family, step: step.name, size: step.size, min: rule.min_size })
      }
    }
  })
  return hints
}

export function check(set: Pick<BrandSet, 'colors' | 'fonts' | 'logos' | 'scale'> & { rules?: Rule[] }, colorList?: BrandColor[]): Hint[] {
  const items = (colorList ?? set.colors).filter((c) => /^#[0-9A-Fa-f]{6}$/.test(c.hex))
  const hints: Hint[] = []
  const white = items.some((c) => c.hex.toUpperCase() === WHITE)

  for (const bg of items) {
    const others = items.filter((t) => t !== bg)
    const readable = others.filter((t) => contrast(t.hex, bg.hex) >= 4.5)
    const large = others.filter((t) => contrast(t.hex, bg.hex) >= 3)
    if (!readable.length && large.length) hints.push({ level: 'warn', code: 'ground_large_only', colors: [bg.name], hex: [bg.hex] })
    else if (!readable.length && others.length) hints.push({ level: 'bad', code: 'ground_unreadable', colors: [bg.name], hex: [bg.hex] })
  }

  if (white)
    for (const bg of items.filter((c) => c.role !== 'neutral')) {
      const ratio = contrast(WHITE, bg.hex)
      if (ratio >= 4.5) continue
      const better = items
        .filter((t) => t !== bg && contrast(t.hex, bg.hex) >= 4.5)
        .sort((a, b) => contrast(b.hex, bg.hex) - contrast(a.hex, bg.hex))[0]
      const hint: Hint = { level: ratio < 3 ? 'bad' : 'warn', code: 'white_on', colors: [bg.name], hex: [WHITE, bg.hex], ratio: r2(ratio) }
      if (better) {
        hint.better = better.name
        hint.better_ratio = r2(contrast(better.hex, bg.hex))
      }
      hints.push(hint)
    }

  for (const primary of items.filter((c) => c.role === 'primary'))
    for (const bg of items.filter((c) => c.role === 'neutral' && luminance(c.hex) > 0.6)) {
      const ratio = contrast(primary.hex, bg.hex)
      if (ratio < 4.5) hints.push({ level: 'warn', code: 'primary_as_text', colors: [primary.name, bg.name], hex: [primary.hex, bg.hex], ratio: r2(ratio) })
    }

  for (let i = 0; i < items.length; i++)
    for (let j = i + 1; j < items.length; j++) {
      const d = deltaE(items[i].hex, items[j].hex)
      if (d < 4) hints.push({ level: 'warn', code: 'nearly_same', colors: [items[i].name, items[j].name], hex: [items[i].hex, items[j].hex], delta_e: r2(d) })
    }

  for (const vision of ['deutan', 'protan'] as Vision[])
    for (const [a, b, d] of visionClashes(items, vision))
      hints.push({ level: 'warn', code: `vision_${vision}`, colors: [a.name, b.name], hex: [a.hex, b.hex], delta_e: r2(d) })

  for (const logo of set.logos) {
    // An uploaded file keeps its colours inside; only a word mark is drawn from the values here.
    if (logo.ground === 'transparent' || !logo.wordmark) continue
    const parts: [string, string][] = [['mark', logo.accent], ...(logo.compact ? [] : ([['word', logo.fg]] as [string, string][]))]
    for (const [part, value] of parts) {
      const ratio = contrast(value, logo.ground)
      if (ratio < 3) hints.push({ level: 'warn', code: `logo_${part}`, logo: logo.name, hex: [value, logo.ground], ratio: r2(ratio) })
    }
  }

  const body = set.scale.find((step) => step.use === 'body')
  if (body && body.size < 16) hints.push({ level: 'warn', code: 'body_small', size: body.size })

  for (const font of set.fonts) {
    if (font.license === 'internal') hints.push({ level: 'info', code: 'font_internal', font: font.family })
    else if (font.license === 'system') hints.push({ level: 'info', code: 'font_system', font: font.family })
  }

  hints.push(...ruleHints(set, items))

  const order = { bad: 0, warn: 1, info: 2 }
  return hints.sort((a, b) => order[a.level] - order[b.level])
}
