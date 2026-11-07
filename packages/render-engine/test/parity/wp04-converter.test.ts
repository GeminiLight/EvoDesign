// WP04 stage parity for InstantiationToExcalidrawConverter.convert().
//
// Class methods have no function vectors (self is not serializable), so the
// converter is verified against the stage snapshots instead: for every
// fixtures/stages/<case>.json, feed Python's ``excalidraw_add_icon_urls``
// snapshot (its layout_instantiation) plus input.structure_instantiation into
// the TS converter, exactly like RenderWorkflow._run_excalidraw_converter
// (audit_layout_instantiation, then convert()), and compare with Python's
// ``excalidraw_convert`` snapshot (manifest and the unchanged layout).
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { compare } from '../harness/compare.ts';
import { FIXTURES } from '../harness/fixtures.ts';
import { InstantiationToExcalidrawConverter } from '../../src/render_engine/excalidraw/converter.ts';
import { audit_layout_instantiation } from '../../src/render_engine/shared/render_audit.ts';

type Dict = Record<string, unknown>;
interface Snapshot { node: string; layout_instantiation: Dict; diagram_manifest: Dict }
interface StageCase { case: string; input: Dict; snapshots: Snapshot[] }

const dir = join(FIXTURES, 'stages');
const files = readdirSync(dir).filter((name) => name.endsWith('.json') && !name.startsWith('_')).sort();

describe('WP04 converter stage parity (excalidraw_add_icon_urls -> excalidraw_convert)', () => {
  it('has all stage cases', () => {
    expect(files.length).toBe(112);
  });

  for (const file of files) {
    it(file.replace(/\.json$/, ''), () => {
      const fixture = JSON.parse(readFileSync(join(dir, file), 'utf-8')) as StageCase;
      const before = fixture.snapshots.find((s) => s.node === 'excalidraw_add_icon_urls');
      const expected = fixture.snapshots.find((s) => s.node === 'excalidraw_convert');
      expect(before, 'missing excalidraw_add_icon_urls snapshot').toBeTruthy();
      expect(expected, 'missing excalidraw_convert snapshot').toBeTruthy();

      const layout = structuredClone(before!.layout_instantiation);
      const structure = structuredClone(fixture.input.structure_instantiation) as Dict;
      audit_layout_instantiation(layout, structure);
      const manifest = new InstantiationToExcalidrawConverter(layout, structure).convert();

      const result = compare(
        { layout_instantiation: expected!.layout_instantiation, diagram_manifest: expected!.diagram_manifest },
        { layout_instantiation: layout, diagram_manifest: manifest },
      );
      expect(result.diffs, result.diffs.join('\n')).toEqual([]);
    });
  }
});
