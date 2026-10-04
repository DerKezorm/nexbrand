/** What the workbench proposes: harmonies, neutrals, type scales, colours from a picture, and directions from a brief. */
import type { BrandColor, BrandLogo, Rule, ScaleStep } from './brand'
import { pickColors } from './brand'
import { contrast, deltaE, fromHsl, hsl, luminance, reach, textOn, toHex } from './color'
import { PAIRINGS, catalogFont, type Mood } from './fonts'

const wrap = (h: number) => ((h % 360) + 360) % 360

export type Harmony = { key: 'complement' | 'neighbours' | 'triad' | 'split'; colors: string[] }

export function harmonies(primary: string): Harmony[] {
  const [h, s, l] = hsl(primary)
  const at = (dh: number, ds = 0, dl = 0) => fromHsl(wrap(h + dh), Math.min(95, Math.max(15, s + ds)), Math.min(70, Math.max(30, l + dl)))
  return [
    { key: 'complement', colors: [at(180, -10, 10)] },
    { key: 'neighbours', colors: [at(-30), at(30, 0, 10)] },
    { key: 'triad', colors: [at(120, -15, 8), at(240, -15, 8)] },
    { key: 'split', colors: [at(150, -10, 8), at(210, -10, 8)] },
  ]
}

export type Names = { primary: string; accent: string; second: string; paper: string; stone: string; ink: string; white: string; light: string; dark: string }

/** Neutrals tinted with the main hue: an off-white, a mid grey for borders, a dark for text. */
export function neutralsFor(primary: string, names: Names): BrandColor[] {
  const [h] = hsl(primary)
  return [
    { name: names.paper, hex: fromHsl(h, 30, 96), role: 'neutral' },
    { name: names.stone, hex: fromHsl(h, 8, 62), role: 'neutral' },
    { name: names.ink, hex: fromHsl(h, 25, 13), role: 'neutral' },
  ]
}

export const RATIOS = [1.125, 1.2, 1.25, 1.333, 1.5]

export function typeScale(base: number, ratio: number, head: string, body: string, names: Record<string, string>): ScaleStep[] {
  const r = (n: number) => Math.round(base * ratio ** n)
  return [
    { name: names.h1, use: 'h1', size: r(4), weight: 700, font: head, line_height: 1.1 },
    { name: names.h2, use: 'h2', size: r(3), weight: 600, font: head, line_height: 1.15 },
    { name: names.h3, use: 'h3', size: r(2), weight: 600, font: head, line_height: 1.25 },
    { name: names.lead, use: 'lead', size: r(1), weight: 500, font: body, line_height: 1.4 },
    { name: names.body, use: 'body', size: base, weight: 400, font: body, line_height: 1.6 },
    { name: names.small, use: 'small', size: Math.round(base / ratio), weight: 400, font: body, line_height: 1.5 },
  ]
}

/** Dominant colours of a picture: count coarse buckets, then keep the biggest that differ clearly. */
export function colorsOfImage(data: Uint8ClampedArray): string[] {
  const buckets = new Map<string, { n: number; r: number; g: number; b: number }>()
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] < 128) continue
    const key = `${data[i] >> 4},${data[i + 1] >> 4},${data[i + 2] >> 4}`
    const e = buckets.get(key) ?? { n: 0, r: 0, g: 0, b: 0 }
    e.n++
    e.r += data[i]
    e.g += data[i + 1]
    e.b += data[i + 2]
    buckets.set(key, e)
  }
  const sorted = [...buckets.values()].sort((a, b) => b.n - a.n).map((e) => toHex([e.r / e.n, e.g / e.n, e.b / e.n]))
  const out: string[] = []
  for (const c of sorted) {
    if (out.every((o) => deltaE(o, c) > 14)) out.push(c)
    if (out.length === 6) break
  }
  return out
}

/** Picked colours into roles: the most colourful mid tone leads, the lightest and darkest become neutrals. */
export function rolesFor(colors: string[], names: Names): BrandColor[] {
  const withL = colors.map((c) => ({ c, l: hsl(c)[2], s: hsl(c)[1] }))
  const light = [...withL].sort((a, b) => b.l - a.l)[0]
  const dark = [...withL].sort((a, b) => a.l - b.l)[0]
  const loud = withL.filter((x) => x !== light && x !== dark).sort((a, b) => b.s - a.s)
  const out: BrandColor[] = []
  if (loud[0]) out.push({ name: names.primary, hex: loud[0].c, role: 'primary' })
  loud.slice(1, 3).forEach((x, i) => out.push({ name: i === 0 ? names.accent : names.second, hex: x.c, role: i === 0 ? 'accent' : 'secondary' }))
  if (light) out.push({ name: names.light, hex: light.c, role: 'neutral' })
  if (dark && dark !== light) out.push({ name: names.dark, hex: dark.c, role: 'neutral' })
  return out
}

const KEYWORDS: [RegExp, Mood, number][] = [
  [/warm|handwerk|craft|gemütlich|cosy|cozy|bäck|bake|holz|wood|herzlich|tradition/, 'warm', 18],
  [/frisch|fresh|natur|nature|bio|organic|grün|green|gesund|health|garten|garden|nachhaltig|sustain|umwelt/, 'fresh', 140],
  [/seriös|serious|vertrau|trust|bank|kanzlei|law|recht|versicher|insur|steuer|tax|beratung|consult/, 'serious', 218],
  [/verspielt|playful|kinder|child|kids|bunt|colourful|colorful|jung|young|party|spiel|play|fröhlich|cheer|kita/, 'playful', 322],
  [/luxus|luxury|edel|fine|premium|hochwertig|exklusiv|exclusive|schmuck|jewel|wein|wine/, 'fine', 42],
  [/sport|energie|energy|dynamisch|dynamic|kraft|power|fitness|schnell|fast|technik|tech|software/, 'bold', 8],
  [/ruhig|calm|medizin|medic|praxis|clinic|pflege|care|therapie|therapy|klar|clear|sanft|gentle|wellness/, 'calm', 188],
]

export type Direction = { id: 'a' | 'b' | 'c'; mood: Mood; second: Mood; colors: BrandColor[]; head: string; body: string; label?: string; why?: string }

/** Three directions from a few words, without an AI: hue and fonts by the moods the words name. The main colour is
 * then darkened until a button with white text and a link on the light ground reach 4.5:1. */
export function directions(brief: string, name: string, names: Names): Direction[] {
  const text = (brief + ' ' + name).toLocaleLowerCase()
  const hits = KEYWORDS.filter(([re]) => re.test(text))
  const found: [Mood, number][] = hits.length ? hits.map(([, m, h]) => [m, h]) : [['calm', 205]]
  const [m1, h1] = found[0]
  const [m2, h2] = found[1] ?? [m1, wrap(h1 + 35)]
  const pair = (m: Mood, skip?: string) => PAIRINGS.find((p) => p.moods.includes(m) && p.head !== skip) ?? PAIRINGS[0]

  const build = (id: Direction['id'], h: number, s: number, l: number, ah: number, as: number, al: number, mood: Mood, skipHead?: string): Direction => {
    const neutrals = neutralsFor(fromHsl(h, s, l), names)
    let primary = fromHsl(h, s, l)
    primary = reach(primary, '#FFFFFF', 4.5) ?? primary
    primary = reach(primary, neutrals[0].hex, 4.5) ?? primary
    const p = pair(mood, skipHead)
    return {
      id,
      mood,
      second: m2,
      head: p.head,
      body: p.body,
      colors: [
        { name: names.primary, hex: primary, role: 'primary' },
        { name: names.accent, hex: fromHsl(wrap(ah), as, al), role: 'accent' },
        neutrals[0],
        neutrals[2],
        { name: names.white, hex: '#FFFFFF', role: 'neutral' },
      ],
    }
  }
  return [
    build('a', h1, 58, 40, h1 + 32, 70, 58, m1),
    build('b', h1, 72, 44, h1 + 180, 55, 52, m2),
    build('c', h2, 30, 34, h2 - 40, 35, 60, m2 === m1 ? 'calm' : m2, pair(m1).head),
  ]
}

/** What the account's AI proposed (`routers/ai.py`, checked there: hue, saturation, a mood and fonts of the catalog).
 * The AI names a direction and says why; the colours are made here, the same way as without it, so the main colour
 * reaches 4.5:1 with white and on the light ground whatever the model said. */
export type AiDirection = { label: string; why: string; hue: number; accent_hue: number; saturation: number; mood: string; head: string; body: string }
const MOODS: Mood[] = ['warm', 'fresh', 'serious', 'playful', 'fine', 'bold', 'calm']

export function fromAi(list: AiDirection[], names: Names): Direction[] {
  return list.slice(0, 3).map((d, index) => {
    const mood = MOODS.includes(d.mood as Mood) ? (d.mood as Mood) : 'calm'
    const base = fromHsl(wrap(d.hue), Math.min(90, Math.max(20, d.saturation)), 42)
    const neutrals = neutralsFor(base, names)
    let primary = reach(base, '#FFFFFF', 4.5) ?? base
    primary = reach(primary, neutrals[0].hex, 4.5) ?? primary
    const fallback = PAIRINGS.find((p) => p.moods.includes(mood)) ?? PAIRINGS[0]
    return {
      id: (['a', 'b', 'c'] as const)[index],
      mood,
      second: mood,
      head: catalogFont(d.head) ? d.head : fallback.head,
      body: catalogFont(d.body) ? d.body : fallback.body,
      label: d.label,
      why: d.why,
      colors: [
        { name: names.primary, hex: primary, role: 'primary' },
        { name: names.accent, hex: fromHsl(wrap(d.accent_hue), 65, 55), role: 'accent' },
        neutrals[0],
        neutrals[2],
        { name: names.white, hex: '#FFFFFF', role: 'neutral' },
      ],
    }
  })
}

/** Rules a fresh design set can start with; those about contrast come from the numbers. */
export function startRules(colors: BrandColor[], words: { whiteOk: (name: string, ratio: string) => string; whiteBad: (name: string, ratio: string) => string; clear: string; distort: string }, locale: string): Rule[] {
  const rules: Rule[] = []
  for (const c of colors.filter((x) => x.role !== 'neutral')) {
    const r = contrast('#FFFFFF', c.hex)
    const ratio = r.toLocaleString(locale, { maximumFractionDigits: 1 }) + ':1'
    rules.push(r >= 4.5 ? { kind: 'do', text: words.whiteOk(c.name, ratio) } : { kind: 'dont', text: words.whiteBad(c.name, ratio) })
  }
  rules.push({ kind: 'do', text: words.clear })
  rules.push({ kind: 'dont', text: words.distort })
  return rules
}

/** Word marks that stand in for a logo until there is one. */
export function wordmarks(name: string, colors: BrandColor[], headFamily: string, labels: { positive: string; negative: string; monogram: string }): BrandLogo[] {
  const { primary, light, dark } = pickColors(colors, luminance)
  const mark = { text: name || '?', font: headFamily }
  return [
    { id: 'word-positive', name: labels.positive, wordmark: mark, fg: dark, accent: primary, ground: '#FFFFFF', min_width: '30 mm / 120 px' },
    { id: 'word-negative', name: labels.negative, wordmark: mark, fg: light, accent: primary, ground: dark, min_width: '30 mm / 120 px' },
    { id: 'monogram', name: labels.monogram, wordmark: mark, fg: textOn(primary), accent: primary, ground: light, compact: true, min_width: '8 mm / 24 px' },
  ]
}

export function familyOf(catalogId: string): string {
  return catalogFont(catalogId)?.family ?? 'Inter'
}
