import type { CabinId, Rule } from '../types/dna';

export type DnaLibraryFilters = {
  category: 'all' | CabinId;
  query: string;
  status: 'all' | 'enabled' | 'disabled';
};

export const emptyDnaFilters: DnaLibraryFilters = { category: 'all', query: '', status: 'all' };

/** Keep category identity even when imported rules share a numeric ID. */
export function filterDnaPreferences(library: Record<CabinId, Rule[]>, filters: DnaLibraryFilters) {
  const query = filters.query.trim().toLocaleLowerCase();
  return (['structure', 'style', 'layout'] as const)
    .filter(cabinId => filters.category === 'all' || filters.category === cabinId)
    .flatMap(cabinId => library[cabinId].map(rule => ({ cabinId, rule })))
    .filter(({ rule }) => (!query || `${rule.title} ${rule.preview}`.toLocaleLowerCase().includes(query))
      && (filters.status === 'all' || rule.enabled === (filters.status === 'enabled')))
    .sort((a, b) => Number(b.rule.enabled) - Number(a.rule.enabled)
      || Number(b.rule.pinned) - Number(a.rule.pinned) || b.rule.usageCount - a.rule.usageCount);
}
