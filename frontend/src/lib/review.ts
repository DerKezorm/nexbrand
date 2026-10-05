/** Small rules of a review, shared by the agency's panel and the client's page. */

/** The name a comment shows: the one given, or the page's words for none (stored as "-" before 05.10.2026). */
export function shownAuthor(author: string, none: string): string {
  const name = author.trim()
  return name && name !== '-' ? name : none
}

/** The letter of the n-th direction: A, B, C, D. */
export function directionLetter(index: number): string {
  return String.fromCharCode(65 + index)
}

/** What the agency may do with a review or a public page: see and copy the link from write up, withdraw or end it
 * as a manager or as the one who made it. The server decides the same; the page only leaves out what would fail. */
export function linkRights(role: 'read' | 'write' | 'manage' | null | undefined, mine: boolean): { link: boolean; make: boolean; end: boolean } {
  const writes = role === 'write' || role === 'manage'
  return { link: writes, make: writes, end: role === 'manage' || (writes && mine) }
}
