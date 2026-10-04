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
export type Rule = { kind: 'do' | 'dont'; text: string }
export type Sample = { name: string; media: string }

export type BrandSet = {
  colors: BrandColor[]
  fonts: BrandFont[]
  logos: BrandLogo[]
  scale: ScaleStep[]
  rules: Rule[]
  samples: Sample[]
}

export function emptySet(): BrandSet {
  return { colors: [], fonts: [], logos: [], scale: [], rules: [], samples: [] }
}

/** A colour as a project shows it: inherited from its version, replacing one there, or its own. */
export type ShownColor = BrandColor & { from?: 'inherited' | 'replaced' | 'own' }

export function projectColors(set: BrandSet, own: BrandColor[]): ShownColor[] {
  const mine = new Map(own.map((color) => [color.name.toLocaleLowerCase(), color]))
  const out: ShownColor[] = set.colors.map((color) => {
    const replaced = mine.get(color.name.toLocaleLowerCase())
    if (replaced) mine.delete(color.name.toLocaleLowerCase())
    return replaced ? { ...replaced, from: 'replaced' } : { ...color, from: 'inherited' }
  })
  for (const color of mine.values()) out.push({ ...color, from: 'own' })
  return out
}

/** The main colours a page or preview needs, chosen by role and lightness. */
export function pickColors(colors: BrandColor[], luminance: (hex: string) => number) {
  const neutrals = colors.filter((c) => c.role === 'neutral').sort((a, b) => luminance(b.hex) - luminance(a.hex))
  const primary = colors.find((c) => c.role === 'primary')?.hex ?? colors[0]?.hex ?? '#2F7BFF'
  const accent = colors.find((c) => c.role === 'accent')?.hex ?? colors.find((c) => c.role === 'secondary')?.hex ?? primary
  const light = neutrals.find((c) => c.hex.toUpperCase() !== '#FFFFFF')?.hex ?? '#FAFAF7'
  const dark = neutrals[neutrals.length - 1]?.hex ?? '#15151B'
  return { primary, accent, light, dark: luminance(dark) < 0.2 ? dark : '#15151B' }
}
