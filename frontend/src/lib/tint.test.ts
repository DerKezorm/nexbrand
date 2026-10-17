// Small things that are rules, not pages: the letters in the circles of people and teams are readable in
// both modes (measured from the style sheet itself), a button's name is cut after a whole word, a tab names
// its page, and a moment is written one way.
import { describe, expect, it } from 'vitest'

import { contrast } from './color'
import { CLIENT_COLORS, TEAM_COLORS } from './palette'
import { personColor } from './person'
import { shorten } from './text'
import { moment } from './time'
import { pageTitle } from './title'

type Files = { readFileSync: (file: string, encoding: string) => string }
const fsName = 'node:fs'
const files = (await import(/* @vite-ignore */ fsName)) as Files
const css = files.readFileSync('src/styles/index.css', 'utf-8')

/** The value of a custom property in a block of the style sheet (the dark one is `@theme`). */
function token(block: RegExp, name: string): string {
  const body = css.match(block)?.[1] ?? ''
  const found = body.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`))
  if (!found) throw new Error(`no ${name}`)
  return found[1]
}
const DARK = /@theme\s*\{([\s\S]*?)\n\}/
const LIGHT = /:root\[data-theme='light'\]\s*\{([\s\S]*?)\n\}/

/** `color-mix(in srgb, var(--tint) N%, X)` of a rule, as numbers: the share of the tint and the other colour. */
function mixOf(rule: RegExp, property: 'background' | 'color'): { share: number; other: string } {
  const body = css.match(rule)?.[1] ?? ''
  const found = body.match(new RegExp(`${property}:\\s*color-mix\\(in srgb, var\\(--tint\\) (\\d+)%, (.+?)\\);`))
  if (!found) throw new Error(`no ${property} in ${rule}`)
  return { share: Number(found[1]) / 100, other: found[2].trim() }
}

const hex = (rgb: number[]) => '#' + rgb.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('')
const channels = (color: string) => [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16))
/** What a browser draws for color-mix in srgb: each channel mixed straight, as written. */
function mix(tint: string, share: number, other: string): string {
  const a = channels(tint)
  const b = channels(other)
  return hex(a.map((v, i) => v * share + b[i] * (1 - share)))
}

describe('the letters in the circles of people and teams', () => {
  const base = /\.nc-tint\s*\{([\s\S]*?)\}/
  const light = /:root\[data-theme='light'\] \.nc-tint\s*\{([\s\S]*?)\}/
  // Every colour a person, a team or a client can have.
  const people = [...new Set(['alex', 'robin', 'sam', 'jona', 'mila', 'toni', 'kim', 'lou', 'b', 'x'].map(personColor))]
  const tints = [...new Set([...people, ...CLIENT_COLORS, ...TEAM_COLORS])]

  for (const [mode, block, rule] of [['dark', DARK, base], ['light', LIGHT, light]] as const) {
    it(`reach 4.5 to 1 in ${mode} mode for every colour`, () => {
      const card = token(block, 'color-ink-850')
      const ground = mixOf(base, 'background')
      expect(ground.other).toBe('var(--color-ink-850)')
      const ink = mixOf(rule, 'color')
      const worst = Math.min(...tints.map((tint) => contrast(mix(tint, ink.share, ink.other), mix(tint, ground.share, card))))
      expect(worst).toBeGreaterThanOrEqual(4.5)
    })
  }
})

describe('a long name for a button', () => {
  it('is cut after a whole word, with an ellipsis', () => {
    const rule = 'Um das Logo herum mindestens die Höhe des Buchstabens x frei lassen'
    const cut = shorten(rule)
    expect(cut.endsWith('…')).toBe(true)
    expect(cut.length).toBeLessThanOrEqual(49)
    // Every word of it is a whole word of the rule.
    const words = cut.slice(0, -1).split(' ')
    expect(rule.split(' ').slice(0, words.length)).toEqual(words)
  })

  it('stays whole when it is short, and a single long word is still cut', () => {
    expect(shorten('Text auf Grund')).toBe('Text auf Grund')
    expect(shorten('x'.repeat(80), 40)).toBe('x'.repeat(40) + '…')
  })
})

describe('the title of a tab', () => {
  it('names the page and the app, the pages a client sees only the client', () => {
    expect(pageTitle('Example Bakery')).toBe('Example Bakery · nexbrand')
    expect(pageTitle('Example Bakery', true)).toBe('Example Bakery')
    expect(pageTitle('')).toBe('nexbrand')
  })
})

describe('a moment', () => {
  it('is the day as lists show it, with hours and minutes and no seconds', () => {
    const at = '2026-10-04T20:35:59Z'
    const written = moment(at, 'de')
    expect(written).toContain(new Date(at).toLocaleDateString('de'))
    expect(written).not.toMatch(/\d{1,2}:\d{2}:\d{2}/)
    expect(written).toMatch(/\d{2}:\d{2}/)
  })
})

describe('asking before something goes', () => {
  it('uses the family dialog everywhere, never the browser one', () => {
    type Dirs = { readdirSync: (dir: string, options: { recursive: true }) => string[] }
    const dirs = files as unknown as Dirs
    const sources = dirs.readdirSync('src', { recursive: true }).filter((name) => /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name))
    expect(sources.length).toBeGreaterThan(40)
    const asking = sources.filter((name) => /(^|[^\w.])(window\.)?confirm\(/.test(files.readFileSync(`src/${name}`, 'utf-8')))
    expect(asking).toEqual([])
  })
})

describe('status words in their colour', () => {
  // "checked", "nearly right", an error line: the colour as text on a card, on the page and on its own wash.
  const words = ['color-ok-500', 'color-warn-500', 'color-bad-500', 'color-accent-400', 'color-magenta-text', 'color-gelb-text']
  for (const [mode, block] of [['dark', DARK], ['light', LIGHT]] as const) {
    it(`reach 4.5 to 1 in ${mode} mode`, () => {
      const grounds = ['color-ink-850', 'color-ink-950'].map((name) => token(block, name))
      const low: string[] = []
      for (const word of words) {
        const ink = token(block, word)
        for (const ground of grounds) {
          for (const share of [0, 0.08, 0.12, 0.15]) {
            const ratio = contrast(ink, mix(ink, share, ground))
            if (ratio < 4.5) low.push(`${word} on ${ground} ${share}: ${ratio.toFixed(2)}`)
          }
        }
      }
      expect(low).toEqual([])
    })
  }
})
