/** Preserve paint order when opening scenes with legacy invalid fractional keys. */
export function normalizeLegacyOrder<T extends { index?: unknown }>(elements: readonly T[]): T[] {
  if (!elements.some(element => typeof element.index === 'string' && /^a\d{5}$/.test(element.index))) {
    return [...elements];
  }
  return elements.map((element, position) => {
    const digits = String(position).padStart(5, '0');
    return { ...element, index: String.fromCharCode(97 + digits.length - 1) + digits };
  });
}
