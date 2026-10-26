import { type Dispatch, type SetStateAction, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useBackendAuth } from '../features/auth/BackendAuthProvider';
import { useLanguage } from '../i18n/LanguageProvider';
import type { CabinId, Rule } from '../types/dna';
import {
  guestLoadDnaRules,
  guestSaveDnaRules,
  guestLoadProjectDnaRules,
  guestSaveProjectDnaRules,
  hasDnaRulesForScope,
  guestHasProjectDna,
} from '../services/guestStorage';
import { loadDnaRules, saveDnaRules } from '../services/backendApi';

import { rememberDnaDraft, readDnaDraft, isLatestDnaDraft, clearDnaDraft, sameDnaPreferences, type DnaRules } from '../utils/dnaSyncDraft';

const CABIN_IDS: CabinId[] = ['structure', 'style', 'layout'];

function loadLocalRules(
  projectId?: string,
  scopeId?: string | null,
  locale?: string | null,
): Record<CabinId, Rule[]> {
  if (projectId) {
    return guestLoadProjectDnaRules(projectId, scopeId, locale) ?? guestLoadDnaRules(scopeId, locale);
  }
  return guestLoadDnaRules(scopeId, locale);
}

function hasStoredLocalRules(projectId?: string, scopeId?: string | null): boolean {
  return projectId
    ? guestHasProjectDna(projectId, scopeId) || hasDnaRulesForScope(scopeId)
    : hasDnaRulesForScope(scopeId);
}

function hasAnyRules(rules: Record<CabinId, Rule[]>): boolean {
  return CABIN_IDS.some((cabinId) => rules[cabinId].length > 0);
}

export function useRuleLibrary(options?: { projectId?: string }) {
  const { projectId } = options ?? {};
  const { token, user } = useBackendAuth();
  const { language } = useLanguage();
  // Wait for the authenticated profile; never attribute a new token to a stale cached user.
  const storageScopeId = token ? (user?.user_id ?? null) : null;
  const ruleScopeKey = `${storageScopeId ?? 'guest'}:${projectId ?? 'global'}`;
  const pendingKey = `evodesign:dna-pending:${ruleScopeKey}`;
  const activeScopeRef = useRef(ruleScopeKey);
  activeScopeRef.current = ruleScopeKey;
  const [ruleLibrary, setRuleLibraryState] = useState<DnaRules>(() => loadLocalRules(projectId, storageScopeId, language));
  const latestRuleLibraryRef = useRef(ruleLibrary);
  const dirtyRef = useRef(false);
  const readyScopeRef = useRef<string | null>(token ? null : ruleScopeKey);
  const [canEditRules, setCanEditRules] = useState(!token);
  const [syncStatus, setSyncStatus] = useState<'local' | 'loading' | 'saving' | 'synced' | 'failed' | 'failedVolatile' | 'loadFailed' | 'conflict'>(token ? 'loading' : 'local');
  const serverRulesRef = useRef<DnaRules | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);
  const pendingSaveRef = useRef<(() => void) | null>(null);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const aliveRef = useRef(true);

  const storeLocal = useCallback((rules: DnaRules) => {
    if (projectId) guestSaveProjectDnaRules(projectId, rules, storageScopeId);
    else guestSaveDnaRules(rules, storageScopeId);
  }, [projectId, storageScopeId]);

  const persistBackend = useCallback((rules: DnaRules) => {
    if (!token || !storageScopeId) return;
    const draft = rememberDnaDraft(pendingKey, rules);
    if (aliveRef.current && activeScopeRef.current === ruleScopeKey) setSyncStatus('saving');
    void saveDnaRules(rules, projectId, { token, keepalive: true, ownerId: storageScopeId }).then(ok => {
      if (!isLatestDnaDraft(pendingKey, draft)) return;
      if (ok) clearDnaDraft(pendingKey, draft);
      if (aliveRef.current && activeScopeRef.current === ruleScopeKey) {
        setSyncStatus(ok ? 'synced' : draft.durable ? 'failed' : 'failedVolatile');
      }
    });
  }, [pendingKey, projectId, ruleScopeKey, storageScopeId, token]);

  const setRuleLibrary = useCallback<Dispatch<SetStateAction<DnaRules>>>((action) => {
    // Never replace remote rules using an unhydrated local/default copy.
    if (readyScopeRef.current !== ruleScopeKey) return;
    dirtyRef.current = true;
    setRuleLibraryState(previous => {
      const next = typeof action === 'function' ? action(previous) : action;
      latestRuleLibraryRef.current = next;
      return next;
    });
  }, [ruleScopeKey]);

  useEffect(() => {
    let cancelled = false;
    readyScopeRef.current = null;
    setCanEditRules(false);
    dirtyRef.current = false;
    serverRulesRef.current = null;
    const localRules = loadLocalRules(projectId, storageScopeId, language);
    const pending = token && storageScopeId ? readDnaDraft(pendingKey) : null;
    const localCopy = pending?.rules ?? localRules;
    latestRuleLibraryRef.current = localCopy;
    setRuleLibraryState(localCopy);
    setSyncStatus(token ? 'loading' : 'local');
    if (token && !storageScopeId) return;
    if (!token) {
      readyScopeRef.current = ruleScopeKey;
      setCanEditRules(true);
      return;
    }
    void loadDnaRules(projectId, token, storageScopeId ?? undefined).then(backendRules => {
      if (cancelled) return;
      if (!backendRules) {
        setSyncStatus('loadFailed'); // Retry reloads; it must not PUT a stale copy.
        return;
      }
      serverRulesRef.current = backendRules;
      if (pending && !sameDnaPreferences(pending.rules, backendRules)) {
        // Preserve both copies. Resuming never silently overwrites another device.
        setSyncStatus('conflict');
        return;
      }
      if (pending) clearDnaDraft(pendingKey, pending);
      const remoteHasRules = hasAnyRules(backendRules);
      const rules = remoteHasRules ? backendRules : localRules;
      latestRuleLibraryRef.current = rules;
      setRuleLibraryState(rules);
      if (remoteHasRules || hasStoredLocalRules(projectId, storageScopeId)) storeLocal(rules);
      readyScopeRef.current = ruleScopeKey;
      setCanEditRules(true);
      setSyncStatus(remoteHasRules ? 'synced' : 'local');
    });
    return () => { cancelled = true; };
  }, [language, projectId, storageScopeId, token, pendingKey, ruleScopeKey, reloadNonce, storeLocal]);

  useEffect(() => {
    if (!dirtyRef.current || readyScopeRef.current !== ruleScopeKey) return;
    dirtyRef.current = false;
    storeLocal(ruleLibrary);
    if (!token) return;
    rememberDnaDraft(pendingKey, ruleLibrary);
    setSyncStatus('saving');
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    pendingSaveRef.current = () => persistBackend(ruleLibrary);
    saveTimerRef.current = setTimeout(() => {
      const save = pendingSaveRef.current;
      pendingSaveRef.current = null;
      save?.();
    }, 500);
  }, [ruleLibrary, pendingKey, persistBackend, ruleScopeKey, storeLocal, token]);

  useEffect(() => {
    aliveRef.current = true;
    const flush = () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      const save = pendingSaveRef.current;
      pendingSaveRef.current = null;
      save?.();
    };
    window.addEventListener('pagehide', flush);
    return () => {
      aliveRef.current = false;
      flush();
      window.removeEventListener('pagehide', flush);
    };
  }, [ruleScopeKey, token, language]);

  const retrySync = () => {
    if (syncStatus === 'loadFailed') { setReloadNonce(value => value + 1); return; }
    readyScopeRef.current = ruleScopeKey;
    setCanEditRules(true);
    storeLocal(latestRuleLibraryRef.current);
    persistBackend(latestRuleLibraryRef.current);
  };
  const acceptServerRules = () => {
    const rules = serverRulesRef.current;
    if (!rules) return;
    const draft = readDnaDraft(pendingKey);
    if (draft) clearDnaDraft(pendingKey, draft);
    latestRuleLibraryRef.current = rules;
    dirtyRef.current = false;
    setRuleLibraryState(rules);
    storeLocal(rules);
    readyScopeRef.current = ruleScopeKey;
    setCanEditRules(true);
    setSyncStatus('synced');
  };

  const evoStats = useMemo(() => {
    const counts = {
      structure: ruleLibrary.structure.length,
      style: ruleLibrary.style.length,
      layout: ruleLibrary.layout.length,
    };
    const total = counts.structure + counts.style + counts.layout;
    const enabled = [...ruleLibrary.structure, ...ruleLibrary.style, ...ruleLibrary.layout].filter((r) => r.enabled).length;
    return { counts, total, enabled };
  }, [ruleLibrary]);

  const [activeDrawerCabin, setActiveDrawerCabin] = useState<CabinId | null>(null);
  const [searchKeywords, setSearchKeywords] = useState<Record<CabinId, string>>({ structure: '', style: '', layout: '' });
  const [selectedRuleIds, setSelectedRuleIds] = useState<Record<CabinId, number[]>>({ structure: [], style: [], layout: [] });
  const [editing, setEditing] = useState<{ cabinId: CabinId; rule: Rule } | null>(null);
  const [draftTitle, setDraftTitle] = useState('');
  const [draftPreview, setDraftPreview] = useState('');
  const [editErrors, setEditErrors] = useState({ title: false, preview: false });

  useEffect(() => {
    setActiveDrawerCabin(null);
    setSearchKeywords({ structure: '', style: '', layout: '' });
    setSelectedRuleIds({ structure: [], style: [], layout: [] });
    setEditing(null);
    setDraftTitle('');
    setDraftPreview('');
    setEditErrors({ title: false, preview: false });
  }, [ruleScopeKey]);

  const sortRules = (rules: Rule[]) => [...rules].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    if (a.pinned && b.pinned) return 0;
    return b.usageCount - a.usageCount;
  });

  const topRulesByCabin = (cabinId: CabinId) => {
    const sorted = sortRules(ruleLibrary[cabinId]);
    // Prioritise enabled rules so disabled ones don't occupy the top-3 slots
    const enabled = sorted.filter((r) => r.enabled);
    const disabled = sorted.filter((r) => !r.enabled);
    return [...enabled, ...disabled].slice(0, 3);
  };

  const fullRulesByCabin = (cabinId: CabinId) => {
    const keyword = searchKeywords[cabinId].trim().toLowerCase();
    const sorted = sortRules(ruleLibrary[cabinId]);
    if (!keyword) return sorted;
    return sorted.filter((rule) => (`${rule.title} ${rule.preview}`).toLowerCase().includes(keyword));
  };

  const toggleRuleEnabled = (cabinId: CabinId, ruleId: number) => {
    setRuleLibrary((prev) => ({
      ...prev,
      [cabinId]: prev[cabinId].map((rule) => (rule.id === ruleId ? { ...rule, enabled: !rule.enabled } : rule)),
    }));
  };

  const openEdit = (cabinId: CabinId, rule: Rule) => {
    setEditing({ cabinId, rule });
    setDraftTitle(rule.title);
    setDraftPreview(rule.preview);
    setEditErrors({ title: false, preview: false });
  };

  const saveEdit = () => {
    if (!editing) return false;
    const nextTitle = draftTitle.trim();
    const nextPreview = draftPreview.trim();
    const nextErrors = { title: nextTitle.length === 0, preview: nextPreview.length === 0 };

    if (nextErrors.title || nextErrors.preview) {
      setEditErrors(nextErrors);
      return false;
    }

    setRuleLibrary((prev) => ({
      ...prev,
      [editing.cabinId]: prev[editing.cabinId].map((rule) => (
        rule.id === editing.rule.id
          ? { ...rule, title: nextTitle, preview: nextPreview }
          : rule
      )),
    }));
    setEditing(null);
    setEditErrors({ title: false, preview: false });
    return true;
  };

  const openDrawer = (cabinId: CabinId) => {
    setActiveDrawerCabin(cabinId);
    setSelectedRuleIds((prev) => ({ ...prev, [cabinId]: [] }));
  };

  const closeDrawer = () => {
    setActiveDrawerCabin(null);
  };

  const toggleSelectRule = (cabinId: CabinId, ruleId: number) => {
    setSelectedRuleIds((prev) => {
      const hasRule = prev[cabinId].includes(ruleId);
      return {
        ...prev,
        [cabinId]: hasRule ? prev[cabinId].filter((id) => id !== ruleId) : [...prev[cabinId], ruleId],
      };
    });
  };

  const batchSetEnabled = (cabinId: CabinId, enabled: boolean) => {
    const targetIds = selectedRuleIds[cabinId];
    if (targetIds.length === 0) return;
    setRuleLibrary((prev) => ({
      ...prev,
      [cabinId]: prev[cabinId].map((rule) => (targetIds.includes(rule.id) ? { ...rule, enabled } : rule)),
    }));
  };

  const drawerRules = activeDrawerCabin ? fullRulesByCabin(activeDrawerCabin) : [];
  const drawerSelectedIds = activeDrawerCabin ? selectedRuleIds[activeDrawerCabin] : [];
  const hasDraftChanges = editing
    ? draftTitle.trim() !== editing.rule.title || draftPreview.trim() !== editing.rule.preview
    : false;
  const canSaveEdit = Boolean(editing && hasDraftChanges);

  return {
    syncStatus, retrySync, acceptServerRules, canEditRules,
    ruleLibrary,
    setRuleLibrary: setRuleLibrary as Dispatch<SetStateAction<Record<CabinId, Rule[]>>>,
    evoStats,
    activeDrawerCabin,
    searchKeywords,
    setSearchKeywords,
    editing,
    setEditing,
    draftTitle,
    setDraftTitle,
    draftPreview,
    setDraftPreview,
    editErrors,
    setEditErrors,
    hasDraftChanges,
    canSaveEdit,
    topRulesByCabin,
    fullRulesByCabin,
    toggleRuleEnabled,
    openEdit,
    saveEdit,
    openDrawer,
    closeDrawer,
    toggleSelectRule,
    batchSetEnabled,
    drawerRules,
    drawerSelectedIds,
  };
}
