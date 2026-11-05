// Integer-like semantic ids (FINAL_REPORT.md issue 1).
//
// A JS object puts array-index keys ("0", "7", ...) first, so the TS engine
// cannot reproduce Python's dict order for them. Both implementations reject
// such ids at the render entry with the same message; the cases and messages
// below mirror evodesign/tests/common/test_semantic_ids.py.
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { compare } from '../harness/compare.ts';
import { FIXTURES } from '../harness/fixtures.ts';
import {
  ensure_no_integer_like_semantic_ids,
  integer_like_semantic_ids,
  is_integer_like_id,
} from '../../src/common/semantic_ids.ts';
import { renderExcalidrawManifest } from '../../src/render_engine/workflow.ts';

type Dict = Record<string, unknown>;
interface StageCase { case: string; input: Dict; snapshots: { diagram_manifest: Dict }[]; error: unknown }

const INTEGER_LIKE_CASES: [unknown, boolean][] = [
  ['0', true], ['7', true], ['42', true], ['4294967294', true],
  ['4294967295', false], ['01', false], ['-1', false], ['1.0', false],
  ['1e3', false], [' 1', false], ['', false], ['n1', false], ['1a', false],
  ['１', false], ['٣', false], [7, false], [null, false],
];

describe('is_integer_like_id', () => {
  it.each(INTEGER_LIKE_CASES)('%j -> %s', (value, expected) => {
    expect(is_integer_like_id(value)).toBe(expected);
  });

  it('agrees with how JS orders object keys', () => {
    for (const [value] of INTEGER_LIKE_CASES) {
      if (typeof value !== 'string' || value === '') continue;
      const keys = Object.keys({ z: 0, [value]: 0 });
      expect(keys[0] === value).toBe(is_integer_like_id(value));
    }
  });
});

describe('integer-like semantic ids', () => {
  const structure = {
    nodes: [{ id: 'n_a' }, { id: '2' }, { id: '1' }],
    edges: [{ id: 'edge:2to1' }],
    groups: [{ id: '10' }],
  };
  const layout = { n_a: {}, 2: {}, 1: {}, 10: {}, 3: {}, '2:icon': {} };

  it('reports structure ids, then layout keys', () => {
    // Layout keys come back ascending here (JS order); Python sees "3" last too.
    expect(integer_like_semantic_ids(structure, layout)).toEqual(['2', '1', '10', '3']);
    expect(integer_like_semantic_ids(null, null)).toEqual([]);
  });

  it('raises the same message as Python', () => {
    expect(() => ensure_no_integer_like_semantic_ids(structure, layout)).toThrow(
      "Semantic ids must not be bare integers (got '2', '1', '10', '3'); use descriptive ids such as 'n_login'.",
    );
  });
});

describe('render entry', () => {
  const dir = join(FIXTURES, 'stages');
  const files = readdirSync(dir).filter((name) => name.endsWith('.json') && !name.startsWith('_')).sort();
  const load = (file: string) => JSON.parse(readFileSync(join(dir, file), 'utf-8')) as StageCase;

  it('rejects a fixture whose first node id is renamed to "1"', () => {
    const fixture = load(files[0]);
    const structure = fixture.input.structure_instantiation as { nodes: { id: string }[] };
    const old = structure.nodes[0].id;
    const text = JSON.stringify(fixture.input).replaceAll(JSON.stringify(old), '"1"');
    expect(() => renderExcalidrawManifest(JSON.parse(text) as Dict)).toThrow("must not be bare integers (got '1')");
  });

  it.each(files)('%s still renders through run() exactly like Python', (file) => {
    const fixture = load(file);
    if (fixture.error) return;
    const expected = fixture.snapshots[fixture.snapshots.length - 1].diagram_manifest;
    expect(compare(expected, renderExcalidrawManifest(fixture.input)).diffs).toEqual([]);
  });
});
