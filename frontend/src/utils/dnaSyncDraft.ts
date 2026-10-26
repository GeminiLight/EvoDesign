import type { CabinId, Rule } from '../types/dna';
import { readLocalStorage, writeLocalStorage, removeLocalStorage } from './safeLocalStorage';
export type DnaRules = Record<CabinId, Rule[]>;
type Draft = { rules: DnaRules; marker: string; durable: boolean };
const latest = new Map<string, Draft>();

export function rememberDnaDraft(key: string, rules: DnaRules): Draft {
  const marker = JSON.stringify({ rules, at: Date.now() });
  const durable = writeLocalStorage(key, marker);
  if (!durable) removeLocalStorage(key); // Never leave an older outbox entry behind.
  const draft = { rules, marker, durable };
  latest.set(key, draft);
  return draft;
}
export function readDnaDraft(key: string): Draft | null {
  if (latest.has(key)) return latest.get(key)!;
  const marker = readLocalStorage(key);
  if (!marker) return null;
  try {
    const parsed = JSON.parse(marker);
    const rules = parsed.rules ?? parsed; // Recover drafts written before the envelope.
    if (!['structure', 'style', 'layout'].every(id => Array.isArray(rules[id]))) return null;
    return { rules, marker, durable: true };
  } catch { return null; }
}
export function isLatestDnaDraft(key: string, draft: Draft): boolean {
  return latest.get(key) === draft;
}
export function clearDnaDraft(key: string, draft: Draft): void {
  if (latest.get(key) === draft) latest.delete(key);
  if (readLocalStorage(key) === draft.marker) removeLocalStorage(key);
}
/** Ignore server IDs/timestamps when deciding if a recovered preference was saved. */
export function sameDnaPreferences(left: DnaRules, right: DnaRules): boolean {
  const normalize = (rules: DnaRules) => ['structure', 'style', 'layout'].map(id =>
    rules[id as CabinId].map(rule => [rule.title, rule.preview, rule.enabled, rule.pinned])
      .sort((a, b) => String(a[0]).localeCompare(String(b[0]))));
  return JSON.stringify(normalize(left)) === JSON.stringify(normalize(right));
}
