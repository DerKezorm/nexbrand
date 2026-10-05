/**
 * Colour arithmetic: WCAG contrast, CIEDE2000 distance, colour vision, CMYK, web scales.
 *
 * The same numbers as the server (`backend/app/services/colors.py`); `color.test.ts` checks both against
 * `backend/tests/data/color_cases.json`.
 */

export type Rgb = [number, number, number]

export function rgb(hex: string): Rgb {
  const h = hex.replace('#', '')
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as Rgb
}

export function toHex([r, g, b]: Rgb): string {
  const c = (v: number) => Math.round(Math.min(255, Math.max(0, v))).toString(16).padStart(2, '0')
  return ('#' + c(r) + c(g) + c(b)).toUpperCase()
}

export function isHex(value: string): boolean {
  return /^#[0-9a-fA-F]{6}$/.test(value)
}

/** A colour as people write it (`#abc`, `abc`, `rgb(…)`, `hsl(…)`, see `parseColor`) as `#AABBCC`; anything else as
 * it was (the check refuses it). */
export function normalHex(value: string): string {
  return parseColor(value) ?? value
}

const toLinear = (v: number) => {
  v /= 255
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
}
const fromLinear = (v: number) => 255 * (v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055)

export function luminance(color: string): number {
  const [r, g, b] = rgb(color).map(toLinear)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p)
  return (x + 0.05) / (y + 0.05)
}

export type Grade = 'AAA' | 'AA' | 'AA large' | 'fail'

/** WCAG 2.2 for text: 4.5 normal, 3 large (from 24 px, or 18.7 px bold); AAA 7 and 4.5. */
export function grade(ratio: number, large = false): Grade {
  if (large) return ratio >= 4.5 ? 'AAA' : ratio >= 3 ? 'AA' : 'fail'
  return ratio >= 7 ? 'AAA' : ratio >= 4.5 ? 'AA' : ratio >= 3 ? 'AA large' : 'fail'
}

/** A contrast ratio as it is shown: cut, never rounded up, to two places (one from 10:1). 4.4992 is shown as 4.49, not
 * as 4.50 beside "fails": a ratio shown at or above a threshold has reached it. As `shown_ratio` on the server. */
export function shownRatio(r: number): number {
  const places = r >= 10 ? 10 : 100
  return Math.floor(r * places + 1e-9) / places
}

export function formatRatio(r: number, locale = 'en'): string {
  const digits = r >= 10 ? 1 : 2
  return shownRatio(r).toLocaleString(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits }) + ':1'
}

const NUMBER = /[+-]?(?:\d+(?:\.\d*)?|\.\d+)/.source
const HEX_TEXT = /^(?:#?([0-9a-f]{3}|[0-9a-f]{6})|#([0-9a-f]{4}|[0-9a-f]{8}))$/
const FUNCTION = /^(rgba?|hsla?)\(\s*([^()]*?)\s*\)$/
const PART = new RegExp(`^(${NUMBER})(%|deg)?$`)

function parts(text: string): [number, string][] | null {
  const body = text.split('/')[0]
  let items = body.trim().split(/\s*,\s*|\s+/).filter((item) => item)
  if (items.length === 4 && body.includes(',')) items = items.slice(0, 3)
  if (items.length !== 3) return null
  const out: [number, string][] = []
  for (const item of items) {
    const match = PART.exec(item)
    if (!match) return null
    out.push([parseFloat(match[1]), match[2] ?? ''])
  }
  return out
}

/** A colour as people and style sheets write it, as `#RRGGBB`: `#RGB`, `#RRGGBB` (with alpha, which is left out), the
 * same without `#`, `rgb()`/`rgba()` and `hsl()`/`hsla()` with commas or spaces. null: not a colour read here (a name
 * such as `red` neither). The same as `colors.parse` on the server; `color_cases.json` holds both to it. */
export function parseColor(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const text = value.trim().toLowerCase()
  if (text.length > 80) return null
  const hexed = HEX_TEXT.exec(text)
  if (hexed) {
    let digits = hexed[1] ?? hexed[2]
    if (digits.length === 3 || digits.length === 4) digits = digits.slice(0, 3).split('').map((c) => c + c).join('')
    return '#' + digits.slice(0, 6).toUpperCase()
  }
  const fn = FUNCTION.exec(text)
  if (!fn) return null
  const found = parts(fn[2])
  if (!found) return null
  if (fn[1].startsWith('rgb')) {
    if (found.some(([, unit]) => unit === 'deg')) return null
    const channels = found.map(([n, unit]) => (unit === '%' ? n * 2.55 : n))
    if (channels.some((c) => c < 0 || c > 255)) return null
    return toHex([channels[0], channels[1], channels[2]])
  }
  const [[hue, hueUnit], [saturation, sUnit], [light, lUnit]] = found
  if (hueUnit === '%' || sUnit === 'deg' || lUnit === 'deg' || saturation < 0 || saturation > 100 || light < 0 || light > 100) return null
  return fromHsl(((hue % 360) + 360) % 360, saturation, light)
}

/** Which of near-black and white reads better on this ground. */
export function textOn(bg: string, dark = '#14141A'): string {
  return contrast(bg, '#FFFFFF') >= contrast(bg, dark) ? '#FFFFFF' : dark
}

export function hsl(color: string): [number, number, number] {
  const [r, g, b] = rgb(color).map((v) => v / 255)
  const mx = Math.max(r, g, b)
  const mn = Math.min(r, g, b)
  const d = mx - mn
  let h = 0
  if (d) h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4
  h = (h * 60 + 360) % 360
  const l = (mx + mn) / 2
  const s = d ? d / (1 - Math.abs(2 * l - 1)) : 0
  return [Math.round(h), Math.round(s * 100), Math.round(l * 100)]
}

export function fromHsl(h: number, s: number, l: number): string {
  s /= 100
  l /= 100
  const k = (n: number) => (n + h / 30) % 12
  const a = s * Math.min(l, 1 - l)
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)))
  return toHex([f(0) * 255, f(8) * 255, f(4) * 255])
}

/** Without a print profile; the interface says "computed" wherever it shows it. */
export function cmyk(color: string): [number, number, number, number] {
  const [r, g, b] = rgb(color).map((v) => v / 255)
  const k = 1 - Math.max(r, g, b)
  if (k >= 1) return [0, 0, 0, 100]
  const f = (v: number) => Math.round(((1 - v - k) / (1 - k)) * 100)
  return [f(r), f(g), f(b), Math.round(k * 100)]
}

function lab(color: string): [number, number, number] {
  const [r, g, b] = rgb(color).map(toLinear)
  const x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
  const y = 0.2126 * r + 0.7152 * g + 0.0722 * b
  const z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
  const f = (t: number) => (t > 216 / 24389 ? Math.cbrt(t) : ((24389 / 27) * t + 16) / 116)
  return [116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))]
}

/** CIEDE2000: below 1 nobody sees it, below about 5 it reads as the same colour slightly off. */
export function deltaE(a: string, b: string): number {
  const [L1, a1, b1] = lab(a)
  const [L2, a2, b2] = lab(b)
  const rad = Math.PI / 180
  const C1 = Math.hypot(a1, b1)
  const C2 = Math.hypot(a2, b2)
  const Cm = (C1 + C2) / 2
  const G = 0.5 * (1 - Math.sqrt(Cm ** 7 / (Cm ** 7 + 25 ** 7)))
  const a1p = (1 + G) * a1
  const a2p = (1 + G) * a2
  const C1p = Math.hypot(a1p, b1)
  const C2p = Math.hypot(a2p, b2)
  const h = (bb: number, ap: number) => {
    if (bb === 0 && ap === 0) return 0
    const v = Math.atan2(bb, ap) / rad
    return v < 0 ? v + 360 : v
  }
  const h1p = h(b1, a1p)
  const h2p = h(b2, a2p)
  const dLp = L2 - L1
  const dCp = C2p - C1p
  let dhp = 0
  if (C1p * C2p !== 0) {
    dhp = h2p - h1p
    if (dhp > 180) dhp -= 360
    else if (dhp < -180) dhp += 360
  }
  const dHp = 2 * Math.sqrt(C1p * C2p) * Math.sin((dhp / 2) * rad)
  const Lpm = (L1 + L2) / 2
  const Cpm = (C1p + C2p) / 2
  let hpm = h1p + h2p
  if (C1p * C2p !== 0) {
    if (Math.abs(h1p - h2p) > 180) hpm = h1p + h2p < 360 ? (h1p + h2p + 360) / 2 : (h1p + h2p - 360) / 2
    else hpm = (h1p + h2p) / 2
  }
  const T = 1 - 0.17 * Math.cos((hpm - 30) * rad) + 0.24 * Math.cos(2 * hpm * rad) + 0.32 * Math.cos((3 * hpm + 6) * rad) - 0.2 * Math.cos((4 * hpm - 63) * rad)
  const dTheta = 30 * Math.exp(-(((hpm - 275) / 25) ** 2))
  const Rc = 2 * Math.sqrt(Cpm ** 7 / (Cpm ** 7 + 25 ** 7))
  const Sl = 1 + (0.015 * (Lpm - 50) ** 2) / Math.sqrt(20 + (Lpm - 50) ** 2)
  const Sc = 1 + 0.045 * Cpm
  const Sh = 1 + 0.015 * Cpm * T
  const Rt = -Math.sin(2 * dTheta * rad) * Rc
  return Math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))
}

export type Vision = 'normal' | 'deutan' | 'protan' | 'tritan' | 'achromat'
export const VISIONS: Vision[] = ['normal', 'deutan', 'protan', 'tritan', 'achromat']

// Machado, Oliveira, Fernandes 2009, full severity, applied in linear RGB.
const MATRICES: Record<'protan' | 'deutan' | 'tritan', number[][]> = {
  protan: [
    [0.152286, 1.052583, -0.204868],
    [0.114503, 0.786281, 0.099216],
    [-0.003882, -0.048116, 1.051998],
  ],
  deutan: [
    [0.367322, 0.860646, -0.227968],
    [0.280085, 0.672501, 0.047413],
    [-0.01182, 0.04294, 0.968881],
  ],
  tritan: [
    [1.255528, -0.076749, -0.178779],
    [-0.078411, 0.930809, 0.147602],
    [0.004733, 0.691367, 0.3039],
  ],
}

export function simulate(color: string, vision: Vision): string {
  if (vision === 'normal') return color.toUpperCase()
  const lin = rgb(color).map(toLinear)
  if (vision === 'achromat') {
    const v = fromLinear(0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2])
    return toHex([v, v, v])
  }
  const m = MATRICES[vision]
  const out = m.map((row) => Math.min(1, Math.max(0, row[0] * lin[0] + row[1] * lin[1] + row[2] * lin[2])))
  return toHex(out.map(fromLinear) as Rgb)
}

/** The nearest colour of the same hue that reaches `target` on `bg`: darker or lighter, whichever first. */
export function reach(fg: string, bg: string, target: number): string | null {
  if (contrast(fg, bg) >= target) return fg.toUpperCase()
  const [r, g, b] = rgb(fg)
  for (let step = 1; step <= 100; step++) {
    const part = step / 100
    const darker = toHex([r * (1 - part), g * (1 - part), b * (1 - part)])
    if (contrast(darker, bg) >= target) return darker
    const lighter = toHex([r + (255 - r) * part, g + (255 - g) * part, b + (255 - b) * part])
    if (contrast(lighter, bg) >= target) return lighter
  }
  return null
}

export const STEPS = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950] as const
const STEP_LIGHT = [97, 93, 85, 75, 64, 54, 45, 37, 29, 21, 13]

/** A web scale from 50 to 950 around one colour: same hue, lightness in fixed steps, a little less colour at the ends. */
export function scaleOf(color: string): { step: number; hex: string }[] {
  const [h, s] = hsl(color)
  return STEPS.map((step, i) => {
    const l = STEP_LIGHT[i]
    return { step, hex: fromHsl(h, Math.round(s * (l > 90 || l < 20 ? 0.75 : 1)), l) }
  })
}

export function slug(name: string): string {
  const text = name.toLocaleLowerCase().replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss')
  return text.normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'color'
}
