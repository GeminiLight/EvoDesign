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
const { homeProjectKey, sortHomeProjects } = await load('src/utils/homeProjects.ts');
const { workspaceDocumentKey, openWorkspaceDocument, closeWorkspaceDocument, parseWorkspaceDocuments } = await load('src/utils/workspaceDocuments.ts');
const { getGenerationReviewState, hasCurrentVisualScores } = await load('src/utils/generationReport.ts');
const { getInitialStartupGenerationDraft, getInitialPreflightGeneration } = await load('src/services/workspaceRouteHandoff.ts');
const { saveStartupGenerationDraft, loadStartupGenerationDraft, clearStartupGenerationDraft } = await load('src/services/startupGenerationDraft.ts');
const { guestSaveDiagram, guestExportProjects, guestSyncProjectSchema, guestFetchRecentDiagrams, guestFetchProjectSnapshots, guestLoadDnaRules, guestSaveDnaRules } = await load('src/services/guestStorage.ts');
const { fetchRecentDiagrams, fetchProjectDiagram, fetchProjectSnapshots, syncProjectSchema, saveDnaRules, loadDnaRules, createBlankCanvasProject } = await load('src/services/backendApi.ts');
const { createBlankExcalidrawScene } = await load('src/utils/blankCanvas.ts');
const { requestCanvasFullscreen } = await load('src/hooks/useCanvasFullscreen.ts');
const { generationActivityStages, activityCanAutoClose } = await load('src/utils/generationActivity.ts');
const { clampFloatingAnchor, defaultFloatingAnchor, floatingPanelPosition, isAnchorDrag } = await load('src/utils/floatingAnchor.ts');
const { notifyAuthInvalidated } = await load('src/features/auth/authEvents.ts');
const { shouldSubmitOnEnter, shouldSubmitOnModifiedEnter } = await load('src/utils/keyboard.ts');
const { saveWorkspacePreflightDraft, loadWorkspacePreflightDraft } = await load('src/services/workspacePreflightDraft.ts');
const { rememberDnaDraft, readDnaDraft, clearDnaDraft, isLatestDnaDraft, sameDnaPreferences } = await load('src/utils/dnaSyncDraft.ts');
const { filterDnaPreferences, emptyDnaFilters } = await load('src/utils/dnaLibrary.ts');
const { remoteDocumentDecision } = await load('src/utils/remoteDocumentPolicy.ts');
rmSync(temp, { recursive: true });

test('external document updates preserve an unsaved draft and an open historical version', () => {
  const clean = { incoming: 5, known: 4, saving: false, dirty: false, blocked: false, historical: false };
  assert.equal(remoteDocumentDecision(clean), 'apply');
  assert.equal(remoteDocumentDecision({ ...clean, dirty: true }), 'conflict');
  assert.equal(remoteDocumentDecision({ ...clean, dirty: true, saving: true }), 'wait');
  assert.equal(remoteDocumentDecision({ ...clean, blocked: true }), 'wait');
  assert.equal(remoteDocumentDecision({ ...clean, historical: true }), 'history');
  assert.equal(remoteDocumentDecision({ ...clean, incoming: 4, dirty: true }), 'ignore');
  assert.equal(remoteDocumentDecision({ ...clean, known: null }), 'ignore');
});

test('fullscreen uses the native canvas element and verifies ownership after entering', async () => {
  const ownerDocument = { fullscreenEnabled: true, fullscreenElement: null };
  const element = { ownerDocument, requestFullscreen: async options => {
    assert.deepEqual(options, { navigationUI: 'hide' }); ownerDocument.fullscreenElement = element;
  } };
  assert.equal(await requestCanvasFullscreen(element), true);
  ownerDocument.fullscreenElement = null;
  element.requestFullscreen = async () => {};
  assert.equal(await requestCanvasFullscreen(element), false, 'a fulfilled but ineffective request needs the viewport layout');
});
test('embedded browsers can fall back when fullscreen is unavailable or denied', async () => {
  let calls = 0;
  const element = { ownerDocument: { fullscreenEnabled: false }, requestFullscreen: async () => { calls++; throw new Error('Denied'); } };
  assert.equal(await requestCanvasFullscreen(element), false);
  assert.equal(calls, 0);
  element.ownerDocument.fullscreenEnabled = true;
  assert.equal(await requestCanvasFullscreen(element), false);
  assert.equal(calls, 1);
  assert.equal(await requestCanvasFullscreen({ ownerDocument: { fullscreenEnabled: true } }), false);
});

test('DNA overview includes every category and all rules without modifying their data', () => {
  const rule = (id, title) => ({ id, title, preview: 'A preference', enabled: true, pinned: false, usageCount: 0 });
  const library = { structure: Array.from({ length: 5 }, (_, id) => rule(id, `Structure ${id}`)),
    style: [rule(0, 'Style')], layout: [rule(0, 'Layout')] };
  const before = JSON.stringify(library);
  const results = filterDnaPreferences(library, emptyDnaFilters);
  assert.equal(results.length, 7);
  assert.deepEqual(results.filter(item => item.rule.id === 0).map(item => item.cabinId), ['structure', 'style', 'layout']);
  assert.equal(JSON.stringify(library), before);
});

test('DNA category, search and enabled-state filters combine without hiding other category counts', () => {
  const library = { structure: [], style: [{ id: 1, title: 'VIOLET', preview: '青紫配色', enabled: true }],
    layout: [{ id: 2, title: 'Left to right', preview: 'Align nodes', enabled: false }] };
  assert.equal(filterDnaPreferences(library, { ...emptyDnaFilters, query: ' violet ' }).length, 1);
  assert.equal(filterDnaPreferences(library, { ...emptyDnaFilters, query: '青紫' })[0].cabinId, 'style');
  assert.deepEqual(filterDnaPreferences(library, { category: 'layout', query: 'ALIGN', status: 'disabled' }).map(item => item.rule.id), [2]);
  assert.equal(filterDnaPreferences(library, { category: 'layout', query: '', status: 'enabled' }).length, 0);
  assert.equal(library.layout.length, 1);
});

test('DNA overview prioritizes active preferences while preserving a stable pinned and usage order', () => {
  const rule = (id, enabled, pinned, usageCount) => ({ id, title: `Rule ${id}`, preview: '', enabled, pinned, usageCount });
  const library = { structure: [rule(1, false, true, 100), rule(2, true, false, 8), rule(3, true, true, 0), rule(4, true, false, 8)], style: [], layout: [] };
  assert.deepEqual(filterDnaPreferences(library, emptyDnaFilters).map(item => item.rule.id), [3, 2, 4, 1]);
  assert.deepEqual(library.structure.map(rule => rule.id), [1, 2, 3, 4]);
});

test('canvas tabs deduplicate project versions and update names without changing tab order', () => {
  const first = { key: workspaceDocumentKey('p1', 'old'), projectId: 'p1', diagramId: 'old', title: 'Architecture' };
  const second = { key: workspaceDocumentKey('p2', 'd2'), projectId: 'p2', diagramId: 'd2', title: 'Sequence' };
  const tabs = openWorkspaceDocument(openWorkspaceDocument([], first), second);
  const next = openWorkspaceDocument(tabs, { ...first, diagramId: 'new-version', title: 'Renamed' });
  assert.equal(next.length, 2);
  assert.equal(next[0].title, 'Renamed');
  assert.equal(next[1], second);
  assert.equal(workspaceDocumentKey('p1', 'old'), workspaceDocumentKey('p1', 'new-version'));
  assert.equal(openWorkspaceDocument(next, next[0]), next);
});

test('closing the active tab chooses its nearest surviving neighbor', () => {
  const tabs = ['p1', 'p2', 'p3'].map(projectId => ({ key: workspaceDocumentKey(projectId), projectId, diagramId: projectId, title: projectId }));
  assert.equal(closeWorkspaceDocument(tabs, 'project:p2', 'project:p2').activeKey, 'project:p3');
  assert.equal(closeWorkspaceDocument(tabs, 'project:p3', 'project:p3').activeKey, 'project:p2');
  assert.equal(closeWorkspaceDocument(tabs, 'project:p1', 'project:p1').activeKey, 'project:p2');
  assert.equal(tabs.length, 3);
});

test('closing a background tab preserves the active canvas and closing the last returns to draft', () => {
  const first = { key: 'project:p1', projectId: 'p1', diagramId: 'd1', title: 'A' };
  const second = { key: 'project:p2', projectId: 'p2', diagramId: 'd2', title: 'B' };
  const result = closeWorkspaceDocument([first, second], second.key, first.key);
  assert.deepEqual(result, { documents: [first], activeKey: first.key });
  assert.deepEqual(closeWorkspaceDocument([first], first.key, first.key), { documents: [], activeKey: 'draft' });
  assert.deepEqual(first, { key: 'project:p1', projectId: 'p1', diagramId: 'd1', title: 'A' });
});

test('restored canvas tabs reject malformed state and retain identifiers without schema or conversation content', () => {
  for (const raw of [null, '{broken', '{}', '42', 'null']) assert.deepEqual(parseWorkspaceDocuments(raw), []);
  const parsed = parseWorkspaceDocuments(JSON.stringify([
    { key: 'forged', projectId: 'p1', diagramId: 'd1', title: 'A', schema: { secret: true }, messages: ['private'], view: { scrollX: 200 } },
    { projectId: '', diagramId: 'bad', title: 'Invalid' },
    { projectId: 3, diagramId: 'bad', title: 'Invalid' },
    { projectId: 'p1', diagramId: 'd2', title: 'Latest title' },
  ]));
  assert.deepEqual(parsed, [{ key: 'project:p1', projectId: 'p1', diagramId: 'd2', title: 'Latest title' }]);
});

test('legacy documents have distinct keys and restored metadata is bounded', () => {
  assert.equal(workspaceDocumentKey(null, 'd1'), 'diagram:d1');
  assert.notEqual(workspaceDocumentKey(null, 'd1'), workspaceDocumentKey(null, 'd2'));
  assert.equal(workspaceDocumentKey(), 'draft');
  const records = Array.from({ length: 200 }, (_, i) => ({ projectId: `p${i}`, diagramId: `d${i}`, title: 'x'.repeat(400) }));
  const parsed = parseWorkspaceDocuments(JSON.stringify(records));
  assert.equal(parsed.length, 100);
  assert.equal(parsed[0].title.length, 300);
});

const reviewedReport = {
  memory: { status: 'used', retrievedCount: 2 },
  refinement: { status: 'completed', fixesApplied: 1 },
  learning: { status: 'disabled', savedCount: 0 },
  qualityStatus: 'passed', beforeScore: 6, afterScore: 8, timings: {}, durationMs: 12000,
};
test('browser review describes content only even when visual status is unverified', () => {
  const report = { ...reviewedReport, browserEdition: true, qualityStatus: 'unverified' };
  assert.equal(getGenerationReviewState(report), 'reviewed');
  assert.equal(hasCurrentVisualScores(report), false);
});
test('later edits invalidate the displayed review and historical scores', () => {
  for (const browserEdition of [true, false]) {
    const report = { ...reviewedReport, browserEdition, qualityStatus: 'edited' };
    assert.equal(getGenerationReviewState(report), 'edited');
    assert.equal(hasCurrentVisualScores(report), false);
    assert.equal(getGenerationReviewState({ ...report, qualityStatus: 'needs_attention' }), 'needs_attention');
  }
  assert.equal(getGenerationReviewState({ ...reviewedReport, qualityStatus: 'unverified' }), 'unverified');
});
test('report states distinguish skipped, unavailable and unsuccessful refinement', () => {
  for (const status of ['failed', 'unresolved']) {
    for (const browserEdition of [true, false]) {
      assert.equal(getGenerationReviewState({ ...reviewedReport, browserEdition, refinement: { status } }), 'kept_original');
    }
  }
  assert.equal(getGenerationReviewState(reviewedReport), 'refined');
  for (const status of ['skipped', 'disabled']) {
    assert.equal(getGenerationReviewState({ ...reviewedReport, browserEdition: true, refinement: { status } }), 'not_reviewed');
  }
  for (const [status, state] of [['skipped', 'not_needed'], ['disabled', 'disabled'], ['unsupported', 'unsupported'], ['unavailable', 'unverified']]) {
    assert.equal(getGenerationReviewState({ ...reviewedReport, refinement: { status } }), state);
  }
});
test('visual score display requires two finite scores within the scoring scale', () => {
  assert.equal(hasCurrentVisualScores(reviewedReport), true);
  assert.equal(hasCurrentVisualScores({ ...reviewedReport, beforeScore: 0, afterScore: 10 }), true);
  for (const value of [undefined, NaN, Infinity, -1, 10.1, '8']) {
    assert.equal(hasCurrentVisualScores({ ...reviewedReport, beforeScore: value }), false);
    assert.equal(hasCurrentVisualScores({ ...reviewedReport, afterScore: value }), false);
  }
});

test('home pins take priority within one list while each group stays most-recent-first', () => {
  const projects = [
    { project_id: 'older', created_at: '2026-10-01T00:00:00Z' },
    { project_id: 'pin-old', created_at: '2025-01-01T00:00:00Z' },
    { project_id: 'latest', created_at: '2026-10-29T00:00:00Z' },
    { project_id: 'pin-new', created_at: '2025-02-01T00:00:00Z', updated_at: '2026-10-28T00:00:00Z' },
  ];
  const before = JSON.stringify(projects);
  assert.deepEqual(sortHomeProjects(projects, ['pin-old', 'pin-new', 'missing', 'pin-old']).map(homeProjectKey), ['pin-new', 'pin-old', 'latest', 'older']);
  assert.deepEqual(sortHomeProjects(projects, []).map(homeProjectKey), ['latest', 'pin-new', 'older', 'pin-old']);
  assert.equal(JSON.stringify(projects), before);
});

test('home ordering normalizes UTC, falls back from invalid update times, and keeps equal-time order', () => {
  const projects = [
    { request_id: 'unknown', created_at: 'invalid' },
    { request_id: 'naive', created_at: '2026-10-29T08:00:00' },
    { request_id: 'same-time', created_at: '2026-10-29T16:00:00+08:00' },
    { request_id: '', diagram_id: 'fallback', updated_at: 'invalid', created_at: '2026-10-29T09:00:00Z' },
  ];
  assert.deepEqual(sortHomeProjects(projects, []).map(homeProjectKey), ['fallback', 'naive', 'same-time', 'unknown']);
  assert.deepEqual(sortHomeProjects(projects, ['unknown']).map(homeProjectKey), ['unknown', 'fallback', 'naive', 'same-time']);
});

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
test('blank documents start with independent empty scenes without placeholder shapes', () => {
  const first = createBlankExcalidrawScene();
  const next = createBlankExcalidrawScene();
  first.elements.push(node('drawn'));
  first.files.test = { id: 'test' };
  assert.equal(next.type, 'excalidraw');
  assert.deepEqual(next.elements, []);
  assert.deepEqual(next.files, {});
  assert.equal(snapshotSourceKey('MANUAL_CREATE'), 'workspace.snapshotSourceCreated');
});
test('blank browser canvases save, reopen and edit independently without model requests', async () => {
  const stored = values.get('evodiagram_guest_diagrams');
  const previousFetch = globalThis.fetch;
  values.delete('auth_token');
  globalThis.fetch = () => { throw new Error('Blank creation must not contact a model or backend'); };
  try {
    const request = { id: 'manual-test', prompt: 'An older prompt', diagramType: 'flow', metadata: { projectId: 'guest_previous' } };
    const first = await createBlankCanvasProject(request, 'Blank 1');
    const second = await createBlankCanvasProject(request, 'Blank 2');
    assert.notEqual(first.project_id, second.project_id);
    assert.notEqual(first.project_id, 'guest_previous');
    assert.equal(guestFetchProjectSnapshots(first.project_id).snapshots[0].edit_source, 'MANUAL_CREATE');
    assert.deepEqual(first.excalidraw_payload.elements, []);
    await syncProjectSchema({ project_id: first.project_id, schema_patch: { elements: [node('drawn')] }, create_snapshot: true });
    const reopened = await fetchProjectDiagram(first.project_id);
    assert.equal(reopened.excalidraw_payload.elements[0].id, 'drawn');
    assert.deepEqual((await fetchProjectDiagram(second.project_id)).excalidraw_payload.elements, []);
  } finally {
    values.set('auth_token', 'local-test-token'); globalThis.fetch = previousFetch;
    if (stored === undefined) values.delete('evodiagram_guest_diagrams'); else values.set('evodiagram_guest_diagrams', stored);
  }
});
test('signed-in blank canvases use project creation and initial revision, with no generation', async () => {
  const previousFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), body: JSON.parse(init.body), method: init.method });
    if (String(url).endsWith('/projects')) return new Response(JSON.stringify({ project_id: 'blank-auth', created_at: '2026-10-30T00:00:00Z' }));
    assert.ok(String(url).endsWith('/schema/sync'));
    return new Response(JSON.stringify({ snapshot_id: 'blank-snapshot', version: 1, latest_schema: createBlankExcalidrawScene() }));
  };
  try {
    const result = await createBlankCanvasProject({ id: 'manual-auth', prompt: '', diagramType: 'automated' }, 'Blank');
    assert.equal(calls.length, 2);
    assert.equal(calls[1].body.project_id, 'blank-auth');
    assert.equal(calls[1].body.base_snapshot_id, null);
    assert.equal(calls[1].body.create_snapshot, true);
    assert.equal(result.project_version, 1);
    assert.equal(result.snapshot_id, 'blank-snapshot');
    assert.deepEqual(result.excalidraw_payload.elements, []);
  } finally { globalThis.fetch = previousFetch; }
});
test('preflight reload preserves icon choice and supports older drafts without enabling icons', () => {
  const session = new Map();
  globalThis.window.sessionStorage = { getItem: key => session.get(key) ?? null, setItem: (key, value) => session.set(key, value), removeItem: key => session.delete(key) };
  const draft = { kind: 'gallery', promptText: 'Describe a service', diagramType: 'architecture', llmConfigId: 'test-model', canvasMode: 'excalidraw', source: 'gallery', rules: [], ruleCount: 0 };
  saveWorkspacePreflightDraft({ ...draft, useIcons: true });
  assert.equal(loadWorkspacePreflightDraft().useIcons, true);
  saveWorkspacePreflightDraft({ ...draft, useIcons: false });
  assert.equal(loadWorkspacePreflightDraft().useIcons, false);
  saveWorkspacePreflightDraft(draft);
  assert.equal(loadWorkspacePreflightDraft().useIcons, false);
  saveWorkspacePreflightDraft({ ...draft, canvasMode: 'tldraw', useIcons: true });
  assert.equal(loadWorkspacePreflightDraft().useIcons, false);
  delete globalThis.window.sessionStorage;
});
test('direct creation carries icons through routing and recovery without opening preflight', () => {
  const session = new Map();
  globalThis.window.sessionStorage = { getItem: key => session.get(key) ?? null, setItem: (key, value) => session.set(key, value), removeItem: key => session.delete(key) };
  for (const useIcons of [true, false]) {
    const state = { initialPrompt: '  Architecture with a gateway  ', initialDiagramType: 'architecture', initialCanvasMode: 'excalidraw', initialUseIcons: useIcons, initialSource: 'home', pendingGeneration: true };
    assert.equal(getInitialPreflightGeneration(state), null);
    const draft = getInitialStartupGenerationDraft(state);
    assert.equal(draft.promptText, 'Architecture with a gateway');
    assert.equal(draft.status, 'pending');
    assert.equal(draft.metadata.useIcons, String(useIcons));
    saveStartupGenerationDraft(draft);
    assert.equal(loadStartupGenerationDraft().metadata.useIcons, String(useIcons));
    assert.equal(getInitialStartupGenerationDraft({}).metadata.useIcons, String(useIcons));
    clearStartupGenerationDraft();
  }
  const tldraw = getInitialStartupGenerationDraft({ initialPrompt: 'Flow', initialCanvasMode: 'tldraw', initialUseIcons: true, pendingGeneration: true });
  assert.equal(tldraw.metadata.useIcons, 'false');
  saveStartupGenerationDraft({ ...tldraw, canvasMode: 'excalidraw', metadata: { useIcons: 'true' } });
  const olderHandoff = getInitialStartupGenerationDraft({ initialPrompt: 'Flow', pendingGeneration: true });
  assert.equal(olderHandoff.metadata.useIcons, 'true', 'older routes must preserve the stored icon setting');
  clearStartupGenerationDraft();
  delete globalThis.window.sessionStorage;
});
test('project list and snapshot history carry server revisions to the first editor save', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ projects: [{ project_id: 'p', version: 7, canvas_engine: 'excalidraw' }] }));
  const projects = await fetchRecentDiagrams();
  assert.equal(projects[0].project_version, 7);
  globalThis.fetch = async () => new Response(JSON.stringify({ project_version: 8, snapshots: [{ snapshot_id: 's', project_id: 'p' }] }));
  const history = await fetchProjectSnapshots({ projectId: 'p' });
  assert.equal(history.snapshots[0].project_version, 8);
});

test('direct reopen keeps a coherent formal document even when the history request sees a newer revision', async () => {
  globalThis.fetch = async url => new Response(JSON.stringify(url.includes('/snapshots?')
    ? { project_version: 9, total: 2, snapshots: [{ snapshot_id: 'latest', schema_blob: { elements: [node('fresh')] }, metrics_scores: { generation: { total_duration_ms: 1250, quality_status: 'edited' } }, timestamp: '2026-10-24T14:00:00' }] }
    : { project_id: 'older-project', title: 'Saved work', canvas_engine: 'excalidraw', version: 8,
      current_snapshot_id: 'saved', latest_schema: { elements: [node('saved-scene')] }, created_at: '2026-10-24T13:00:00', updated_at: '2026-10-24T14:00:00' }));
  const project = await fetchProjectDiagram('older-project');
  assert.equal(project.project_version, 8);
  assert.equal(project.snapshot_id, 'saved');
  assert.equal(project.generation_report, undefined, 'reports from another snapshot are not attached to this scene');
  assert.equal(project.excalidraw_payload.elements[0].id, 'saved-scene');
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
  const reopened = guestFetchRecentDiagrams().find(project => project.project_id === first.projectId);
  assert.equal(reopened.generation_report.durationMs, 3000, 'project reopening retains generation timing');
  assert.equal(reopened.generation_report.refinement.status, 'completed');
  assert.equal(reopened.generation_report.qualityStatus, 'edited', 'local edits do not hide the review history');
  for (let i = 0; i < 21; i++) guestSyncProjectSchema({ project_id: first.projectId, create_snapshot: true, schema_patch: { elements: [node('v-' + i)] } });
  const snapshots = guestFetchProjectSnapshots(first.projectId).snapshots;
  assert.equal(snapshots.length, 22);
  assert.ok(snapshots.some(snapshot => snapshot.snapshot_id === first.snapshotId));
  assert.equal(guestFetchRecentDiagrams().find(project => project.project_id === first.projectId).generation_report, undefined,
    'a manual snapshot must not borrow a different version’s report');
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

test('multiline creation requires Command/Control+Enter and never submits IME or line breaks', () => {
  assert.equal(shouldSubmitOnModifiedEnter({ key: 'Enter' }), false);
  assert.equal(shouldSubmitOnModifiedEnter({ key: 'Enter', shiftKey: true }), false);
  assert.equal(shouldSubmitOnModifiedEnter({ key: 'Enter', metaKey: true }), true);
  assert.equal(shouldSubmitOnModifiedEnter({ key: 'Enter', ctrlKey: true }), true);
  assert.equal(shouldSubmitOnModifiedEnter({ key: 'Enter', ctrlKey: true, shiftKey: true }), false);
  assert.equal(shouldSubmitOnModifiedEnter({ key: 'Enter', metaKey: true, nativeEvent: { isComposing: true } }), false);
  assert.equal(shouldSubmitOnModifiedEnter({ key: 'Enter', ctrlKey: true, keyCode: 229 }), false);
  assert.equal(shouldSubmitOnModifiedEnter({ key: 'Enter', metaKey: true, nativeEvent: { keyCode: 229 } }), false);
  assert.equal(shouldSubmitOnModifiedEnter({ key: 'a', ctrlKey: true }), false);
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


test('new design-memory scopes start empty without changing previously saved preferences', () => {
  const empty = { structure: [], style: [], layout: [] };
  assert.deepEqual(guestLoadDnaRules('new-account', 'en'), empty);
  assert.deepEqual(guestLoadDnaRules('new-account', 'zh'), empty);
  const saved = { structure: [{ id: 900, title: 'My naming preference', preview: 'Use service names.', source: 'manual', enabled: true, pinned: true, usageCount: 2, updatedAt: '2026-10-27' }], style: [], layout: [] };
  guestSaveDnaRules(saved, 'existing-account');
  assert.deepEqual(guestLoadDnaRules('existing-account', 'en'), saved);
  assert.deepEqual(guestLoadDnaRules('another-account', 'en'), empty);
  values.delete('evodiagram_user_dna_existing-account');
});


test('live browser stages use the real review configuration and measured durations', () => {
  const progress = { currentStage: 'refining', stageIndex: 2, totalStages: 3, completedStages: ['structure'], stageStartedAt: 1000,
    stageDurations: { structure: 1523 } };
  const stages = generationActivityStages(progress, undefined, true, true, 4300);
  assert.deepEqual(stages.map(stage => [stage.key, stage.state]), [['structure', 'done'], ['refining', 'running'], ['layout', 'pending']]);
  assert.equal(stages[0].durationMs, 1523);
  assert.equal(stages[1].durationMs, 3300);
  const withoutReview = generationActivityStages({ ...progress, currentStage: 'layout', totalStages: 2 }, undefined, true, true, 900);
  assert.deepEqual(withoutReview.map(stage => stage.key), ['structure', 'layout']);
  assert.equal(withoutReview[1].durationMs, 0);
});
test('generation records never invent completion, timings or successful refinement', () => {
  const stopped = generationActivityStages({ currentStage: 'layout', totalStages: 2, completedStages: ['structure'] }, undefined, false, true, 9999);
  assert.equal(stopped[1].state, 'interrupted');
  assert.equal(stopped[1].durationMs, undefined);
  const report = { timings: { structure: 0, layout: 10, refining: 400, render: NaN }, refinement: { status: 'failed' } };
  const finished = generationActivityStages(null, report, false, true, 9999);
  assert.deepEqual(finished.map(stage => stage.key), ['structure', 'refining', 'layout']);
  assert.equal(finished[1].state, 'interrupted');
  assert.equal(activityCanAutoClose(false, false, true), true);
  assert.equal(activityCanAutoClose(false, true, true), false);
  assert.equal(activityCanAutoClose(false, false, false), false);
  assert.equal(activityCanAutoClose(true, false, true), false);
});
test('assistant drag threshold separates activation from movement and keeps the launcher on screen', () => {
  assert.equal(isAnchorDrag({ x: 0, y: 0 }, { x: 3, y: 4 }), false);
  assert.equal(isAnchorDrag({ x: 0, y: 0 }, { x: 6, y: 0 }), true);
  assert.deepEqual(defaultFloatingAnchor({ width: 1456, height: 763, top: 64 }), { x: 1360, y: 623 });
  assert.deepEqual(clampFloatingAnchor({ x: -500, y: -500 }, { width: 375, height: 667, top: 64 }), { x: 12, y: 76 });
  assert.deepEqual(clampFloatingAnchor({ x: 900, y: 900 }, { width: 320, height: 560, top: 64 }), { x: 260, y: 476 });
});
test('assistant bubbles fit above or below a moved anchor after viewport resize', () => {
  for (const bounds of [{ width: 320, height: 560, top: 64 }, { width: 1456, height: 763, top: 64 }]) {
    for (const anchor of [{ x: 10, y: 76 }, { x: 1000, y: 600 }]) {
      const panel = floatingPanelPosition(clampFloatingAnchor(anchor, bounds), bounds);
      assert.ok(panel.left >= 12 && panel.left + panel.width <= bounds.width - 12);
      assert.ok(panel.top >= bounds.top + 12 && panel.top + panel.height <= bounds.height - 12);
    }
  }
});


test('AI generation reuses a saved blank canvas and preserves its earlier revision', async () => {
  const stored = values.get('evodiagram_guest_diagrams');
  values.delete('auth_token');
  try {
    const request = { id: 'blank-to-ai', prompt: '', diagramType: 'automated', style: 'neutral' };
    const blank = await createBlankCanvasProject(request, 'Blank to AI');
    const beforeCount = guestExportProjects().length;
    const generated = guestSaveDiagram({ ...request, id: 'generated-flow', prompt: 'Submit, run, complete', diagramType: 'flow', style: 'gentle',
      metadata: { projectId: blank.project_id } }, { excalidrawPayload: JSON.stringify({ elements: [node('generated')] }), summary: 'Task flow' });
    assert.equal(generated.projectId, blank.project_id);
    assert.equal(guestExportProjects().length, beforeCount);
    const snapshots = guestFetchProjectSnapshots(blank.project_id).snapshots;
    assert.equal(snapshots.length, 2);
    assert.deepEqual(snapshots[0].schema_blob.elements, []);
    assert.equal(snapshots[1].parent_id, snapshots[0].snapshot_id);
    const reopened = await fetchProjectDiagram(blank.project_id);
    assert.equal(reopened.excalidraw_payload.elements[0].id, 'generated');
    const project = guestExportProjects().find(item => item.project_id === blank.project_id);
    assert.equal(project.diagram_type, 'flow');
    assert.equal(project.prompt, 'Submit, run, complete');
    const independent = guestSaveDiagram({ ...request, metadata: { projectId: 'missing-project' } }, { excalidrawPayload: JSON.stringify(createBlankExcalidrawScene()) });
    assert.notEqual(independent.projectId, 'missing-project');
    assert.notEqual(independent.projectId, blank.project_id);
  } finally {
    values.set('auth_token', 'local-test-token');
    if (stored === undefined) values.delete('evodiagram_guest_diagrams'); else values.set('evodiagram_guest_diagrams', stored);
  }
});
