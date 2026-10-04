/**
 * The checks a design set runs on itself, live while somebody edits: every hint comes from the numbers.
 *
 * The same rules and codes as the server (`backend/app/services/checks.py`), which hands them to programs and AI;
 * `checks.test.ts` holds both to the same answers. The words come from `checks.*` in the language files.
 */

import type { BrandColor, BrandSet } from './brand'
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
}

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

export function check(set: Pick<BrandSet, 'colors' | 'fonts' | 'logos' | 'scale'>, colorList?: BrandColor[]): Hint[] {
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

  const order = { bad: 0, warn: 1, info: 2 }
  return hints.sort((a, b) => order[a.level] - order[b.level])
}
