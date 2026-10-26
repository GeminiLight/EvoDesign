/** Only document settings cross the storage boundary. Never replay editor UI state. */
export function documentAppState(value: unknown): Record<string, unknown> {
  const input = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  return Object.fromEntries(['viewBackgroundColor', 'gridSize', 'gridStep', 'gridModeEnabled']
    .filter(key => input[key] !== undefined).map(key => [key, input[key]]));
}

/** Keep the live selection during an in-place AI edit, never from saved data. */
export function retainedSelection(
  state: { selectedElementIds?: Readonly<Record<string, boolean>>; selectedGroupIds?: Readonly<Record<string, boolean>> },
  elements: readonly { id: string; isDeleted?: boolean; groupIds?: readonly string[] }[],
) {
  const live = elements.filter(element => !element.isDeleted);
  const ids = new Set(live.map(element => element.id));
  const groups = new Set(live.flatMap(element => element.groupIds ?? []));
  return {
    selectedElementIds: Object.fromEntries(Object.entries(state.selectedElementIds ?? {}).filter(([id, selected]) => selected && ids.has(id))),
    selectedGroupIds: Object.fromEntries(Object.entries(state.selectedGroupIds ?? {}).filter(([id, selected]) => selected && groups.has(id))),
  };
}

/** Preserve live editor preferences unless the edited document explicitly changes them. */
export function inPlaceAppState(live: Record<string, unknown>, incoming: unknown) {
  return {
    ...documentAppState(live),
    currentItemFontFamily: live.currentItemFontFamily,
    ...documentAppState(incoming),
  };
}

/** Excalidraw caches assets across scene switches; persist only this scene's files. */
export function sceneFiles<T>(elements: readonly { type: string; fileId?: string | null }[], files: Record<string, T>): Record<string, T> {
  const ids = new Set(elements.filter(element => element.type === 'image').map(element => element.fileId));
  return Object.fromEntries(Object.entries(files).filter(([id]) => ids.has(id)));
}
