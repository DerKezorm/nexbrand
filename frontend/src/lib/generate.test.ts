import { describe, expect, it } from 'vitest'

import type { BrandColor, BrandSet } from './brand'
import { check, type Hint } from './checks'
import { contrast, deltaE, fromHsl, hsl } from './color'
import { catalogEntry } from './fonts'
import { fromAi, oneColor, rolesFor, shortfall, startRules, startShortfall, typeScale, wordmarks, type AiDirection } from './generate'

const NAMES = { primary: 'Primary', accent: 'Accent', second: 'Second', paper: 'Paper', stone: 'Stone', ink: 'Ink', white: 'White', light: 'Light', dark: 'Dark' }

function direction(change: Partial<AiDirection>): AiDirection {
  return { label: 'A', why: 'because', hue: 210, accent_hue: 30, saturation: 60, mood: 'calm', head: 'fraunces', body: 'inter', ...change }
}

describe('directions from the AI', () => {
  it('the main colour reaches 4.5:1 with white and on the light ground, whatever hue the model said', () => {
    for (let hue = 0; hue < 360; hue += 15) {
      for (const saturation of [20, 55, 90]) {
        const [made] = fromAi([direction({ hue, saturation })], NAMES)
        const primary = made.colors[0].hex
        const paper = made.colors[2].hex
        expect(contrast(primary, '#FFFFFF'), `hue ${hue}`).toBeGreaterThanOrEqual(4.5)
        expect(contrast(primary, paper), `hue ${hue}`).toBeGreaterThanOrEqual(4.5)
      }
    }
  })

  it('keeps the words of the AI and falls back for fonts and moods it does not know', () => {
    const [made] = fromAi([direction({ label: 'Wood oven', why: 'warm', mood: 'sinister', head: 'comic-sans', body: 'x' })], NAMES)
    expect(made.label).toBe('Wood oven')
    expect(made.why).toBe('warm')
    expect(made.mood).toBe('calm')
    expect(made.head).not.toBe('comic-sans')
    expect(made.body).not.toBe('x')
  })

  it('makes at most three, named a, b and c', () => {
    const made = fromAi([1, 2, 3, 4, 5].map((n) => direction({ hue: n * 40 })), NAMES)
    expect(made.map((d) => d.id)).toEqual(['a', 'b', 'c'])
  })
})

describe('a new client starts without hints about what nexbrand made itself (F24)', () => {
  const labels = { positive: 'Word mark', negative: 'Word mark negative', monogram: 'Monogram' }
  const scaleNames = { h1: 'H1', h2: 'H2', h3: 'H3', lead: 'Lead', body: 'Body', small: 'Small' }
  /** The set the workbench builds "with one colour", as `NewClientPage` does it: neutrals, white, word marks, sizes,
   * fonts and the first rules. */
  const workbench = (colors: BrandColor[]): BrandSet => ({
    colors,
    fonts: [catalogEntry('fraunces', 'Headings'), catalogEntry('inter', 'Text')],
    logos: wordmarks('Example', colors, 'Fraunces', labels),
    scale: typeScale(17, 1.25, 'Fraunces', 'Inter', scaleNames),
    rules: startRules(colors, { clear: 'Keep clear', distort: 'Do not distort' }),
    samples: [],
  })
  /** A hint the chosen colour brings itself: it does not read on white, or white does not read on it. Every other hint
   * is about something nexbrand made (paper, stone, ink, word marks, rules, sizes) and must not be there. */
  const ofTheColour = (hint: Hint, start: string) => {
    const about = (hint.colors ?? []).join('/')
    if (['white_on', 'ground_large_only', 'ground_unreadable'].includes(hint.code) && about === 'Primary') return true
    if (hint.code === 'primary_as_text' && about === 'Primary/White') return true
    // On the off-white only where the workbench says so beside the colour, with the same number (decided 06.10.2026).
    const short = startShortfall(start, NAMES)
    return hint.code === 'primary_as_text' && about === 'Primary/Paper' && short !== null && hint.ratio === Math.floor(short.ratio * 100 + 1e-9) / 100
  }

  it('the default colour of "with one colour" starts without a single hint, and as it is', () => {
    const made = oneColor('#2E7D5B', NAMES)
    expect(check(workbench(made)).filter((h) => h.level !== 'info')).toEqual([])
    // The off-white is chosen so the colour keeps reading on it; nothing had to be darkened.
    expect(made[0].hex).toBe('#2E7D5B')
  })

  it('whatever colour it starts from, every hint is about that colour, none about what nexbrand made', () => {
    let starts = 0
    for (let hue = 0; hue < 360; hue += 5)
      for (const saturation of [10, 25, 40, 55, 70, 85, 100])
        for (const light of [15, 25, 32, 38, 44, 50, 58, 66]) {
          const start = fromHsl(hue, saturation, light)
          const made = oneColor(start, NAMES)
          const hints = check(workbench(made)).filter((h) => h.level !== 'info')
          expect(hints.filter((h) => !ofTheColour(h, start)), start).toEqual([])
          // The main colour made darker by hand afterwards, as the checker did (#b4651e, then #8f4a14): the word marks
          // follow it and nexbrand's own neutrals stay apart. How the new colour meets them is the new colour's.
          const darker = made.map((c) => (c.name === 'Primary' ? { ...c, hex: fromHsl(hue, saturation, Math.max(8, light - 10)) } : c))
          const later = check(workbench(darker)).filter((h) => h.logo || (h.code === 'nearly_same' && !h.colors?.includes('Primary')))
          expect(later, start).toEqual([])
          expect(deltaE(made[1].hex, '#FFFFFF'), start).toBeGreaterThanOrEqual(4)
          starts++
        }
    expect(starts).toBe(72 * 7 * 8)
    // 4032 starting colours, each checked twice: 0.8 s alone, over 5 s beside a test run of the server.
  }, 120_000)

  it('makes an off-white the colour reads on wherever one exists: then the workbench has nothing to say', () => {
    let kept = 0
    for (let hue = 0; hue < 360; hue += 2)
      for (const saturation of [40, 60, 80, 100])
        for (let light = 20; light <= 50; light += 1) {
          const start = fromHsl(hue, saturation, light)
          const [h] = hsl(start)
          const possible = contrast(start, '#FFFFFF') >= 4.5 && [96, 95.5, 95].some((l) => [60, 80, 100].some((s) => deltaE(fromHsl(h, s, l), '#FFFFFF') >= 4.5 && contrast(start, fromHsl(h, s, l)) >= 4.5))
          if (!possible) continue
          expect(startShortfall(start, NAMES), start).toBeNull()
          kept++
        }
    expect(kept).toBeGreaterThan(100)
  })
})

describe('a colour the client brings stays as it is (decided 06.10.2026)', () => {
  it('"with one colour" never changes the colour; where it misses 4.5:1 on the off-white, it says how far and what would reach', () => {
    let short = 0
    for (let hue = 0; hue < 360; hue += 5)
      for (const saturation of [40, 60, 80, 100])
        for (const light of [20, 30, 40, 44, 48, 50, 60, 70]) {
          const start = fromHsl(hue, saturation, light)
          const made = oneColor(start, NAMES)
          expect(made[0].hex, start).toBe(start)
          const paper = made[1].hex
          const found = startShortfall(start, NAMES)
          if (contrast(start, paper) >= 4.5) {
            expect(found, start).toBeNull()
            continue
          }
          short++
          expect(found?.color, start).toBe(start)
          expect(found?.ratio, start).toBeCloseTo(contrast(start, paper), 6)
          expect(found?.ground, start).toBe(paper)
          // Taken, the suggestion reads on its own off-white and on white, and nothing more is said about it.
          const better = found!.better!
          expect(startShortfall(better, NAMES), `${start} -> ${better}`).toBeNull()
          expect(contrast(better, '#FFFFFF'), start).toBeGreaterThanOrEqual(4.5)
          // The same hue, only darker.
          if (saturation >= 40 && light >= 30) expect(Math.abs(((hsl(better)[0] - hsl(start)[0] + 540) % 360) - 180), `${start} -> ${better}`).toBeLessThan(4)
          expect(contrast(better, '#000000'), start).toBeLessThan(contrast(start, '#000000'))
        }
    expect(short).toBeGreaterThan(100)
  })

  it('the suggestion is the one of the contrast checker where the colour reads on white', () => {
    // #D04343 reads on white (4.60:1), not on its off-white: the nearest of its hue that does, as `reach` gives it.
    const found = startShortfall('#D04343', NAMES)!
    expect(Math.floor(found.ratio * 100) / 100).toBe(4.13)
    expect(found.better).toBe('#C43F3F')
    expect(oneColor('#D04343', NAMES)[0].hex).toBe('#D04343')
  })

  it('a pale or greyish colour gets a suggestion that also reads on the off-white it brings along', () => {
    for (const start of ['#A8A09F', '#E8CCC9', '#F4C3BE']) {
      // One step is not enough here: the darker colour gets an off-white of its own, on which it misses again.
      const once = shortfall(oneColor(start, NAMES))!.better!
      expect(shortfall(oneColor(once, NAMES)), start).not.toBeNull()
      const better = startShortfall(start, NAMES)!.better!
      expect(shortfall(oneColor(better, NAMES)), `${start} -> ${better}`).toBeNull()
    }
  })

  it('the colours of a picture keep their values; a main colour that misses on the light one is named with a suggestion', () => {
    const roles = rolesFor(['#F6EFE4', '#D9822B', '#2B2A28', '#6F8F55'], NAMES)
    expect(roles.map((c) => c.hex)).toEqual(['#D9822B', '#6F8F55', '#F6EFE4', '#2B2A28'])
    const found = shortfall(roles)!
    expect(found.color).toBe('#D9822B')
    expect(found.ground).toBe('#F6EFE4')
    expect(found.ratio).toBeCloseTo(contrast('#D9822B', '#F6EFE4'), 6)
    expect(contrast(found.better!, '#F6EFE4')).toBeGreaterThanOrEqual(4.5)
    // Taken, only the main colour changes, and then nothing more is said.
    const taken = roles.map((c) => (c.role === 'primary' ? { ...c, hex: found.better! } : c))
    expect(shortfall(taken)).toBeNull()
    // A picture without a light colour has no light ground to speak of; one without a main colour neither.
    expect(shortfall(rolesFor(['#2B2A28', '#6F8F55', '#1A3A5A'], NAMES))).toBeNull()
    expect(shortfall([{ name: 'Light', hex: '#F6EFE4', role: 'neutral' }])).toBeNull()
  })
})
