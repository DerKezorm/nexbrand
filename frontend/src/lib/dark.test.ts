import { describe, expect, it } from 'vitest'

import type { BrandColor } from './brand'
import { schemeOf } from './brand'
import { darkHints } from './checks'
import { suggestDark } from './generate'

const names = { night: 'Night', nightSurface: 'Night surface', brightOf: (name: string) => `${name} light`, note: 'For dark mode.' }
const c = (name: string, hex: string, role: BrandColor['role'] = 'neutral'): BrandColor => ({ name, hex, role })

describe('a suggested dark mode', () => {
  it('takes the palette where it can', () => {
    const colors = [c('Red', '#E40000', 'primary'), c('White', '#FFFFFF'), c('Black', '#000000'), c('Dark grey', '#333333'), c('Grey', '#8A8A8A')]
    const { dark, add } = suggestDark(colors, names)
    // Red on black is 4.4:1: a lighter red comes along for links and buttons.
    expect(add.map((x) => x.name)).toEqual(['Red light'])
    expect(dark).toMatchObject({ ground: 'Black', surface: 'Dark grey', text: 'White', primary: 'Red light' })
    expect(darkHints(dark, [...colors, ...add])).toEqual([])
  })

  it('makes what a light palette lacks, and every name it gives is there', () => {
    const colors = [c('Blue', '#0B3D91', 'primary'), c('Paper', '#F7F4EE'), c('Sand', '#D9CBB0')]
    const { dark, add } = suggestDark(colors, names)
    expect(add.map((x) => x.name)).toEqual(['Night', 'Night surface', 'Blue light'])
    const all = [...colors, ...add]
    expect(schemeOf(dark, all)).not.toBeNull()
    expect(dark.primary).toBe('Blue light')
    expect(darkHints(dark, all).filter((h) => h.level === 'bad')).toEqual([])
  })

  it('keeps the main colour (lighter) instead of taking the accent, and quiet text from the neutrals', () => {
    const colors = [c('Green', '#228042', 'primary'), c('Mint', '#49DFCB', 'accent'), c('Paper', '#F2F8F4'), c('Ink', '#1A2E21'), c('White', '#FFFFFF'), c('Stone', '#8FA396')]
    const { dark, add } = suggestDark(colors, names)
    expect(dark.primary).toBe('Green light')
    expect(add.find((x) => x.name === 'Green light')?.role).toBe('secondary')
    expect(colors.find((x) => x.name === dark.muted)?.role).toBe('neutral')
  })

  it('has no scheme when a name is gone', () => {
    const colors = [c('Black', '#000000')]
    expect(schemeOf({ ground: 'Black', surface: 'Black', text: 'Gone', muted: 'Black', primary: 'Black', on_primary: 'Black' }, colors)).toBeNull()
  })
})
