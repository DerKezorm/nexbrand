/**
 * Fonts: the ones that ship with nexbrand (all under the SIL Open Font License, drawn in every browser without an
 * upload), and uploaded font files, loaded into the page on demand so a specimen shows the real thing.
 */

import '@fontsource-variable/dm-sans'
import '@fontsource-variable/fraunces'
import '@fontsource-variable/lora'
import '@fontsource-variable/nunito'
import '@fontsource-variable/outfit'
import '@fontsource-variable/playfair-display'
import '@fontsource-variable/source-serif-4'
import '@fontsource-variable/space-grotesk'

import type { BrandFont, Fallback } from './brand'

export type Mood = 'warm' | 'fresh' | 'serious' | 'playful' | 'fine' | 'bold' | 'calm'

export type CatalogFont = { id: string; family: string; stack: string; kind: 'serif' | 'sans' | 'grotesk' | 'rounded'; weights: number[]; fallback: Fallback }

/** The same ids as the server's `brandset.CATALOG`. */
export const CATALOG: CatalogFont[] = [
  { id: 'fraunces', family: 'Fraunces', stack: "'Fraunces Variable', Georgia, serif", kind: 'serif', weights: [400, 600, 800], fallback: 'serif' },
  { id: 'playfair', family: 'Playfair Display', stack: "'Playfair Display Variable', Georgia, serif", kind: 'serif', weights: [400, 600, 800], fallback: 'serif' },
  { id: 'lora', family: 'Lora', stack: "'Lora Variable', Georgia, serif", kind: 'serif', weights: [400, 600, 700], fallback: 'serif' },
  { id: 'sourceserif', family: 'Source Serif 4', stack: "'Source Serif 4 Variable', Georgia, serif", kind: 'serif', weights: [400, 600, 700], fallback: 'serif' },
  { id: 'inter', family: 'Inter', stack: "'Inter Variable', system-ui, sans-serif", kind: 'sans', weights: [400, 500, 600, 700], fallback: 'sans-serif' },
  { id: 'dmsans', family: 'DM Sans', stack: "'DM Sans Variable', system-ui, sans-serif", kind: 'sans', weights: [400, 500, 700], fallback: 'sans-serif' },
  { id: 'outfit', family: 'Outfit', stack: "'Outfit Variable', system-ui, sans-serif", kind: 'sans', weights: [400, 600, 700], fallback: 'sans-serif' },
  { id: 'spacegrotesk', family: 'Space Grotesk', stack: "'Space Grotesk Variable', system-ui, sans-serif", kind: 'grotesk', weights: [400, 500, 700], fallback: 'sans-serif' },
  { id: 'nunito', family: 'Nunito', stack: "'Nunito Variable', system-ui, sans-serif", kind: 'rounded', weights: [400, 600, 800], fallback: 'sans-serif' },
]

export const catalogFont = (id: string | undefined) => CATALOG.find((f) => f.id === id)

export type Pairing = { head: string; body: string; moods: Mood[] }

/** Pairs that work, with the moods they suit; the words are in `fonts.pairs.<head>-<body>`. */
export const PAIRINGS: Pairing[] = [
  { head: 'fraunces', body: 'inter', moods: ['warm', 'calm'] },
  { head: 'playfair', body: 'dmsans', moods: ['fine'] },
  { head: 'spacegrotesk', body: 'inter', moods: ['bold', 'serious'] },
  { head: 'outfit', body: 'sourceserif', moods: ['fresh'] },
  { head: 'nunito', body: 'nunito', moods: ['playful'] },
  { head: 'lora', body: 'dmsans', moods: ['calm', 'serious', 'warm'] },
]

export function catalogEntry(id: string, role: string): BrandFont {
  const f = catalogFont(id) ?? CATALOG[4]
  return { family: f.family, role, weights: f.weights, license: 'free', license_note: 'SIL Open Font License 1.1', source: 'Google Fonts', catalog: f.id, fallback: f.fallback, files: [] }
}

const loaded = new Map<string, Promise<boolean>>()

/** An uploaded font file into the page, once, under a name of its own; resolves false when the browser refuses it. */
function load(id: string, url: string): Promise<boolean> {
  const known = loaded.get(url)
  if (known) return known
  const promise = (async () => {
    try {
      const face = new FontFace(`nb-${id}`, `url(${url})`)
      document.fonts.add(await face.load())
      return true
    } catch {
      return false
    }
  })()
  loaded.set(url, promise)
  return promise
}

/** The CSS font-family for a font of a design set. `fileUrl` turns a media id into its address (signed in, a public
 * page, a review). Uploaded files start loading at once; until they are there, the family name and fallback show. */
export function fontStack(font: Pick<BrandFont, 'family' | 'catalog' | 'files' | 'fallback'> | undefined, fileUrl: (id: string) => string): string {
  if (!font) return 'inherit'
  const shipped = catalogFont(font.catalog)
  if (shipped) return shipped.stack
  const quoted = `'${font.family.replace(/'/g, '')}'`
  const files = font.files ?? []
  if (files.length) {
    for (const id of files) void load(id, fileUrl(id))
    return `${files.map((id) => `'nb-${id}'`).join(', ')}, ${quoted}, ${font.fallback ?? 'sans-serif'}`
  }
  return `${quoted}, ${font.fallback ?? 'sans-serif'}`
}

/** A font of the set by its family name (the type scale and word marks name fonts that way). */
export function findFont(fonts: BrandFont[], family: string): BrandFont | undefined {
  const wanted = family.toLocaleLowerCase()
  return fonts.find((f) => f.family.toLocaleLowerCase() === wanted) ?? (catalogFont(CATALOG.find((c) => c.family.toLocaleLowerCase() === wanted)?.id) ? catalogEntry(CATALOG.find((c) => c.family.toLocaleLowerCase() === wanted)!.id, '') : undefined)
}
