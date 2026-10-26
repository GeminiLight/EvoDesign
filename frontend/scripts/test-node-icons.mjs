import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { test } from 'node:test';
import { generateKeyBetween } from 'fractional-indexing';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const temp = mkdtempSync(path.join(tmpdir(), 'evodesign-icons-'));
const output = path.join(temp, 'icons.mjs');
execFileSync(path.join(root, 'node_modules/.bin/esbuild'), [
  path.join(root, 'src/utils/nodeIcons.ts'), '--bundle', '--format=esm', '--platform=node',
  `--outfile=${output}`, '--log-level=error',
]);
const { reconcileNodeIcons, makeNodeIconAsset } = await import(pathToFileURL(output).href);
const orderOutput = path.join(temp, 'order.mjs');
execFileSync(path.join(root, 'node_modules/.bin/esbuild'), [
  path.join(root, 'src/utils/excalidrawOrder.ts'), '--bundle', '--format=esm', '--platform=node',
  `--outfile=${orderOutput}`, '--log-level=error',
]);
const { normalizeLegacyOrder } = await import(pathToFileURL(orderOutput).href);
rmSync(temp, { recursive: true });

test('legacy scene keys allow native fractional insertion without changing paint order', () => {
  const original = Array.from({ length: 40 }, (_, i) => ({ id: String(i), index: `a${String(i).padStart(5, '0')}` }));
  const fixed = normalizeLegacyOrder(original);
  assert.deepEqual(fixed.map(e => e.id), original.map(e => e.id));
  assert.equal(original[0].index, 'a00000');
  for (let i = 0; i < fixed.length - 1; i++) {
    const inserted = generateKeyBetween(fixed[i].index, fixed[i + 1].index);
    assert.ok(fixed[i].index < inserted && inserted < fixed[i + 1].index);
  }
  assert.deepEqual(normalizeLegacyOrder(fixed), fixed);
});

function fixture() {
  return [
    { id:'host',type:'rectangle',x:100,y:100,width:200,height:64,strokeColor:'#6354A3',groupIds:['group'],version:1 },
    { id:'label',type:'text',x:175,y:120,width:80,height:20,containerId:'host',groupIds:['group'],version:1 },
    { id:'icon',type:'image',x:116,y:119,width:26,height:26,groupIds:['group'],version:1,
      customData:{evoDesignIcon:{hostId:'host',name:'analytics'}} },
  ];
}
function repair(elements, files={}) {
  const result = reconcileNodeIcons(elements, files);
  return { ...result, files: { ...files, ...Object.fromEntries(result.assets.map(f=>[f.id,f])) } };
}
function valid(result) {
  const [host,label,icon] = result.elements;
  assert.equal(icon.width,26);
  assert.ok(label.x >= icon.x+icon.width+9);
  assert.ok(label.x+label.width <= host.x+host.width);
  assert.ok(result.files[icon.fileId]?.dataURL.startsWith('data:image/svg+xml;base64,'));
}

test('moving and resizing preserves icon/text spacing without mutating input', () => {
  const initial = repair(fixture());
  const source = structuredClone(initial.elements);
  source[0].x += 250;
  source[0].y += 100;
  source[0].width = 90;
  const frozen = JSON.stringify(source);
  const moved = repair(source,initial.files);
  valid(moved);
  assert.equal(moved.elements[2].x-initial.elements[2].x,250);
  assert.equal(JSON.stringify(source),frozen);
  assert.equal(repair(moved.elements,moved.files).changed,false);
});
test('native copy resolves rewritten groups, even with stale custom host IDs', () => {
  const original = repair(fixture());
  const copy = structuredClone(original.elements).map(e=>({...e,id:e.id+'copy',x:e.x+400,groupIds:['copy-group'],
    ...(e.containerId?{containerId:e.containerId+'copy'}:{})}));
  const duplicated = repair([...original.elements,...copy],original.files);
  const icon = duplicated.elements.find(e=>e.id==='iconcopy');
  assert.equal(icon.customData.evoDesignIcon.hostId,'hostcopy');
  assert.equal(icon.x,original.elements[2].x+400);
  assert.deepEqual(duplicated.elements.slice(0,3),original.elements);
});
test('recolor and replace create portable assets; deletion follows only the host', () => {
  const initial = repair(fixture());
  initial.elements[0].strokeColor='#2266AA';
  initial.elements[2].customData.evoDesignIcon.name='science';
  const changed = repair(initial.elements,initial.files);
  const asset = changed.files[changed.elements[2].fileId];
  assert.ok(Buffer.from(asset.dataURL.split(',')[1],'base64').toString().includes('#2266AA'));
  const arbitrary = {...changed.elements[2],id:'ordinary',customData:{},groupIds:[]};
  changed.elements[0].isDeleted=true;
  const deleted = repair([...changed.elements,arbitrary],changed.files);
  assert.equal(deleted.elements[2].isDeleted,true);
  assert.deepEqual(deleted.elements[3],arbitrary);
});
test('unknown icon names never become arbitrary SVG or remote requests', () => {
  assert.equal(makeNodeIconAsset('<svg onload="alert(1)">','#FFFFFF'),null);
  assert.equal(makeNodeIconAsset('__proto__','#FFFFFF'),null);
  const asset=makeNodeIconAsset('analytics','url(https://example.com)');
  const svg=Buffer.from(asset.dataURL.split(',')[1],'base64').toString();
  assert.ok(svg.includes('#475569'));
  assert.ok(!svg.includes('example.com'));
});

test('missing embedded assets are restored even when the file ID is already canonical', () => {
  const initial = repair(fixture());
  const restored = repair(initial.elements, {});
  assert.equal(restored.changed, true);
  valid(restored);
  assert.equal(repair(restored.elements, restored.files).changed, false);
});

test('remove and undo restore label placement without losing the icon asset', () => {
  const initial = repair(fixture());
  const removed = structuredClone(initial.elements);
  removed[2].isDeleted = true;
  const without = repair(removed,initial.files);
  assert.equal(without.elements[1].x, without.elements[0].x+(without.elements[0].width-without.elements[1].width)/2);
  without.elements[2].isDeleted = false;
  const restored = repair(without.elements,without.files);
  valid(restored);
  assert.equal(restored.elements[2].fileId, initial.elements[2].fileId);
});

test('elliptical terminals retain compact icons inside the curved boundary', () => {
  const source = fixture();
  source[0].type = 'ellipse';
  source[0].width = 90;
  const initial = repair(source);
  valid(initial);
  const [host, label, icon] = initial.elements;
  for (const element of [label, icon]) {
    for (const x of [element.x, element.x + element.width]) {
      for (const y of [element.y, element.y + element.height]) {
        assert.ok(((x-host.x-host.width/2)/(host.width/2))**2 + ((y-host.y-host.height/2)/(host.height/2))**2 <= 1);
      }
    }
  }
  assert.equal(repair(initial.elements, initial.files).changed, false);
  const moved = structuredClone(initial.elements);
  moved[0].x += 300;
  const result = repair(moved, initial.files);
  assert.equal(result.elements[2].x - icon.x, 300);
  assert.equal(result.elements[0].type, 'ellipse');
});
