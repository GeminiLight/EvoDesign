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
