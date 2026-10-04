import { describe, expect, it } from 'vitest'

import type { BrandSet } from './brand'
import { check } from './checks'
import { cmyk, contrast, deltaE, hsl, luminance, reach, scaleOf, simulate, type Vision } from './color'

// The server's files, read when the tests run (from the frontend folder). A static import would put them into the
// app's type check, and the image build has no backend/tests: it stopped there on the first deploy (04.10.2026).
type Files = { readFileSync: (file: string, encoding: string) => string }
const fsName = 'node:fs'
const files = (await import(/* @vite-ignore */ fsName)) as Files
const read = (name: string): unknown => JSON.parse(files.readFileSync(`../backend/tests/data/${name}`, 'utf-8'))
const colorCases = read('color_cases.json') as {
  colors: unknown
  pairs: { a: string; b: string; contrast: number; delta_e: number; reach: string }[]
}
const checkCases = read('check_cases.json') as { sets: unknown[]; hints: unknown[] }

/** The browser and the server compute the same numbers: both are held to the files the server writes. */
describe('colour arithmetic, as the server does it', () => {
  const colors = colorCases.colors as Record<string, { luminance: number; hsl: number[]; cmyk: number[]; simulate: Record<string, string>; scale: string[] }>

  it.each(Object.keys(colors))('%s', (hex) => {
    const want = colors[hex]
    expect(luminance(hex)).toBeCloseTo(want.luminance, 6)
    expect(hsl(hex)).toEqual(want.hsl)
    expect(cmyk(hex)).toEqual(want.cmyk)
    for (const [vision, value] of Object.entries(want.simulate)) expect(simulate(hex, vision as Vision)).toBe(value)
    expect(scaleOf(hex).map((s) => s.hex)).toEqual(want.scale)
  })

  it('every pair: contrast, distance and the nearest passing colour', () => {
    for (const pair of colorCases.pairs) {
      expect(contrast(pair.a, pair.b)).toBeCloseTo(pair.contrast, 6)
      expect(deltaE(pair.a, pair.b)).toBeCloseTo(pair.delta_e, 5)
      expect(reach(pair.a, pair.b, 4.5)).toBe(pair.reach)
    }
  })
})

describe('the checks, as the server words them', () => {
  it.each(checkCases.sets.map((set, i) => [i, set] as const))('set %i', (i, set) => {
    const hints = check(set as unknown as BrandSet)
    expect(hints).toEqual(checkCases.hints[i])
  })
})
