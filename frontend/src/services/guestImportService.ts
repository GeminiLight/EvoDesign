import { createProject, syncProjectSchema } from './backendApi';
import {
  guestExportProjects,
  guestLoadDnaRules,
  guestLoadProjectDnaRules,
  guestSaveDnaRules,
  guestSaveProjectDnaRules,
  hasDnaRulesForScope,
  type GuestDiagram,
  type GuestSnapshot,
} from './guestStorage';
import {
  loadFavoriteProjectIds,
  loadProjectName,
  saveFavoriteProjectIds,
  saveProjectName,
} from './projectPreferences';
import { DEFAULT_CANVAS_LIBRARY, normalizeCanvasLibraryOrNull } from '../contracts/canvas';
import type { RecentCanvasLibrary } from '../types/app';

export const GUEST_IMPORT_COMPLETED_EVENT = 'evodiagram:guest-import-completed';

type ImportedProjectState = {
  projectId: string;
  snapshots: Record<string, string>;
  importedAt?: string;
};

type GuestImportState = {
  projects: Record<string, ImportedProjectState>;
};

export type PendingGuestImportSummary = {
  projectCount: number;
  snapshotCount: number;
};

export type GuestImportResult = {
  importedProjects: number;
  importedSnapshots: number;
  skippedProjects: number;
};

export type GuestImportCompletedDetail = {
  projects: Record<string, ImportedProjectState>;
};

const importStateKey = (userId: string) => `evodiagram_guest_imports_${encodeURIComponent(userId)}`;

const readImportState = (userId: string): GuestImportState => {
  try {
    const raw = localStorage.getItem(importStateKey(userId));
    if (!raw) return { projects: {} };
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || !('projects' in parsed)) {
      return { projects: {} };
    }
    return parsed as GuestImportState;
  } catch {
    return { projects: {} };
  }
};

const writeImportState = (userId: string, state: GuestImportState): void => {
  localStorage.setItem(importStateKey(userId), JSON.stringify(state));
};

const normalizeCanvasLibrary = (project: GuestDiagram): RecentCanvasLibrary => {
  return normalizeCanvasLibraryOrNull(project.canvas_library)
    ?? (project.tldraw_snapshot ? 'tldraw' : DEFAULT_CANVAS_LIBRARY);
};

const getProjectTitle = (project: GuestDiagram): string => {
  return (
    loadProjectName(null, project.project_id)
    || project.summary
    || project.prompt
    || 'Imported guest diagram'
  );
};

const getSortedSnapshots = (project: GuestDiagram): GuestSnapshot[] => {
  const snapshots = Array.isArray(project.snapshots) && project.snapshots.length > 0
    ? project.snapshots
    : [{
        snapshot_id: project.snapshot_id,
        parent_id: null,
        schema_blob: project.tldraw_snapshot ?? project.excalidraw_payload ?? {},
        edit_source: 'AI_GEN',
        thought_trace: null,
        timestamp: project.created_at,
      }];

  return [...snapshots].sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
  );
};

const projectImportComplete = (project: GuestDiagram, imported?: ImportedProjectState): boolean => {
  if (!imported?.projectId) return false;
  const snapshots = getSortedSnapshots(project);
  return snapshots.every((snapshot) => Boolean(imported.snapshots[snapshot.snapshot_id]));
};

const copyProjectPreferences = (
  guestProject: GuestDiagram,
  accountProjectId: string,
  userId: string,
): void => {
  const guestProjectName = loadProjectName(null, guestProject.project_id);
  if (guestProjectName) {
    saveProjectName(userId, accountProjectId, guestProjectName);
  }

  const guestFavorites = loadFavoriteProjectIds(null);
  if (guestFavorites.includes(guestProject.project_id)) {
    const userFavorites = loadFavoriteProjectIds(userId);
    if (!userFavorites.includes(accountProjectId)) {
      saveFavoriteProjectIds(userId, [...userFavorites, accountProjectId]);
    }
  }

  const projectDnaRules = guestLoadProjectDnaRules(guestProject.project_id, null);
  if (projectDnaRules) {
    guestSaveProjectDnaRules(accountProjectId, projectDnaRules, userId);
  }
};

const copyGlobalDnaIfNeeded = (userId: string): void => {
  if (!hasDnaRulesForScope(null) || hasDnaRulesForScope(userId)) return;
  guestSaveDnaRules(guestLoadDnaRules(null), userId);
};

export function getPendingGuestImportSummary(userId: string | null): PendingGuestImportSummary | null {
  if (!userId) return null;

  const projects = guestExportProjects();
  if (projects.length === 0) return null;

  const state = readImportState(userId);
  const pendingProjects = projects.filter((project) => (
    !projectImportComplete(project, state.projects[project.project_id])
  ));

  if (pendingProjects.length === 0) return null;

  return {
    projectCount: pendingProjects.length,
    snapshotCount: pendingProjects.reduce(
      (count, project) => count + getSortedSnapshots(project).length,
      0,
    ),
  };
}

export async function importGuestProjectsToAccount(userId: string): Promise<GuestImportResult> {
  const projects = guestExportProjects();
  const state = readImportState(userId);
  let importedProjects = 0;
  let importedSnapshots = 0;
  let skippedProjects = 0;

  copyGlobalDnaIfNeeded(userId);

  for (const guestProject of projects) {
    let imported = state.projects[guestProject.project_id];
    if (projectImportComplete(guestProject, imported)) {
      skippedProjects += 1;
      continue;
    }

    const canvasLibrary = normalizeCanvasLibrary(guestProject);

    if (!imported?.projectId) {
      const created = await createProject({
        title: getProjectTitle(guestProject),
        diagram_type: guestProject.diagram_type || 'automated',
        canvas_library: canvasLibrary,
        source_text: guestProject.prompt || null,
      });
      imported = {
        projectId: created.project_id,
        snapshots: {},
        importedAt: new Date().toISOString(),
      };
      state.projects[guestProject.project_id] = imported;
      writeImportState(userId, state);
      importedProjects += 1;
      copyProjectPreferences(guestProject, created.project_id, userId);
    }

    let previousImportedSnapshotId: string | null = null;
    for (const snapshot of getSortedSnapshots(guestProject)) {
      const alreadyImportedSnapshotId = imported.snapshots[snapshot.snapshot_id];
      if (alreadyImportedSnapshotId) {
        previousImportedSnapshotId = alreadyImportedSnapshotId;
        continue;
      }

      const synced = await syncProjectSchema({
        project_id: imported.projectId,
        schema_patch: snapshot.schema_blob,
        editor: canvasLibrary,
        base_snapshot_id: previousImportedSnapshotId,
        create_snapshot: true,
      });

      imported.snapshots[snapshot.snapshot_id] = synced.snapshot_id;
      previousImportedSnapshotId = synced.snapshot_id;
      importedSnapshots += 1;
      writeImportState(userId, state);
    }
  }

  window.dispatchEvent(new CustomEvent<GuestImportCompletedDetail>(
    GUEST_IMPORT_COMPLETED_EVENT,
    { detail: { projects: state.projects } },
  ));

  return {
    importedProjects,
    importedSnapshots,
    skippedProjects,
  };
}
