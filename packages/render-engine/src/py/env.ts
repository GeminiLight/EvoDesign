// ``os.environ`` / ``os.getenv`` replacement (MIGRATION_PLAN.md §4).
//
// Python reads feature switches such as ``EVODESIGN_ARCH_DESIGN_SYSTEM`` from
// the process environment. In the browser there is no ``process.env``, so the
// port reads an override table first (``setEnv``), then ``process.env`` when
// it exists, and finally the default the Python call site passes.
//
// Translate ``os.getenv("NAME", "1")`` as ``getEnv('NAME', '1')`` — always
// pass the same default literal as Python.

const overrides = new Map<string, string | null>();

function processEnv(): Record<string, string | undefined> | undefined {
  const proc = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
  return proc?.env;
}

/** ``os.getenv(name, default)``; returns ``null`` for Python ``None``. */
export function getEnv(name: string): string | null;
export function getEnv(name: string, defaultValue: string): string;
export function getEnv(name: string, defaultValue: string | null): string | null;
export function getEnv(name: string, defaultValue: string | null = null): string | null {
  if (overrides.has(name)) {
    const value = overrides.get(name)!;
    return value === null ? defaultValue : value;
  }
  const value = processEnv()?.[name];
  return value === undefined ? defaultValue : value;
}

/** Override a variable for this runtime (``null`` = unset, falls back to the default). */
export function setEnv(name: string, value: string | null): void {
  overrides.set(name, value);
}

/** Remove an override so ``process.env`` (if any) is consulted again. */
export function clearEnv(name?: string): void {
  if (name === undefined) overrides.clear();
  else overrides.delete(name);
}
