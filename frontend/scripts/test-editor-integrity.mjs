import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { test } from 'node:test';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const temp = mkdtempSync(path.join(tmpdir(), 'evodesign-integrity-'));
async function load(relative) {
  const output = path.join(temp, path.basename(relative) + '.mjs');
  execFileSync(path.join(root, 'node_modules/.bin/esbuild'), [path.join(root, relative),
    '--bundle', '--format=esm', '--platform=node', '--define:import.meta.env={}',
    `--outfile=${output}`, '--log-level=error']);
  return import(pathToFileURL(output).href);
}
const { mergeDeltaIntoSchema, getSnapshotDocSignature } = await load('src/utils/app.ts');
const { documentAppState, inPlaceAppState, retainedSelection, sceneFiles } = await load('src/utils/excalidrawScene.ts');
const { workspaceAuthTransition, canRestoreWorkspaceDraft } = await load('src/utils/workspaceAuth.ts');
const { normalizeBackendTimestamp, snapshotSourceKey, generatedProjectTitle } = await load('src/utils/projectHistory.ts');
const { guestSaveDiagram, guestExportProjects, guestSyncProjectSchema, guestFetchProjectSnapshots } = await load('src/services/guestStorage.ts');
const { fetchRecentDiagrams, fetchProjectDiagram, fetchProjectSnapshots, syncProjectSchema, saveDnaRules, loadDnaRules } = await load('src/services/backendApi.ts');
const { notifyAuthInvalidated } = await load('src/features/auth/authEvents.ts');
const { shouldSubmitOnEnter } = await load('src/utils/keyboard.ts');
const { rememberDnaDraft, readDnaDraft, clearDnaDraft, isLatestDnaDraft, sameDnaPreferences } = await load('src/utils/dnaSyncDraft.ts');
rmSync(temp, { recursive: true });

const node = id => ({ id, type: 'rectangle', x: 0, y: 0, width: 120, height: 60, version: 3, versionNonce: 10 });
test('partial model output preserves omitted selected nodes and rejects unrelated changes', () => {
  const source = { elements: [node('a'), node('b'), node('c')], files: { icon: { id: 'icon' } } };
  const before = JSON.stringify(source);
  const result = mergeDeltaIntoSchema(source, { elements: [{ id: 'a', x: 30 }, { id: 'c', x: 999 }] }, 'excalidraw', ['a', 'b']);
  assert.deepEqual(result.elements.map(item => item.id), ['a', 'b', 'c']);
  assert.equal(result.elements[0].width, 120);
  assert.equal(result.elements[1].x, 0);
  assert.equal(result.elements[2].x, 0);
  assert.deepEqual(result.files, source.files);
  assert.equal(JSON.stringify(source), before);
});
test('AI edits change the native document signature even when a model echoes old version fields', () => {
  const source = { elements: [node('a')] };
  const result = mergeDeltaIntoSchema(source, { elements: [{ ...node('a'), x: 30 }] }, 'excalidraw', ['a']);
  assert.equal(result.elements[0].version, 4);
  assert.notEqual(getSnapshotDocSignature(source), getSnapshotDocSignature(result));
});
test('explicit deletion targets selected nodes and their bound labels, keeping native tombstones', () => {
  const source = { elements: [node('a'), node('b'), { ...node('label'), type: 'text', containerId: 'a' }] };
  const result = mergeDeltaIntoSchema(source, { elements: [], deleted_ids: ['a', 'b'] }, 'excalidraw', ['a']);
  assert.equal(result.elements[0].isDeleted, true);
  assert.equal(result.elements[1].isDeleted, undefined);
  assert.equal(result.elements[2].isDeleted, true);
});
test('TLDraw uses explicit deletion without losing omitted shapes, pages or assets', () => {
  const source = { document: { store: { a: { id: 'a' }, b: { id: 'b' }, page: { id: 'page' },
    binding: { id: 'binding', typeName: 'binding', fromId: 'b', toId: 'a' } } } };
  const result = mergeDeltaIntoSchema(source, { records: { page: { id: 'page', x: 900 } }, deleted_ids: ['a'] }, 'tldraw', ['a', 'b']);
  assert.deepEqual(result.document.store, { b: { id: 'b' }, page: { id: 'page' } });
});
test('stored scenes contain document settings but no popup, selection, viewport or collaborator state', () => {
  assert.deepEqual(documentAppState({ viewBackgroundColor: '#fff', gridSize: 20, gridModeEnabled: true,
    openDialog: { name: 'imageExport' }, selectedElementIds: { a: true }, collaborators: new Map(),
    zoom: { value: .2 }, scrollX: -500, activeTool: { type: 'eraser' }, editingTextElement: node('a') }),
  { viewBackgroundColor: '#fff', gridSize: 20, gridModeEnabled: true });
  assert.deepEqual(documentAppState(null), {});
});

test('in-place AI edits retain only live selected elements and groups', () => {
  const selection = retainedSelection({ selectedElementIds: { a: true, removed: true, b: false }, selectedGroupIds: { team: true, old: true } },
    [{ id: 'a', groupIds: ['team'] }, { id: 'b' }, { id: 'removed', isDeleted: true }]);
  assert.deepEqual(selection, { selectedElementIds: { a: true }, selectedGroupIds: { team: true } });
  assert.deepEqual(retainedSelection({}, []), { selectedElementIds: {}, selectedGroupIds: {} });
  assert.deepEqual(documentAppState(selection), {}, 'selection never crosses the persistence boundary');
});

test('legacy API timestamps retain their UTC instant and history identifies AI generations', () => {
  assert.equal(normalizeBackendTimestamp('2026-10-24T14:36:31.123456'), '2026-10-24T14:36:31.123456Z');
  for (const timestamp of ['2026-10-24T22:36:31+08:00', '2026-10-24T14:36:31Z', 'invalid']) {
    assert.equal(normalizeBackendTimestamp(timestamp), timestamp);
  }
  assert.equal(snapshotSourceKey('AI_GEN'), 'workspace.snapshotSourceGenerated');
  assert.equal(snapshotSourceKey('AI_LOCAL'), 'workspace.snapshotSourceLocalEdit');
  assert.equal(snapshotSourceKey('MANUAL_SAVE'), 'workspace.snapshotSourceManualSave');
});

test('fresh titles replace placeholders from either language while retaining named projects', () => {
  for (const name of ['New Project', '新项目', '新建项目', '']) assert.equal(generatedProjectTitle(name, '  Incident\n workflow ', false), 'Incident workflow');
  assert.equal(generatedProjectTitle('My architecture', 'New request', false), 'My architecture');
  assert.equal(generatedProjectTitle('New Project', 'New request', true), 'New Project');
});

const values = new Map([['auth_token', 'local-test-token']]);
globalThis.localStorage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
globalThis.window = { localStorage: globalThis.localStorage };
test('project list and snapshot history carry server revisions to the first editor save', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ projects: [{ project_id: 'p', version: 7, canvas_engine: 'excalidraw' }] }));
  const projects = await fetchRecentDiagrams();
  assert.equal(projects[0].project_version, 7);
  globalThis.fetch = async () => new Response(JSON.stringify({ project_version: 8, snapshots: [{ snapshot_id: 's', project_id: 'p' }] }));
  const history = await fetchProjectSnapshots({ projectId: 'p' });
  assert.equal(history.snapshots[0].project_version, 8);
});

test('direct reopen uses the latest snapshot and its revision, not an outdated detail response', async () => {
  globalThis.fetch = async url => new Response(JSON.stringify(url.includes('/snapshots?')
    ? { project_version: 9, total: 2, snapshots: [{ snapshot_id: 'latest', schema_blob: { elements: [node('fresh')] }, metrics_scores: { generation: { total_duration_ms: 1250, quality_status: 'edited' } }, timestamp: '2026-10-24T14:00:00' }] }
    : { project_id: 'older-project', title: 'Saved work', canvas_engine: 'excalidraw', version: 8,
      latest_schema: { elements: [node('stale')] }, created_at: '2026-10-24T13:00:00', updated_at: '2026-10-24T14:00:00' }));
  const project = await fetchProjectDiagram('older-project');
  assert.equal(project.project_version, 9);
  assert.equal(project.snapshot_id, 'latest');
  assert.equal(project.generation_report.durationMs, 1250, 'reopening retains the generation details');
  assert.equal(project.generation_report.qualityStatus, 'edited');
  assert.equal(project.excalidraw_payload.elements[0].id, 'fresh');
  assert.equal(project.updated_at, '2026-10-24T14:00:00Z');
});
test('unversioned overwrites fail closed before sending a request; versioned saves send the revision', async () => {
  let calls = 0;
  globalThis.fetch = async (_url, init) => {
    calls++;
    assert.equal(JSON.parse(init.body).version, 8);
    return new Response(JSON.stringify({ version: 9 }));
  };
  const request = { project_id: 'p', base_snapshot_id: 's', schema_patch: { elements: [] } };
  await assert.rejects(syncProjectSchema(request), error => error.status === 409);
  assert.equal(calls, 0);
  assert.equal((await syncProjectSchema({ ...request, version: 8 })).version, 9);
  assert.equal(calls, 1);
});

test('guest storage keeps earlier projects and snapshots, including generation reports', () => {
  const report = { qualityStatus: 'passed', durationMs: 3000, timings: {}, memory: { status: 'used', retrievedCount: 2 },
    refinement: { status: 'completed', fixesApplied: 1 }, learning: { status: 'skipped', savedCount: 0 } };
  let first;
  for (let i = 0; i < 31; i++) {
    const saved = guestSaveDiagram({ id: 'request-' + i, prompt: 'Test', diagramType: 'flow', metadata: {} },
      { projectId: 'guest_integrity_' + i, snapshotId: 'snapshot-' + i, excalidrawPayload: JSON.stringify({ elements: [node('a')] }), generationReport: report });
    if (i === 0) first = saved;
  }
  assert.ok(guestExportProjects().some(project => project.project_id === first.projectId));
  assert.equal(guestExportProjects().length, 31);
  assert.equal(guestFetchProjectSnapshots(first.projectId).snapshots[0].generation_report.qualityStatus, 'passed');
  guestSyncProjectSchema({ project_id: first.projectId, base_snapshot_id: first.snapshotId, schema_patch: { elements: [node('edited')] } });
  assert.equal(guestFetchProjectSnapshots(first.projectId).snapshots[0].generation_report.qualityStatus, 'edited');
  for (let i = 0; i < 21; i++) guestSyncProjectSchema({ project_id: first.projectId, create_snapshot: true, schema_patch: { elements: [node('v-' + i)] } });
  const snapshots = guestFetchProjectSnapshots(first.projectId).snapshots;
  assert.equal(snapshots.length, 22);
  assert.ok(snapshots.some(snapshot => snapshot.snapshot_id === first.snapshotId));
});


test('DNA saves serialize replacements and retain the originating identity across login changes', async () => {
  const calls = [];
  let finishFirst;
  globalThis.fetch = (_url, init) => {
    calls.push(init);
    if (calls.length === 1) return new Promise(resolve => { finishFirst = resolve; });
    return Promise.resolve(new Response('{}'));
  };
  const rules = { structure: [], style: [], layout: [] };
  const first = saveDnaRules(rules, 'project-a', { token: 'owner-a' });
  const second = saveDnaRules(rules, 'project-a', { token: 'owner-a' });
  values.set('auth_token', 'owner-b');
  await Promise.resolve();
  assert.equal(calls.length, 1, 'second replacement must wait for the first response');
  finishFirst(new Response('{}'));
  assert.equal(await first, true);
  assert.equal(await second, true);
  assert.equal(calls.length, 2);
  assert.ok(calls.every(call => call.headers.Authorization === 'Bearer owner-a'));
  assert.ok(calls.every(call => JSON.parse(call.body).project_id === 'project-a'));
  values.set('auth_token', 'local-test-token');
});

test('DNA save reports HTTP/network failures and later retries can still succeed', async () => {
  const rules = { structure: [], style: [], layout: [] };
  globalThis.fetch = async () => new Response('{}', { status: 500 });
  assert.equal(await saveDnaRules(rules, 'retry-test'), false);
  globalThis.fetch = async () => { throw new Error('offline'); };
  assert.equal(await saveDnaRules(rules, 'retry-test'), false);
  globalThis.fetch = async () => new Response('{}');
  assert.equal(await saveDnaRules(rules, 'retry-test'), true);
});

test('DNA save snapshots input before queueing and bounds page-exit keepalive payloads', async () => {
  const calls = [];
  globalThis.fetch = async (_url, init) => { calls.push(init); return new Response('{}'); };
  const rules = { structure: [], style: [], layout: [] };
  const pending = saveDnaRules(rules, undefined, { token: 'owner', keepalive: true });
  rules.structure.push({ id: 1, title: 'Later edit', preview: 'x'.repeat(70000), enabled: true });
  await pending;
  await saveDnaRules(rules, undefined, { token: 'owner', keepalive: true });
  assert.equal(JSON.parse(calls[0].body).structure.length, 0);
  assert.equal(calls[0].keepalive, true);
  assert.equal(calls[1].keepalive, false);
});

test('IME composition and Shift+Enter never submit while plain Enter does', () => {
  assert.equal(shouldSubmitOnEnter({ key: 'Enter' }), true);
  assert.equal(shouldSubmitOnEnter({ key: 'Enter', shiftKey: true }), false);
  assert.equal(shouldSubmitOnEnter({ key: 'Enter', nativeEvent: { isComposing: true } }), false);
  assert.equal(shouldSubmitOnEnter({ key: 'Enter', keyCode: 229 }), false);
  assert.equal(shouldSubmitOnEnter({ key: 'Enter', nativeEvent: { keyCode: 229 } }), false);
  assert.equal(shouldSubmitOnEnter({ key: 'a' }), false);
});

test('DNA loads use the captured owner and wait for an earlier queued save', async () => {
  const calls = [];
  let release;
  globalThis.fetch = async (_url, init) => {
    calls.push(init);
    if (init.method === 'PUT') await new Promise(resolve => { release = resolve; });
    return new Response(JSON.stringify({ structure: [], style: [], layout: [] }));
  };
  const rules = { structure: [], style: [], layout: [] };
  const save = saveDnaRules(rules, 'load-after-save', { token: 'origin' });
  const load = loadDnaRules('load-after-save', 'origin');
  values.set('auth_token', 'new-account');
  await Promise.resolve();
  assert.equal(calls.length, 1);
  release();
  await save; await load;
  assert.equal(calls.length, 2);
  assert.equal(calls[1].headers.Authorization, 'Bearer origin');
  values.set('auth_token', 'local-test-token');
});

test('DNA outbox tracks newest saves without depending on localStorage availability', () => {
  const rules = { structure: [], style: [], layout: [] };
  const key = 'outbox-test';
  const a = rememberDnaDraft(key, rules);
  const b = rememberDnaDraft(key, { ...rules, style: [{ title: 'New', preview: 'blue', enabled: true }] });
  assert.equal(isLatestDnaDraft(key, a), false);
  assert.equal(isLatestDnaDraft(key, b), true);
  clearDnaDraft(key, a);
  assert.equal(readDnaDraft(key), b, 'old completion cannot erase a newer draft');
  clearDnaDraft(key, b);
  const original = window.localStorage;
  window.localStorage = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); }, removeItem: () => { throw new Error('blocked'); } };
  const volatile = rememberDnaDraft('blocked', rules);
  assert.equal(volatile.durable, false);
  assert.equal(isLatestDnaDraft('blocked', volatile), true);
  assert.equal(readDnaDraft('blocked'), volatile);
  clearDnaDraft('blocked', volatile);
  window.localStorage = original;
});

test('recovered DNA compares actual preferences, ignoring server metadata but detecting remote edits', () => {
  const rules = { structure: [{ id: 1, title: 'Naming', preview: 'User', enabled: true, pinned: false }], style: [], layout: [] };
  const remote = structuredClone(rules);
  remote.structure[0].id = 99;
  remote.structure[0].updatedAt = 'new timestamp';
  assert.equal(sameDnaPreferences(rules, remote), true);
  remote.structure[0].preview = 'Customer';
  assert.equal(sameDnaPreferences(rules, remote), false, 'another device edit requires explicit recovery choice');
});

test('DNA identity queues survive token refresh without mixing accounts', async () => {
  const calls = [];
  let release;
  globalThis.fetch = async (_url, init) => {
    calls.push(init);
    if (init.method === 'PUT') await new Promise(resolve => { release = resolve; });
    return new Response(JSON.stringify({ structure: [], style: [], layout: [] }));
  };
  const save = saveDnaRules({ structure: [], style: [], layout: [] }, 'p', { token: 'old-session', ownerId: 'same-user' });
  const load = loadDnaRules('p', 'new-session', 'same-user');
  await Promise.resolve();
  assert.equal(calls.length, 1);
  release();
  await save; await load;
  assert.equal(calls[0].headers.Authorization, 'Bearer old-session');
  assert.equal(calls[1].headers.Authorization, 'Bearer new-session');
});


test('session expiry resumes only its owner and never upgrades a private canvas into another account', () => {
  assert.equal(workspaceAuthTransition(null, 'a', 'a'), 'resume');
  assert.equal(workspaceAuthTransition(null, 'b', 'a'), 'reset');
  assert.equal(workspaceAuthTransition(null, 'a', null), 'guest-upgrade');
  assert.equal(workspaceAuthTransition('a', null, null), 'reset');
  assert.equal(workspaceAuthTransition('a', 'b', null), 'reset');
  assert.equal(canRestoreWorkspaceDraft('a', 'private-project', 'a'), true);
  assert.equal(canRestoreWorkspaceDraft('a', 'private-project', 'b'), false);
  assert.equal(canRestoreWorkspaceDraft(null, 'private-project', 'b'), false);
  assert.equal(canRestoreWorkspaceDraft(null, 'guest_local', 'b'), true);
  assert.equal(canRestoreWorkspaceDraft(null, undefined, 'b'), true);
});

test('in-place edits preserve live font and document preferences without replaying saved UI state', () => {
  const live = { currentItemFontFamily: 8, gridModeEnabled: true, gridSize: 30, viewBackgroundColor: '#eef', zoom: { value: 2 } };
  assert.deepEqual(inPlaceAppState(live, undefined), { currentItemFontFamily: 8, gridModeEnabled: true, gridSize: 30, viewBackgroundColor: '#eef' });
  assert.equal(inPlaceAppState(live, { viewBackgroundColor: '#ddd', currentItemFontFamily: 1 }).currentItemFontFamily, 8);
  assert.equal(inPlaceAppState(live, { viewBackgroundColor: '#ddd' }).viewBackgroundColor, '#ddd');
});

test('an expired snapshot request cannot invalidate a newer login', async () => {
  let resolveResponse;
  let invalidations = 0;
  globalThis.window.dispatchEvent = () => { invalidations++; };
  values.set('auth_token', 'expired');
  globalThis.fetch = () => new Promise(resolve => { resolveResponse = resolve; });
  const request = fetchProjectSnapshots({ projectId: 'p' });
  values.set('auth_token', 'new-session');
  resolveResponse(new Response('{}', { status: 401 }));
  await assert.rejects(request);
  assert.equal(invalidations, 0);
  globalThis.fetch = async () => new Response('{}', { status: 401 });
  await assert.rejects(fetchProjectSnapshots({ projectId: 'p' }));
  assert.equal(invalidations, 1);
  values.set('auth_token', 'local-test-token');
});


test('switching projects cannot leak cached image assets into saved or exported documents', () => {
  const files = { current: { dataURL: 'current' }, previous: { dataURL: 'private previous image' }, deleted: { dataURL: 'undo image' } };
  const elements = [{ type: 'image', fileId: 'current' }, { type: 'image', fileId: 'deleted', isDeleted: true }, { type: 'rectangle' }];
  assert.deepEqual(Object.keys(sceneFiles(elements, files)), ['current', 'deleted'], 'save retains tombstone assets for undo');
  assert.deepEqual(Object.keys(sceneFiles(elements.filter(element => !element.isDeleted), files)), ['current'], 'export contains only live image assets');
  assert.deepEqual(sceneFiles([{ type: 'rectangle' }], files), {});
});


test('intentional sign-out is distinguishable from session expiry without changing event listeners', () => {
  const events = [];
  globalThis.window.dispatchEvent = event => events.push(event);
  notifyAuthInvalidated();
  notifyAuthInvalidated('signed-out');
  assert.equal(events[0].type, events[1].type);
  assert.equal(events[0].detail.reason, 'expired');
  assert.equal(events[1].detail.reason, 'signed-out');
});
