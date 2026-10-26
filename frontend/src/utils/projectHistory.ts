/** The API's legacy naive ISO timestamps are UTC, not the browser's timezone. */
export function normalizeBackendTimestamp(value: string): string {
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(value) ? `${value}Z` : value;
}

export function snapshotSourceKey(source?: string | null): string {
  const value = (source ?? '').toLowerCase();
  if (value === 'ai_local' || value.includes('local')) return 'workspace.snapshotSourceLocalEdit';
  if (value.includes('manual') || value.includes('save')) return 'workspace.snapshotSourceManualSave';
  if (value === 'ai_gen' || value.includes('generate')) return 'workspace.snapshotSourceGenerated';
  return 'workspace.snapshotSourceUpdated';
}

export function generatedProjectTitle(current: string, prompt: string, existingProject: boolean): string {
  const name = current.trim();
  const placeholder = ['New Project', '新项目', '新建项目'].includes(name);
  return name && (existingProject || !placeholder) ? name : prompt.trim().replace(/\s+/g, ' ').slice(0, 60);
}
