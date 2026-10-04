const COLORS = ['#60a5fa', '#f472b6', '#4ade80', '#fbbf24', '#a78bfa', '#2dd4bf', '#fb923c', '#f87171']

/** Everyone gets a colour of their own, the same in every browser: it comes from the name. */
export function personColor(name: string): string {
  let hash = 0
  for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) >>> 0
  return COLORS[hash % COLORS.length]
}
