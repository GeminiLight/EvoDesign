import type { FileId } from '@excalidraw/excalidraw/element/types';
import type { ExcalidrawElementSkeleton } from '@excalidraw/excalidraw/data/transform';
import { layoutPlan, wrapLabel, type DiagramPlan } from './diagramPlan';
import { makeNodeIconAsset, reconcileNodeIcons, type IconSceneElement } from '../../utils/nodeIcons';

export async function renderPlan(plan: DiagramPlan, useIcons: boolean): Promise<Record<string, unknown>> {
  const { convertToExcalidrawElements } = await import('@excalidraw/excalidraw');
  const layout = layoutPlan(plan, useIcons);
  const skeleton: ExcalidrawElementSkeleton[] = [];
  const files: Record<string, unknown> = {};
  const stroke = '#475569';
  const common = { strokeColor: stroke, strokeWidth: 1.5, roughness: 0, opacity: 100, fillStyle: 'solid' as const };
  skeleton.push({ type: 'text', id: crypto.randomUUID(), x: 60, y: 10, text: plan.title, fontSize: 24, fontFamily: 2, strokeColor: '#334155' });
  for (const n of layout.nodes) {
    skeleton.push({ ...common, type: n.shape, id: n.id, x: n.x, y: n.y, width: n.width, height: n.height,
      backgroundColor: n.color, roundness: n.shape === 'rectangle' ? { type: 3 } : null,
      label: { text: n.text, fontSize: 18, fontFamily: 2, strokeColor: '#334155' } });
  }
  if (plan.kind === 'sequence') {
    const end = Math.max(...layout.edges.flatMap(e => e.points.map(p => p.y)), 260) + 80;
    for (const n of layout.nodes) skeleton.push({ ...common, type: 'line', id: crypto.randomUUID(),
      x: n.x + n.width / 2, y: n.y + n.height, points: [[0, 0], [0, end - n.y - n.height]], strokeColor: '#94a3b8', strokeStyle: 'dashed' });
  }
  layout.edges.forEach((e) => {
    const first = e.points[0];
    skeleton.push({ ...common, type: 'arrow', id: crypto.randomUUID(), x: first.x, y: first.y,
      points: e.points.map(p => [p.x - first.x, p.y - first.y]), endArrowhead: 'arrow', strokeStyle: e.strokeStyle,
      ...(plan.kind === 'graph' && e.source !== e.target ? { start: { id: e.source }, end: { id: e.target } } : {}),
      ...(e.label ? { label: { text: wrapLabel(e.label, 22), fontFamily: 2, fontSize: 14, strokeColor: '#475569' } } : {}),
    });
  });
  if (useIcons) {
    for (const n of layout.nodes) {
      if (!n.icon || n.shape === 'diamond') continue;
      const asset = makeNodeIconAsset(n.icon, stroke);
      if (!asset) continue;
      files[asset.id] = asset;
      skeleton.push({ type: 'image', id: crypto.randomUUID(), fileId: asset.id as FileId, x: n.x + 16, y: n.y + (n.height - 26) / 2,
        width: 26, height: 26, customData: { evoDesignIcon: { name: n.icon, hostId: n.id } } });
    }
  }
  const native = convertToExcalidrawElements(skeleton, { regenerateIds: false });
  const repaired = reconcileNodeIcons(native as unknown as IconSceneElement[], files);
  for (const asset of repaired.assets) files[asset.id] = asset;
  return { type: 'excalidraw', version: 2, source: 'EvoDesign browser edition', elements: repaired.elements,
    appState: { viewBackgroundColor: '#ffffff' }, files };
}

export function preserveLockedElements(scene: Record<string, unknown>, current: Record<string, unknown> | null, locked: string[]): Record<string, unknown> {
  if (!current || !locked.length || !Array.isArray(current.elements)) return scene;
  const ids = new Set(locked);
  const previous = current.elements as Record<string, unknown>[];
  for (const el of previous) {
    const icon = (el.customData as { evoDesignIcon?: { hostId?: string } } | undefined)?.evoDesignIcon;
    if (ids.has(String(el.containerId)) || (icon?.hostId && ids.has(icon.hostId))) ids.add(String(el.id));
  }
  const generated = (scene.elements as Record<string, unknown>[]).filter(el => {
    const icon = (el.customData as { evoDesignIcon?: { hostId?: string } } | undefined)?.evoDesignIcon;
    return !ids.has(String(el.id)) && !ids.has(String(el.containerId)) && !ids.has(icon?.hostId || '');
  });
  return { ...scene, elements: [...generated, ...previous.filter(el => ids.has(String(el.id)))], files: { ...scene.files as object, ...current.files as object } };
}

/** Recompute text metrics after a model edit without touching unrelated objects. */
export async function reflowEditedText(current: Record<string, unknown>, patch: Record<string, unknown>): Promise<Record<string, unknown>> {
  const updates = patch.elements as Record<string, unknown>[];
  if (!updates.some(e => 'text' in e || 'fontSize' in e || 'width' in e || 'height' in e)) return patch;
  const { restoreElements } = await import('@excalidraw/excalidraw');
  const source = current.elements as Record<string, unknown>[];
  const changed = new Map(updates.map(e => [e.id, e]));
  const merged = source.map(e => ({ ...e, ...changed.get(e.id) }));
  const restored = restoreElements(merged as unknown as Parameters<typeof restoreElements>[0], null, { refreshDimensions: true });
  const reflowIds = new Set(updates.map(e => e.id));
  for (const e of source) if (reflowIds.has(e.containerId)) reflowIds.add(e.id);
  const elements = restored.filter(e => reflowIds.has(e.id)).map(e => ({
    ...changed.get(e.id), id: e.id, x: e.x, y: e.y, width: e.width, height: e.height,
    ...(e.type === 'text' ? { text: e.text, originalText: e.originalText, fontSize: e.fontSize } : {}),
  }));
  return { ...patch, elements };
}

export async function repairSceneBindings(scene: Record<string, unknown>): Promise<Record<string, unknown>> {
  const { restoreElements } = await import('@excalidraw/excalidraw');
  return { ...scene, elements: restoreElements(scene.elements as Parameters<typeof restoreElements>[0], null, { repairBindings: true }) };
}
