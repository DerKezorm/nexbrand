// A client in the sidebar: its small logo when it has one, else its loud colours (a set that starts with its grounds
// showed three blacks), else what the set brings first.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { ClientFace } from '../api/client'
import { Swatch } from '../components/Sidebar'
import type { BrandLogo } from '../lib/brand'

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

let root: Root
let host: HTMLDivElement

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
})

const grounds = ['#0A0B0E', '#12141A', '#181B22', '#ECEEF3']
const mark: BrandLogo = { id: 'l1', name: 'nexapps', media: 'markabcd12', fg: '#FFFFFF', accent: '#E11D2F', ground: '#0A0B0E', compact: true }

function show(face: ClientFace) {
  act(() => root.render(<Swatch client={{ face, color: '#60a5fa' }} />))
  return [...host.querySelectorAll<HTMLElement>('span > span')].map((s) => s.style.background)
}

describe('Swatch', () => {
  it('shows the small logo when the client has one', () => {
    show({ colors: grounds, accents: ['#E11D2F'], logo: null, mark })
    const img = host.querySelector('img')
    expect(img?.getAttribute('src')).toBe('/api/media/markabcd12?preview=1')
  })

  it('takes the loud colours before the grounds', () => {
    expect(show({ colors: grounds, accents: ['#E11D2F', '#23D19E'], logo: null })).toEqual(['rgb(225, 29, 47)', 'rgb(35, 209, 158)'])
    expect(host.querySelector('img')).toBeNull()
  })

  it('falls back to the set and then to the client colour', () => {
    expect(show({ colors: grounds, accents: [], logo: null })).toEqual(['rgb(10, 11, 14)', 'rgb(18, 20, 26)', 'rgb(24, 27, 34)'])
    expect(show({ colors: [], logo: null })).toEqual(['rgb(96, 165, 250)'])
  })
})
