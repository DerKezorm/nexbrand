import { describe, expect, it } from 'vitest'

import { directionLetter, linkRights, shownAuthor } from './review'

describe('a review', () => {
  it('names a comment without a name in words, also one stored with a dash', () => {
    expect(shownAuthor('', 'No name')).toBe('No name')
    expect(shownAuthor('-', 'No name')).toBe('No name')
    expect(shownAuthor('  ', 'No name')).toBe('No name')
    expect(shownAuthor('Kim', 'No name')).toBe('Kim')
  })

  it('letters its directions', () => {
    expect([0, 1, 2, 3].map(directionLetter)).toEqual(['A', 'B', 'C', 'D'])
  })

  it('shows the link from write up, and lets the maker or a manager end it (A2, A3)', () => {
    expect(linkRights('read', false)).toEqual({ link: false, make: false, end: false })
    expect(linkRights('read', true)).toEqual({ link: false, make: false, end: false })
    expect(linkRights('write', false)).toEqual({ link: true, make: true, end: false })
    expect(linkRights('write', true)).toEqual({ link: true, make: true, end: true })
    expect(linkRights('manage', false)).toEqual({ link: true, make: true, end: true })
    expect(linkRights(null, false)).toEqual({ link: false, make: false, end: false })
  })
})
