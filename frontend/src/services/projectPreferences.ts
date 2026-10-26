import { readLocalStorage, writeLocalStorage } from '../utils/safeLocalStorage';

const LEGACY_PROJECT_FAVORITES_STORAGE_KEY = 'evodiagram_project_favorites';
const GUEST_PROJECT_FAVORITES_STORAGE_KEY = 'evodiagram_guest_project_favorites';
const USER_PROJECT_FAVORITES_STORAGE_PREFIX = 'evodiagram_user_';
const PROJECT_FAVORITES_STORAGE_SUFFIX = '_project_favorites';
const LEGACY_PROJECT_NAME_STORAGE_PREFIX = 'workspace.projectName';
const PROJECT_NAME_SCOPE_PREFIX = 'workspace.projectName';

const normalizeProjectIds = (value: unknown): string[] => {
  if (!Array.isArray(value)) return [];

  const seen = new Set<string>();
  return value.reduce<string[]>((ids, item) => {
    if (typeof item !== 'string') return ids;
    const projectId = item.trim();
    if (!projectId || seen.has(projectId)) return ids;
    seen.add(projectId);
    ids.push(projectId);
    return ids;
  }, []);
};

const parseProjectIds = (raw: string | null): string[] => {
  if (!raw) return [];

  try {
    return normalizeProjectIds(JSON.parse(raw));
  } catch {
    return [];
  }
};

const getProjectFavoritesStorageKey = (authIdentity: string | null): string => {
  if (!authIdentity) {
    return GUEST_PROJECT_FAVORITES_STORAGE_KEY;
  }

  return `${USER_PROJECT_FAVORITES_STORAGE_PREFIX}${encodeURIComponent(authIdentity)}${PROJECT_FAVORITES_STORAGE_SUFFIX}`;
};

export const loadFavoriteProjectIds = (authIdentity: string | null): string[] => {
  const scopedKey = getProjectFavoritesStorageKey(authIdentity);
  const scopedValue = readLocalStorage(scopedKey);
  if (scopedValue !== null) {
    return parseProjectIds(scopedValue);
  }

  if (authIdentity) {
    return [];
  }

  const legacyGuestIds = parseProjectIds(readLocalStorage(LEGACY_PROJECT_FAVORITES_STORAGE_KEY));
  if (legacyGuestIds.length > 0) {
    writeLocalStorage(scopedKey, JSON.stringify(legacyGuestIds));
  }
  return legacyGuestIds;
};

export const saveFavoriteProjectIds = (authIdentity: string | null, projectIds: string[]): void => {
  writeLocalStorage(
    getProjectFavoritesStorageKey(authIdentity),
    JSON.stringify(normalizeProjectIds(projectIds)),
  );
};

const getProjectNameScope = (authIdentity: string | null): string => (
  authIdentity ? `user.${encodeURIComponent(authIdentity)}` : 'guest'
);

const getLegacyProjectNameStorageKey = (projectId: string | undefined): string => (
  projectId
    ? `${LEGACY_PROJECT_NAME_STORAGE_PREFIX}.${projectId}`
    : `${LEGACY_PROJECT_NAME_STORAGE_PREFIX}.draft`
);

export const getProjectNameStorageKey = (
  authIdentity: string | null,
  projectId: string | undefined,
): string => {
  const scope = getProjectNameScope(authIdentity);
  return projectId
    ? `${PROJECT_NAME_SCOPE_PREFIX}.${scope}.${projectId}`
    : `${PROJECT_NAME_SCOPE_PREFIX}.${scope}.draft`;
};

export const loadProjectName = (
  authIdentity: string | null,
  projectId: string | undefined,
): string | null => {
  const scopedKey = getProjectNameStorageKey(authIdentity, projectId);
  const scopedName = readLocalStorage(scopedKey)?.trim();
  if (scopedName) {
    return scopedName;
  }

  if (authIdentity) {
    return null;
  }

  const legacyGuestName = readLocalStorage(getLegacyProjectNameStorageKey(projectId))?.trim();
  if (legacyGuestName) {
    writeLocalStorage(scopedKey, legacyGuestName);
    return legacyGuestName;
  }

  return null;
};

export const saveProjectName = (
  authIdentity: string | null,
  projectId: string | undefined,
  projectName: string,
): void => {
  const trimmedName = projectName.trim();
  if (!trimmedName) return;
  writeLocalStorage(getProjectNameStorageKey(authIdentity, projectId), trimmedName);
};
