import { useEffect, useMemo, useRef, useState } from 'react';
import { updateProjectTitle } from '../services/backendApi';
import { getProjectNameStorageKey, loadProjectName, saveProjectName } from '../services/projectPreferences';

type ProjectNameOptions = {
  readOnly?: boolean;
  onRenamed?: (projectId: string, title: string) => void;
  onError?: () => void;
};

export function useProjectName(
  projectId: string | undefined,
  authIdentity: string | null,
  t: (key: string) => string,
  options: ProjectNameOptions = {},
) {
  const [projectName, setProjectName] = useState('');
  const [projectNameDraft, setProjectNameDraft] = useState('');
  const [isEditingProjectName, setIsEditingProjectName] = useState(false);
  const [isSavingProjectName, setIsSavingProjectName] = useState(false);
  const projectNameInputRef = useRef<HTMLInputElement>(null);
  const savingRef = useRef(false);
  const scope = getProjectNameStorageKey(authIdentity, projectId);
  const activeScopeRef = useRef(scope);
  activeScopeRef.current = scope;
  const lastPersistedScopeRef = useRef<string | null>(null);

  const defaultProjectName = useMemo(
    () => (projectId ? `Project ${projectId.slice(0, 8)}` : t('workspace.newProject')),
    [t, projectId],
  );

  useEffect(() => {
    const storedName = loadProjectName(authIdentity, projectId);
    setProjectName(storedName?.trim() || defaultProjectName);
    setIsEditingProjectName(false);
  }, [authIdentity, defaultProjectName, projectId]);

  useEffect(() => { setProjectNameDraft(projectName); }, [projectName]);

  useEffect(() => {
    // A scope change still renders the previous name once. Language changes
    // must not leave a flag that silently discards the next real rename.
    if (lastPersistedScopeRef.current !== scope) {
      lastPersistedScopeRef.current = scope;
      return;
    }
    const trimmedName = projectName.trim();
    if (trimmedName) saveProjectName(authIdentity, projectId, trimmedName);
  }, [authIdentity, projectId, projectName, scope]);

  useEffect(() => {
    if (options.readOnly) setIsEditingProjectName(false);
  }, [options.readOnly]);

  useEffect(() => {
    if (!isEditingProjectName) return;
    projectNameInputRef.current?.focus();
    projectNameInputRef.current?.select();
  }, [isEditingProjectName]);

  const handleStartProjectNameEdit = () => {
    if (options.readOnly || savingRef.current) return;
    setProjectNameDraft(projectName);
    setIsEditingProjectName(true);
  };

  const handleCancelProjectNameEdit = () => {
    if (savingRef.current) return;
    setProjectNameDraft(projectName);
    setIsEditingProjectName(false);
  };

  const handleSaveProjectNameEdit = async () => {
    if (options.readOnly || savingRef.current) return;
    const nextName = projectNameDraft.trim() || defaultProjectName;
    const requestScope = scope;
    savingRef.current = true;
    setIsSavingProjectName(true);
    try {
      if (projectId && authIdentity) await updateProjectTitle(projectId, nextName);
      if (activeScopeRef.current !== requestScope) return;
      saveProjectName(authIdentity, projectId, nextName);
      setProjectName(nextName);
      setIsEditingProjectName(false);
      if (projectId) options.onRenamed?.(projectId, nextName);
    } catch (error) {
      console.error('Failed to sync project name to backend:', error);
      if (activeScopeRef.current === requestScope) options.onError?.();
    } finally {
      savingRef.current = false;
      setIsSavingProjectName(false);
    }
  };

  return {
    projectName, setProjectName, projectNameDraft, setProjectNameDraft,
    isEditingProjectName, isSavingProjectName, projectNameInputRef,
    handleStartProjectNameEdit, handleCancelProjectNameEdit, handleSaveProjectNameEdit,
  };
}
