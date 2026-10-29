import type { RecentDiagram } from '../types/app';
import { normalizeBackendTimestamp } from './projectHistory';

export const homeProjectKey = (project: RecentDiagram): string => project.project_id || project.request_id || project.diagram_id;

const projectTime = (project: RecentDiagram): number => {
  for (const value of [project.updated_at, project.created_at]) {
    if (!value) continue;
    const timestamp = Date.parse(normalizeBackendTimestamp(value));
    if (Number.isFinite(timestamp)) return timestamp;
  }
  return 0;
};

/** Pinning is a priority within the same chronological list, not a filter. */
export function sortHomeProjects(projects: RecentDiagram[], pinnedIds: string[]): RecentDiagram[] {
  const pinned = new Set(pinnedIds);
  return projects.map(project => ({ project, pinned: pinned.has(homeProjectKey(project)), time: projectTime(project) }))
    .sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.time - a.time)
    .map(item => item.project);
}
