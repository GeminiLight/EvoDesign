/** A real editable document; no model request or generated placeholder nodes. */
export function createBlankExcalidrawScene(): Record<string, unknown> {
  return { type: 'excalidraw', version: 2, source: 'EvoDesign', elements: [],
    appState: { viewBackgroundColor: '#ffffff' }, files: {} };
}
