import { describe, expect, it } from 'vitest'

import { contrast } from './color'
import { fromAi, type AiDirection } from './generate'

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
