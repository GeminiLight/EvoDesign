// Snapshots of filesystem inputs captured at function entry from the original
// Python tests (tools/wp34/capture_runtime_inputs.py). Keep recorded path strings
// for hashes and error messages, while serving bytes from a disposable MemoryFS.
import { readFileSync } from 'node:fs';
import { basename, dirname, join } from 'node:path';
import { getFS, setFS, MemoryFS, type RuntimeFS } from '../../src/py/fs.ts';
import { PACKAGE_ROOT, type Vector } from './fixtures.ts';

const snapshots = JSON.parse(readFileSync(join(PACKAGE_ROOT, 'test/fixtures/runtime_inputs.json'), 'utf8')) as Record<string, Record<string, Record<string, string>[]>>;
function pathIn(value: unknown): string | null {
  if (typeof value === 'string' && value.includes('/pytest-of-') && value.includes('/pytest-')) return value;
  if (Array.isArray(value)) { for (const item of value) { const result = pathIn(item); if (result) return result; } }
  else if (value && typeof value === 'object') { for (const item of Object.values(value)) { const result = pathIn(item); if (result) return result; } }
  return null;
}
export function installPytestFiles(module: string, func: string, vector: Vector, vectors: Vector[]): () => void {
  if (vector.source !== 'pytest' || !snapshots[func] || !module.includes('agentic_system')) return () => {};
  const path = pathIn(vector.args);
  if (!path) return () => {};
  const folder = dirname(path);
  const test = basename(folder);
  const entries = snapshots[func][test];
  if (!entries) return () => {};
  const index = vectors.filter(v => v.line < vector.line && v.source === 'pytest' && pathIn(v.args)?.startsWith(folder + '/')).length;
  const files = entries[index];
  if (!files) throw new Error(`Missing filesystem snapshot for ${test}/${func}/${index}`);
  const original = getFS();
  const memory = new MemoryFS();
  memory.mkdirp(folder);
  for (const [name, base64] of Object.entries(files)) memory.writeBytes(join(folder, name), Buffer.from(base64, 'base64'));
  const overlay = new Proxy(original, {
    get(target, prop) {
      const member = target[prop as keyof RuntimeFS];
      if (typeof member !== 'function') return member;
      return (...args: unknown[]) => {
        const owner = typeof args[0] === 'string' && (args[0] === folder || args[0].startsWith(folder + '/')) ? memory : target;
        return (owner[prop as keyof RuntimeFS] as (...values: unknown[]) => unknown).apply(owner, args);
      };
    },
  });
  setFS(overlay);
  return () => { setFS(original); };
}
