import { BROWSER_MODE } from '../services/browser/runtime';
import { BrowserPreferenceDialog } from '../components/DNA/BrowserPreferenceDialog';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  BrainCircuit,
  LayoutTemplate,
  Palette,
  Plus,
  Search,
  X,
  Zap,
} from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { DnaSyncStatus } from '../components/DNA/DnaSyncStatus';
import { DnaPreferenceLibrary } from '../components/DNA/DnaPreferenceLibrary';
import { Header } from '../components/Header';
import { CloneModal } from '../components/DNA/CloneModal';
import { useBackendAuth } from '../features/auth/BackendAuthProvider';
import { useLanguage } from '../i18n/LanguageProvider';
import { useToast } from '../components/toastContext';
import { useRuleLibrary } from '../hooks/useRuleLibrary';
import { useCloneFlow } from '../hooks/useCloneFlow';
import type { CabinId } from '../types/dna';
import { defaultConfigs } from '../constants/app';
import { dnaPreferenceExample } from '../utils/dnaPreferenceExamples';
import { emptyDnaFilters, type DnaLibraryFilters } from '../utils/dnaLibrary';

type DnaRouteState = {
  highlightCabinId?: CabinId;
  highlightRuleId?: number;
};

const isCabinId = (value: unknown): value is CabinId => (
  value === 'structure' || value === 'style' || value === 'layout'
);
const DNA_CABIN_IDS: CabinId[] = ['structure', 'style', 'layout'];

export function YourDNAPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user } = useBackendAuth();
  const { language, t } = useLanguage();
  const { showToast } = useToast();
  const isZh = language === 'zh';
  const dnaAuthScope = user?.user_id ?? 'guest';

  const {
    ruleLibrary, setRuleLibrary, evoStats, syncStatus, retrySync, acceptServerRules, canEditRules,
    activeDrawerCabin, searchKeywords, setSearchKeywords,
    editing, setEditing, draftTitle, setDraftTitle, draftPreview, setDraftPreview,
    editErrors, setEditErrors, canSaveEdit,
    toggleRuleEnabled, openEdit, saveEdit,
    openDrawer, closeDrawer, toggleSelectRule, batchSetEnabled,
    drawerRules, drawerSelectedIds,
  } = useRuleLibrary();

  const [addingPreference, setAddingPreference] = useState(false);
  const [libraryFilters, setLibraryFilters] = useState<DnaLibraryFilters>(emptyDnaFilters);
  const [newPreferenceCategory, setNewPreferenceCategory] = useState<CabinId>('style');
  const [prefillPreference, setPrefillPreference] = useState(false);
  const primaryAddRef = useRef<HTMLButtonElement | null>(null);
  const cloneTriggerRef = useRef<HTMLButtonElement | null>(null);
  const drawerTriggerRef = useRef<HTMLButtonElement | null>(null);
  const drawerSearchRef = useRef<HTMLInputElement | null>(null);
  const editDialogRef = useRef<HTMLDivElement | null>(null);
  const editTitleRef = useRef<HTMLInputElement | null>(null);
  const editTriggerRef = useRef<HTMLButtonElement | null>(null);
  const processedHighlightRef = useRef<string | null>(null);
  const [highlightedRule, setHighlightedRule] = useState<{ cabinId: CabinId; ruleId: number } | null>(null);
  const canCreateWithCurrentDna = evoStats.enabled > 0;

  const cabins = useMemo(() => [
    {
      id: 'structure' as const,
      name: t('dna.page.structureName'),
      tag: t('dna.page.structureTag'),
      hint: isZh ? '节点、分组与连接关系' : 'Nodes, groups and connections',
      code: t('dna.page.structureCode'),
      icon: BrainCircuit,
      color: {
        accent: 'text-indigo-500 dark:text-indigo-300',
        mask: 'from-indigo-100/10 via-indigo-200/20 to-indigo-300/40 dark:from-indigo-950/35 dark:via-indigo-900/14 dark:to-indigo-500/8',
      },
    },
    {
      id: 'style' as const,
      name: t('dna.page.styleName'),
      tag: t('dna.page.styleTag'),
      hint: isZh ? '配色、字体与图形风格' : 'Color, typography and visual style',
      code: t('dna.page.styleCode'),
      icon: Palette,
      color: {
        accent: 'text-violet-500 dark:text-violet-300',
        mask: 'from-violet-100/10 via-violet-200/20 to-violet-300/40 dark:from-violet-950/35 dark:via-violet-900/14 dark:to-violet-500/8',
      },
    },
    {
      id: 'layout' as const,
      name: t('dna.page.layoutName'),
      tag: t('dna.page.layoutTag'),
      hint: isZh ? '方向、间距与对齐方式' : 'Direction, spacing and alignment',
      code: t('dna.page.layoutCode'),
      icon: LayoutTemplate,
      color: {
        accent: 'text-teal-500 dark:text-teal-300',
        mask: 'from-teal-100/10 via-teal-200/20 to-teal-300/40 dark:from-teal-950/35 dark:via-teal-900/14 dark:to-teal-500/8',
      },
    },
  ], [t, isZh]);

  const {
    showCloneModal, setShowCloneModal, setCloneStep,
    cloneFileName, setCloneFileName, setCloneFile,
    cloneCandidates, cloneMessage, cloneStatus,
    openCloneModal, runCloneExtraction, updateCloneCandidate, applyCloneCandidates,
    cloneCandidateErrors, hasCloneCandidateErrors,
    selectedCandidateCount, canApplyCloneCandidates,
    cloneStepList, cloneCurrentStepIndex,
  } = useCloneFlow(ruleLibrary, setRuleLibrary, cabins, t, isZh, (message) => {
    showToast(message, 'success');
  }, dnaAuthScope);

  const drawerCabin = activeDrawerCabin ? cabins.find((cabin) => cabin.id === activeDrawerCabin) ?? null : null;
  const isDrawerOpen = Boolean(activeDrawerCabin && drawerCabin);
  const drawerSearchTerm = activeDrawerCabin ? searchKeywords[activeDrawerCabin].trim() : '';
  const isAnyDnaOverlayOpen = isDrawerOpen || showCloneModal || addingPreference || Boolean(editing);

  useEffect(() => {
    if (!isAnyDnaOverlayOpen) return;

    const previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.body.style.overflow = previousBodyOverflow;
    };
  }, [isAnyDnaOverlayOpen]);

  const openPreferenceFromButton = (event: React.MouseEvent<HTMLButtonElement>, cabinId: CabinId, prefill = false) => {
    cloneTriggerRef.current = event.currentTarget;
    if (BROWSER_MODE) { setNewPreferenceCategory(cabinId); setPrefillPreference(prefill); setAddingPreference(true); }
    else openCloneModal();
  };

  const openCloneFromButton = (event: React.MouseEvent<HTMLButtonElement>) => {
    openPreferenceFromButton(event, libraryFilters.category === 'all' ? 'style' : libraryFilters.category);
  };

  const restoreAddFocus = () => window.setTimeout(() => {
    const trigger = cloneTriggerRef.current;
    (trigger?.isConnected ? trigger : primaryAddRef.current)?.focus();
  }, 0);

  const closeCloneModal = () => {
    setShowCloneModal(false);
    restoreAddFocus();
  };

  const openDrawerFromButton = (event: React.MouseEvent<HTMLButtonElement>, cabinId: typeof cabins[number]['id']) => {
    drawerTriggerRef.current = event.currentTarget;
    openDrawer(cabinId);
  };

  const closeDrawerAndRestoreFocus = () => {
    closeDrawer();
    window.setTimeout(() => drawerTriggerRef.current?.focus(), 0);
  };

  const openEditFromButton = (event: React.MouseEvent<HTMLButtonElement>, cabinId: typeof cabins[number]['id'], rule: Parameters<typeof openEdit>[1]) => {
    editTriggerRef.current = event.currentTarget;
    openEdit(cabinId, rule);
  };

  const closeEditModal = () => {
    setEditing(null);
    setEditErrors({ title: false, preview: false });
    window.setTimeout(() => editTriggerRef.current?.focus(), 0);
  };

  const ruleActionLabel = (key: string, title: string) => t(key).replace('{title}', title);

  const submitEdit = () => {
    const saved = saveEdit();
    if (saved) {
      window.setTimeout(() => editTriggerRef.current?.focus(), 0);
    }
  };

  const createWithCurrentDna = () => {
    const enabledRules = DNA_CABIN_IDS.flatMap((cabinId) => (
      ruleLibrary[cabinId]
        .filter((rule) => rule.enabled)
        .map((rule) => ({
          cabinId,
          title: rule.title,
          preview: rule.preview,
        }))
    ));

    if (enabledRules.length === 0) {
      showToast(t('dna.page.heroCreateDisabledToast'), 'error');
      return;
    }

    navigate('/workspace', {
      state: {
        preflightGeneration: true,
        preflightKind: 'dna',
        preflightRules: enabledRules,
        preflightRuleCount: enabledRules.length,
        initialDiagramType: 'automated',
        initialLlmConfigId: defaultConfigs[0]?.id ?? 'default',
        initialCanvasMode: 'excalidraw',
        initialSource: 'dna',
      },
    });
  };

  const handleDialogTabTrap = (event: React.KeyboardEvent, container: HTMLElement | null, onEscape: () => void) => {
    if (event.key === 'Escape') {
      event.stopPropagation();
      onEscape();
      return;
    }

    if (event.key !== 'Tab' || !container) return;

    const focusableElements = Array.from(
      container.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ),
    );
    if (focusableElements.length === 0) return;

    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];
    if (event.shiftKey && document.activeElement === firstElement) {
      event.preventDefault();
      lastElement.focus();
    } else if (!event.shiftKey && document.activeElement === lastElement) {
      event.preventDefault();
      firstElement.focus();
    }
  };

  useEffect(() => {
    if (activeDrawerCabin) {
      window.setTimeout(() => drawerSearchRef.current?.focus(), 0);
    }
  }, [activeDrawerCabin]);

  useEffect(() => {
    if (editing) {
      window.setTimeout(() => editTitleRef.current?.focus(), 0);
    }
  }, [editing]);

  useEffect(() => {
    const state = location.state as DnaRouteState | null;
    const params = new URLSearchParams(location.search);
    const queryCabinId = params.get('cabin');
    const ruleParam = params.get('rule');
    const queryRuleId = ruleParam?.trim() ? Number(ruleParam) : null;
    const highlightCabinId = isCabinId(queryCabinId)
      ? queryCabinId
      : state && isCabinId(state.highlightCabinId)
        ? state.highlightCabinId
        : null;
    const highlightRuleId = queryRuleId !== null && Number.isFinite(queryRuleId)
      ? queryRuleId
      : typeof state?.highlightRuleId === 'number'
        ? state.highlightRuleId
        : null;

    if (!highlightCabinId) return;

    const stateKey = `${location.key}:${highlightCabinId}:${highlightRuleId ?? 'category'}`;
    if (processedHighlightRef.current === stateKey) return;
    processedHighlightRef.current = stateKey;
    setLibraryFilters({ ...emptyDnaFilters, category: highlightCabinId });
    if (highlightRuleId === null) return;
    setHighlightedRule({ cabinId: highlightCabinId, ruleId: highlightRuleId });
    setSearchKeywords((prev) => ({ ...prev, [highlightCabinId]: '' }));
    openDrawer(highlightCabinId);
  }, [location.key, location.search, location.state, openDrawer, setSearchKeywords]);

  return (
    <div className="studio-shell studio-library studio-memory relative min-h-screen overflow-x-hidden">
      <div
        aria-hidden={isAnyDnaOverlayOpen ? true : undefined}
        className={isAnyDnaOverlayOpen ? 'pointer-events-none' : undefined}
      >
        <Header variant="studio" />

        <main id="main-content" className="studio-page-main"><div className="studio-page-content">
          <fieldset disabled={!canEditRules} className="memory-toolbar min-w-0">
            <div className="memory-overview">
              <h2>{isZh ? '创作偏好' : 'Design preferences'}</h2>
              <p aria-live="polite">{isZh ? `${evoStats.total} 条偏好 · ${evoStats.enabled} 条已启用` : `${evoStats.total} ${evoStats.total === 1 ? 'preference' : 'preferences'} · ${evoStats.enabled} enabled`}</p>
            </div>
            <div className="memory-toolbar-actions">
              {canCreateWithCurrentDna && <button type="button" onClick={createWithCurrentDna}
                aria-describedby="dna-create-with-current-status" className="studio-secondary">
                <Zap size={15} />{isZh ? '开始创作' : 'Start creating'}
              </button>}
              <button ref={primaryAddRef} type="button" onClick={openCloneFromButton} className="studio-primary">
                <Plus size={15} />{BROWSER_MODE ? (isZh ? '添加偏好' : 'Add preference') : t('dna.page.heroPrimaryAction')}
              </button>
              <span id="dna-create-with-current-status" className="sr-only">{t(canCreateWithCurrentDna ? 'dna.page.heroCreateActionDesc' : 'dna.page.heroCreateDisabledDesc')}</span>
            </div>
          </fieldset>
          {syncStatus !== 'local' && syncStatus !== 'synced' && <DnaSyncStatus
            syncStatus={syncStatus} retrySync={retrySync} acceptServerRules={acceptServerRules} />}
          <DnaPreferenceLibrary cabins={cabins} library={ruleLibrary} filters={libraryFilters}
            onFilterChange={setLibraryFilters} canEdit={canEditRules} onEdit={openEditFromButton}
            onToggle={toggleRuleEnabled} onManage={openDrawerFromButton} onAdd={openPreferenceFromButton}
            onExample={BROWSER_MODE ? (event, cabinId) => openPreferenceFromButton(event, cabinId, true) : undefined} />
        </div></main>
      </div>

      <div
        aria-hidden={isDrawerOpen && !showCloneModal && !editing ? undefined : true}
        className={`fixed inset-0 z-[60] transition ${isDrawerOpen ? 'pointer-events-auto' : 'pointer-events-none'}`}
      >
        <div className={`absolute inset-0 bg-slate-950/45 backdrop-blur-[1px] transition-opacity duration-500 ease-out dark:bg-slate-950/72 ${isDrawerOpen ? 'opacity-100' : 'opacity-0'}`} onClick={closeDrawerAndRestoreFocus} />
        <aside
          role={isDrawerOpen ? 'dialog' : undefined}
          aria-modal={isDrawerOpen ? true : undefined}
          aria-labelledby={isDrawerOpen ? 'dna-drawer-title' : undefined}
          onKeyDown={isDrawerOpen ? (event) => handleDialogTabTrap(event, event.currentTarget, closeDrawerAndRestoreFocus) : undefined}
          className={`memory-drawer absolute right-0 top-0 h-full w-full max-w-2xl transform border-l transition-transform duration-300 ease-out ${isDrawerOpen ? 'translate-x-0' : 'translate-x-full'}`}
        >
          {drawerCabin && activeDrawerCabin && (
            <div className="flex h-full flex-col">
              <div className="relative border-b border-white/40 p-4 dark:border-white/10">
                <div className={`absolute inset-x-0 top-0 h-1 bg-gradient-to-r ${drawerCabin.color.mask}`} />
                <div className="mb-3 flex items-center justify-between gap-2">
                  <div>
                    <h2 id="dna-drawer-title" className="text-sm font-semibold text-slate-900 dark:text-slate-100">{t('dna.page.drawerTitle')}</h2>
                    <p className="text-xs text-slate-600 dark:text-slate-300">{drawerCabin.name} · {drawerCabin.tag}</p>
                  </div>
                  <button type="button" onClick={closeDrawerAndRestoreFocus} aria-label={t('dna.page.closeDrawerLabel')} className="studio-secondary">
                    <X className="h-3.5 w-3.5" />
                    {t('dna.page.close')}
                  </button>
                </div>

                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <span className="mr-auto rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                    {t('dna.page.drawerSelectedCount').replace('{count}', String(drawerSelectedIds.length))}
                  </span>
                  <button type="button" onClick={() => batchSetEnabled(activeDrawerCabin, true)} disabled={drawerSelectedIds.length === 0} className="studio-secondary">
                    {t('dna.page.batchEnable')}
                  </button>
                  <button type="button" onClick={() => batchSetEnabled(activeDrawerCabin, false)} disabled={drawerSelectedIds.length === 0} className="studio-secondary">
                    {t('dna.page.batchDisable')}
                  </button>
                </div>

                <div className="relative">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    ref={drawerSearchRef}
                    value={searchKeywords[activeDrawerCabin]}
                    onChange={(event) => setSearchKeywords((prev) => ({ ...prev, [activeDrawerCabin]: event.target.value }))}
                    placeholder={t('dna.page.searchPlaceholder')}
                    className="studio-search pr-24"
                  />
                  <div className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center gap-2">
                    <span className="hidden text-xs font-semibold text-slate-500 sm:inline dark:text-slate-400">
                      {t('dna.page.drawerResultCount').replace('{count}', String(drawerRules.length))}
                    </span>
                    {drawerSearchTerm && (
                      <button
                        type="button"
                        onClick={() => setSearchKeywords((prev) => ({ ...prev, [activeDrawerCabin]: '' }))}
                        className="rounded-md px-2 py-1 text-xs font-semibold text-indigo-600 transition hover:bg-indigo-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 dark:text-indigo-300 dark:hover:bg-indigo-500/10"
                      >
                        {t('dna.page.drawerClearSearch')}
                      </button>
                    )}
                  </div>
                </div>
              </div>

              <div className="flex-1 space-y-2 overflow-y-auto p-4">
                {drawerRules.map((rule) => {
                  const isHighlightedRule = highlightedRule?.cabinId === activeDrawerCabin && highlightedRule.ruleId === rule.id;
                  return (
                  <div key={rule.id} className={`memory-drawer-rule flex flex-col gap-3 border-b px-1 py-4 transition-colors sm:flex-row sm:items-center ${isHighlightedRule ? 'border-emerald-300 bg-emerald-50/80 dark:border-emerald-500/55 dark:bg-emerald-500/12' : 'border-slate-200/70 dark:border-white/10'} ${rule.enabled ? '' : 'opacity-70 saturate-50'}`}>
                    <label className="inline-flex min-h-11 items-center gap-2 text-xs font-semibold text-slate-600 dark:text-slate-300">
                      <input type="checkbox" checked={drawerSelectedIds.includes(rule.id)} onChange={() => toggleSelectRule(activeDrawerCabin, rule.id)} aria-label={ruleActionLabel('dna.page.selectRuleLabel', rule.title)} className="h-5 w-5 rounded border-slate-300 text-brand-500 focus-visible:ring-2 focus-visible:ring-indigo-500/60" />
                      <span className="sm:sr-only">{t('dna.page.ruleSelectLabel')}</span>
                    </label>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">{rule.title}</p>
                        <span className={`rounded-full px-2 py-0.5 text-xs font-bold uppercase tracking-wider ${rule.enabled ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' : 'bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-300'}`}>
                          {rule.enabled ? t('dna.page.ruleActive') : t('dna.page.ruleInactive')}
                        </span>
                      </div>
                      <p className="line-clamp-2 text-xs text-slate-600 dark:text-slate-300">{rule.preview}</p>
                    </div>
                    <div className="flex items-center justify-end gap-2">
                      <button type="button" onClick={(event) => openEditFromButton(event, activeDrawerCabin, rule)} aria-label={ruleActionLabel('dna.page.editRuleLabel', rule.title)} className="min-h-11 rounded-md px-3 py-2 text-xs font-medium text-slate-600 transition hover:text-indigo-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:ring-offset-2 dark:text-slate-300 dark:hover:text-indigo-300 dark:focus-visible:ring-offset-slate-950">{t('dna.page.edit')}</button>
                      <button type="button" onClick={() => toggleRuleEnabled(activeDrawerCabin, rule.id)} aria-label={ruleActionLabel(rule.enabled ? 'dna.page.disableRuleLabel' : 'dna.page.enableRuleLabel', rule.title)} aria-pressed={rule.enabled} className="min-h-11 rounded-md px-3 py-2 text-xs font-medium text-slate-600 transition hover:text-indigo-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:ring-offset-2 dark:text-slate-300 dark:hover:text-indigo-300 dark:focus-visible:ring-offset-slate-950">{rule.enabled ? t('dna.page.disable') : t('dna.page.enable')}</button>
                    </div>
                  </div>
                  );
                })}

                {drawerRules.length === 0 && (
                  <div className="px-2 py-4 text-sm text-slate-500 dark:text-slate-400">
                    <p>{drawerSearchTerm ? t('dna.page.drawerNoSearchResults') : t('dna.page.emptyState')}</p>

                  </div>
                )}
              </div>
            </div>
          )}
        </aside>
      </div>

      {addingPreference && <BrowserPreferenceDialog initialCategory={newPreferenceCategory} initialDraft={prefillPreference ? dnaPreferenceExample(newPreferenceCategory, language) : undefined} onClose={() => { setAddingPreference(false); restoreAddFocus(); }} onSave={(category, title, description) => {
        setRuleLibrary(previous => ({ ...previous, [category]: [...previous[category], {
          id: Math.max(0, ...Object.values(previous).flat().map(rule => rule.id)) + 1,
          title, preview: description, source: 'manual', enabled: true, pinned: true, usageCount: 0, updatedAt: isZh ? '刚刚' : 'just now',
        }] }));
        setLibraryFilters({ ...emptyDnaFilters, category });
        setAddingPreference(false); restoreAddFocus();
        showToast(t('studio.preferenceSaved'), 'success');
      }} />}
      {showCloneModal && (
        <CloneModal
          t={t}
          cloneStepList={cloneStepList}
          cloneCurrentStepIndex={cloneCurrentStepIndex}
          cloneStatus={cloneStatus}
          cloneFileName={cloneFileName}
          setCloneFileName={setCloneFileName}
          onFileChange={setCloneFile}
          setCloneStep={setCloneStep}
          cloneCandidates={cloneCandidates}
          cloneMessage={cloneMessage}
          runCloneExtraction={runCloneExtraction}
          updateCloneCandidate={updateCloneCandidate}
          applyCloneCandidates={applyCloneCandidates}
          cloneCandidateErrors={cloneCandidateErrors}
          hasCloneCandidateErrors={hasCloneCandidateErrors}
          selectedCandidateCount={selectedCandidateCount}
          canApplyCloneCandidates={canApplyCloneCandidates}
          onClose={closeCloneModal}
        />
      )}

      {editing && (
        <div
          className="studio-modal-backdrop fixed inset-0 z-[70] flex items-end justify-center px-3 py-3 sm:items-center sm:px-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="dna-edit-dialog-title"
          onKeyDown={(event) => handleDialogTabTrap(event, editDialogRef.current, closeEditModal)}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeEditModal();
          }}
        >
          <div ref={editDialogRef} className="studio-dialog-panel max-h-[calc(100dvh-1.5rem)] w-full max-w-lg overflow-y-auto p-5 sm:p-6">
            <h3 id="dna-edit-dialog-title" className="text-lg font-semibold text-slate-900 dark:text-slate-100">{t('dna.page.modalTitle')}</h3>
            <div className="mt-4 space-y-3">
              <label className="block">
                <span className="mb-1 block text-xs font-semibold text-slate-500 dark:text-slate-300">{t('dna.page.modalRuleName')}</span>
                <input
                  ref={editTitleRef}
                  value={draftTitle}
                  aria-invalid={editErrors.title}
                  aria-describedby={editErrors.title ? 'dna-edit-title-error' : undefined}
                  onChange={(event) => {
                    setDraftTitle(event.target.value);
                    if (editErrors.title && event.target.value.trim()) {
                      setEditErrors((prev) => ({ ...prev, title: false }));
                    }
                  }}
                  className="studio-form-input"
                />
                {editErrors.title && <p id="dna-edit-title-error" role="alert" className="mt-1 text-xs font-medium text-rose-600 dark:text-rose-300">{t('dna.page.modalRuleNameRequired')}</p>}
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-semibold text-slate-500 dark:text-slate-300">{t('dna.page.modalRulePreview')}</span>
                <textarea
                  value={draftPreview}
                  aria-invalid={editErrors.preview}
                  aria-describedby={editErrors.preview ? 'dna-edit-preview-error' : undefined}
                  onChange={(event) => {
                    setDraftPreview(event.target.value);
                    if (editErrors.preview && event.target.value.trim()) {
                      setEditErrors((prev) => ({ ...prev, preview: false }));
                    }
                  }}
                  rows={4}
                  className="studio-form-input"
                />
                {editErrors.preview && <p id="dna-edit-preview-error" role="alert" className="mt-1 text-xs font-medium text-rose-600 dark:text-rose-300">{t('dna.page.modalRulePreviewRequired')}</p>}
              </label>
            </div>
            <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={closeEditModal} className="studio-secondary">{t('dna.page.cancel')}</button>
              <button type="button" onClick={submitEdit} disabled={!canSaveEdit} className="studio-primary">{t('dna.page.save')}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
