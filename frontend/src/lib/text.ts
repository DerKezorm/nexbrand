/** A long text for a button's name: whole up to `most` characters, else cut after the last whole word with an
 * ellipsis. Cutting at a fixed count left "the height of the" as "the height de" (F32). */
export function shorten(text: string, most = 48): string {
  const clean = text.replace(/\s+/g, ' ').trim()
  if (clean.length <= most) return clean
  const head = clean.slice(0, most)
  const space = head.lastIndexOf(' ')
  // One very long word: cut inside it rather than leave nothing.
  const cut = space > most / 2 ? head.slice(0, space) : head
  return cut.replace(/[\s,.;:]+$/, '') + '…'
}
