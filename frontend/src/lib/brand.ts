/** The shape of a design set, as the server keeps it (`backend/app/services/brandset.py`). */

export type ColorRole = 'primary' | 'secondary' | 'accent' | 'neutral'
export const COLOR_ROLES: ColorRole[] = ['primary', 'secondary', 'accent', 'neutral']

export type BrandColor = { name: string; hex: string; role: ColorRole; pantone?: string; cmyk?: string; note?: string }

export type FontLicense = 'free' | 'internal' | 'system'
export type Fallback = 'serif' | 'sans-serif' | 'monospace' | 'cursive'

export type BrandFont = {
  family: string
  role: string
  weights: number[]
  italic?: boolean
  license: FontLicense
  license_note?: string
  source?: string
  /** A font that ships with nexbrand (`lib/fonts.ts`). */
  catalog?: string
  /** Uploaded font files (media ids). */
  files?: string[]
  fallback?: Fallback
}

export type Wordmark = { text: string; font: string }

export type BrandLogo = {
  id: string
  name: string
  /** An uploaded picture (SVG, PNG …); empty with a word mark. */
  media?: string
  /** Further formats to hand out (EPS, PDF …). */
  files?: string[]
  wordmark?: Wordmark | null
  fg: string
  accent: string
  ground: string
  compact?: boolean
  min_width?: string
  clear_space?: string
}

export type ScaleUse = '' | 'h1' | 'h2' | 'h3' | 'h4' | 'lead' | 'body' | 'small' | 'caption' | 'label'
export const SCALE_USES: ScaleUse[] = ['', 'h1', 'h2', 'h3', 'h4', 'lead', 'body', 'small', 'caption', 'label']

export type ScaleStep = { name: string; use?: ScaleUse; size: number; weight: number; font: string; line_height: number }
export type RuleKind = 'do' | 'dont'
export type RuleTopic = '' | 'logo' | 'color' | 'font' | 'image' | 'tone'
export const RULE_TOPICS: RuleTopic[] = ['', 'logo', 'color', 'font', 'image', 'tone']
export type RuleUse = '' | 'headings' | Exclude<ScaleUse, ''>
export const RULE_USES: RuleUse[] = ['', 'headings', ...(SCALE_USES.filter((u) => u) as Exclude<ScaleUse, ''>[])]

/**
 * A rule of the set. All but `text` point at parts of the set by name and are checked (`lib/checks.ts`); `text` is
 * words nobody checks. A rule stored without a type is a `text` rule.
 */
export type Rule =
  | { type?: 'text'; kind: RuleKind; text: string; topic?: RuleTopic }
  | { type: 'pair'; kind: RuleKind; text?: string; fg: string; bg: string; size?: 'text' | 'large' }
  | { type: 'logo'; kind: RuleKind; text?: string; logo: string; grounds: string[] }
  | { type: 'font'; kind: RuleKind; text?: string; font: string; use?: RuleUse; min_size?: number }
export type Sample = { name: string; media: string }

/** The set's dark mode: which of its colours is what (by name). */
export type DarkPart = 'ground' | 'surface' | 'text' | 'muted' | 'primary' | 'on_primary'
export const DARK_PARTS: DarkPart[] = ['ground', 'surface', 'text', 'muted', 'primary', 'on_primary']
export type DarkMode = Record<DarkPart, string>
/** A dark mode as values, ready to draw; null when a name is gone. */
export type Scheme = Record<DarkPart, string>

export function schemeOf(dark: DarkMode | null | undefined, colors: BrandColor[]): Scheme | null {
  if (!dark) return null
  const out: Partial<Scheme> = {}
  for (const part of DARK_PARTS) {
    const found = colors.find((c) => c.name.toLowerCase() === (dark[part] ?? '').toLowerCase())
    if (!found) return null
    out[part] = found.hex
  }
  return out as Scheme
}

export type BrandSet = {
  colors: BrandColor[]
  fonts: BrandFont[]
  logos: BrandLogo[]
  scale: ScaleStep[]
  rules: Rule[]
  samples: Sample[]
  dark?: DarkMode | null
}

export function emptySet(): BrandSet {
  return { colors: [], fonts: [], logos: [], scale: [], rules: [], samples: [] }
}

/** A colour as a project shows it: inherited from its version, replacing one there, or its own. */
export type ShownColor = BrandColor & { from?: 'inherited' | 'replaced' | 'own' }

/** The main colours a page or preview needs, chosen by role and lightness. */
export function pickColors(colors: BrandColor[], luminance: (hex: string) => number) {
  const neutrals = colors.filter((c) => c.role === 'neutral').sort((a, b) => luminance(b.hex) - luminance(a.hex))
  const primary = colors.find((c) => c.role === 'primary')?.hex ?? colors[0]?.hex ?? '#2F7BFF'
  const accent = colors.find((c) => c.role === 'accent')?.hex ?? colors.find((c) => c.role === 'secondary')?.hex ?? primary
  const light = neutrals.find((c) => c.hex.toUpperCase() !== '#FFFFFF')?.hex ?? '#FAFAF7'
  const dark = neutrals[neutrals.length - 1]?.hex ?? '#15151B'
  return { primary, accent, light, dark: luminance(dark) < 0.2 ? dark : '#15151B' }
}

/** What a step of the type scale is for, beside its name, only when it says something the name does not: "Heading 1
 * (Heading 1)" said it twice (F33). */
export function purposeBeside(name: string, use: string): string | null {
  const plain = (text: string) => text.trim().toLocaleLowerCase()
  return use && plain(use) !== plain(name) ? use : null
}
