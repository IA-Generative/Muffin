// Les collections que la personne consulte le plus d'abord (#286), la plus consultée en tête ; les autres gardent leur
// ordre. Ne retire jamais rien : c'est un ordre de proposition, pas un filtre.
export function habitualFirst<T extends { id: string }>(items: T[], habitualIds: string[]): T[] {
  if (habitualIds.length === 0) return items
  const rank = new Map(habitualIds.map((id, index) => [id, index]))
  const habitual = items.filter((item) => rank.has(item.id)).sort((a, b) => rank.get(a.id)! - rank.get(b.id)!)
  return [...habitual, ...items.filter((item) => !rank.has(item.id))]
}
