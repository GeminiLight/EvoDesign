import type { AppState } from '@excalidraw/excalidraw/types';

export type WorkspaceDocument = {
  key: string;
  projectId?: string;
  diagramId: string;
  title: string;
};

export type CanvasViewState = {
  kind: 'excalidraw';
  scrollX: number;
  scrollY: number;
  zoom: AppState['zoom'];
  selectedElementIds: Record<string, boolean>;
  selectedGroupIds: Record<string, boolean>;
} | {
  kind: 'tldraw';
  camera: { x: number; y: number; z: number };
  selectedIds: string[];
};

export type WorkspaceDocumentContext = {
  messages: Array<{ id: string; role: 'user' | 'agent'; content: string }>;
  input: string;
  view: CanvasViewState | null;
};

export function workspaceDocumentKey(projectId?: string | null, diagramId?: string): string {
  return projectId ? `project:${projectId}` : diagramId ? `diagram:${diagramId}` : 'draft';
}

export function openWorkspaceDocument(documents: WorkspaceDocument[], document: WorkspaceDocument): WorkspaceDocument[] {
  const index = documents.findIndex(item => item.key === document.key);
  if (index < 0) return [...documents, document];
  const current = documents[index];
  if (current.projectId === document.projectId && current.diagramId === document.diagramId && current.title === document.title) return documents;
  return documents.map((item, position) => position === index ? document : item);
}

/** Closing a tab only changes the open list; it never deletes a saved project. */
export function closeWorkspaceDocument(documents: WorkspaceDocument[], key: string, activeKey: string) {
  const index = documents.findIndex(item => item.key === key);
  const remaining = documents.filter(item => item.key !== key);
  return {
    documents: remaining,
    activeKey: key !== activeKey ? activeKey : remaining[Math.min(Math.max(0, index), remaining.length - 1)]?.key ?? 'draft',
  };
}

export function parseWorkspaceDocuments(raw: string | null): WorkspaceDocument[] {
  try {
    const items: unknown = JSON.parse(raw ?? '[]');
    if (!Array.isArray(items)) return [];
    const unique = new Map<string, WorkspaceDocument>();
    for (const item of items.slice(0, 100)) {
      if (!item || typeof item !== 'object' || typeof item.projectId !== 'string' || !item.projectId.trim()
        || typeof item.diagramId !== 'string' || typeof item.title !== 'string') continue;
      const document = { key: workspaceDocumentKey(item.projectId), projectId: item.projectId,
        diagramId: item.diagramId, title: item.title.slice(0, 300) };
      unique.set(document.key, document);
    }
    return [...unique.values()];
  } catch { return []; }
}
