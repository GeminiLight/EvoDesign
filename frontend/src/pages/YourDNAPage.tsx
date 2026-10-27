import { BROWSER_MODE } from '../services/browser/runtime';
import { BrowserPreferenceDialog } from '../components/DNA/BrowserPreferenceDialog';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  BrainCircuit,
  ChevronDown,
  LayoutTemplate,
  Palette,
  Pencil,
  Search,
  ToggleLeft,
  ToggleRight,
  WandSparkles,
  X,
  Zap,
} from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { DnaSyncStatus } from '../components/DNA/DnaSyncStatus';
import { Header } from '../components/Header';
import { CloneModal } from '../components/DNA/CloneModal';
import { useBackendAuth } from '../features/auth/BackendAuthProvider';
import { useLanguage } from '../i18n/LanguageProvider';
import { useToast } from '../components/toastContext';
import { useRuleLibrary } from '../hooks/useRuleLibrary';
import { useCloneFlow } from '../hooks/useCloneFlow';
import type { CabinId } from '../types/dna';
import { defaultConfigs } from '../constants/app';

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
    topRulesByCabin, toggleRuleEnabled, openEdit, saveEdit,
    openDrawer, closeDrawer, toggleSelectRule, batchSetEnabled,
    drawerRules, drawerSelectedIds,
  } = useRuleLibrary();

  const [addingPreference, setAddingPreference] = useState(false);
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
      code: t('dna.page.layoutCode'),
      icon: LayoutTemplate,
      color: {
        accent: 'text-teal-500 dark:text-teal-300',
        mask: 'from-teal-100/10 via-teal-200/20 to-teal-300/40 dark:from-teal-950/35 dark:via-teal-900/14 dark:to-teal-500/8',
      },
    },
  ], [t]);

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

  const openCloneFromButton = (event: React.MouseEvent<HTMLButtonElement>) => {
    cloneTriggerRef.current = event.currentTarget;
    if (BROWSER_MODE) setAddingPreference(true);
    else openCloneModal();
  };

  const closeCloneModal = () => {
    setShowCloneModal(false);
    window.setTimeout(() => cloneTriggerRef.current?.focus(), 0);
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
    const queryRuleId = Number(params.get('rule'));
    const highlightCabinId = isCabinId(queryCabinId)
      ? queryCabinId
      : state && isCabinId(state.highlightCabinId)
        ? state.highlightCabinId
        : null;
    const highlightRuleId = Number.isFinite(queryRuleId)
      ? queryRuleId
      : typeof state?.highlightRuleId === 'number'
        ? state.highlightRuleId
        : null;

    if (!highlightCabinId || highlightRuleId === null) return;

    const stateKey = `${highlightCabinId}:${highlightRuleId}`;
    if (processedHighlightRef.current === stateKey && activeDrawerCabin === highlightCabinId) return;
    processedHighlightRef.current = stateKey;
    setHighlightedRule({ cabinId: highlightCabinId, ruleId: highlightRuleId });
    setSearchKeywords((prev) => ({ ...prev, [highlightCabinId]: '' }));
    openDrawer(highlightCabinId);
  }, [activeDrawerCabin, location.search, location.state, openDrawer, setSearchKeywords]);

  return (
    <div className="bg-soft-mesh dark:bg-soft-mesh-dark relative min-h-screen overflow-hidden bg-slate-50 dark:bg-slate-950 text-slate-900 selection:bg-brand-500/30 dark:from-slate-950 dark:via-slate-950 dark:to-slate-950 dark:text-slate-100">
      <div
        aria-hidden={isAnyDnaOverlayOpen ? true : undefined}
        className={isAnyDnaOverlayOpen ? 'pointer-events-none' : undefined}
      >
        <Header />

        <main id="main-content" className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
          <fieldset disabled={!canEditRules} className="min-w-0">
            <section className="mb-6 flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
              <div className="max-w-2xl">
                <h1 className="font-display text-2xl font-semibold tracking-tight">{t('dna.page.heroTitlePrefix')}</h1>
                <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">{t('dna.page.heroSubtitle')}</p>
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-2">
                <button type="button" onClick={openCloneFromButton} className="studio-primary">
                  <WandSparkles size={16} />{BROWSER_MODE ? (isZh ? '添加设计偏好' : 'Add a preference') : t('dna.page.heroPrimaryAction')}
                </button>
                <button type="button" onClick={createWithCurrentDna} disabled={!canCreateWithCurrentDna}
                  aria-describedby="dna-create-with-current-status" className="studio-secondary">
                  <Zap size={15} />{t('dna.page.heroCreateAction')}
                </button>
                <span id="dna-create-with-current-status" className="sr-only">{t(canCreateWithCurrentDna ? 'dna.page.heroCreateActionDesc' : 'dna.page.heroCreateDisabledDesc')}</span>
              </div>
            </section>
          </fieldset>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-slate-200/70 pb-3 dark:border-white/[0.07]">
              <p className="flex gap-4 text-xs text-slate-500 dark:text-slate-400">
                <span>{t('dna.page.evoGenomeCount')} <strong className="ml-1 font-medium text-slate-700 dark:text-slate-200">{evoStats.total}</strong></span>
                <span>{t('dna.page.evoActiveCount')} <strong className="ml-1 font-medium text-violet-600 dark:text-violet-300">{evoStats.enabled}</strong></span>
              </p>
              <DnaSyncStatus syncStatus={syncStatus} retrySync={retrySync} acceptServerRules={acceptServerRules} />
            </div>
          <fieldset disabled={!canEditRules} className="min-w-0">
            <div className="divide-y divide-slate-200/70 dark:divide-white/[0.07]">
              {cabins.map((cabin) => {
                const CabinIcon = cabin.icon;
                const topRules = topRulesByCabin(cabin.id);
                return <section key={cabin.id} className="py-5 first:pt-2">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-800 dark:text-slate-100">
                      <CabinIcon size={17} className={cabin.color.accent} />{cabin.name}
                      <span className="ml-1 text-xs font-normal tabular-nums text-slate-400">{evoStats.counts[cabin.id]}</span>
                    </h2>
                    {topRules.length > 0 && <button type="button" onClick={(event) => openDrawerFromButton(event, cabin.id)} className="studio-secondary text-xs">
                      {t('dna.page.manageLibraryAction')}<ChevronDown size={14} className="-rotate-90" />
                    </button>}
                  </div>
                  {topRules.length === 0 ? <p className="py-2 pl-[25px] text-[13px] text-slate-500 dark:text-slate-400">{isZh ? '还没有保存的偏好' : 'No saved preferences yet'}</p> : (
                    <div className="divide-y divide-slate-200/50 dark:divide-white/[0.04]">
                      {topRules.map((rule) => <article key={rule.id} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:gap-6 sm:pl-[25px]">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                            <h3 className="break-words text-[13px] font-semibold text-slate-800 dark:text-slate-100">{rule.title}</h3>
                            <span className={`inline-flex items-center gap-1.5 text-[11px] ${rule.enabled ? 'text-violet-600 dark:text-violet-300' : 'text-slate-400'}`}>
                              <span className={`h-1.5 w-1.5 rounded-full ${rule.enabled ? 'bg-violet-400' : 'bg-slate-400'}`} />
                              {t(rule.enabled ? 'dna.page.ruleActive' : 'dna.page.ruleInactive')}
                            </span>
                          </div>
                          <p className="mt-1.5 line-clamp-2 max-w-3xl break-words text-[13px] leading-6 text-slate-500 dark:text-slate-400">{rule.preview}</p>
                          {!BROWSER_MODE && <p className="mt-1 text-[11px] text-slate-400 dark:text-slate-500">{t(rule.source === 'ai' ? 'dna.page.aiLearned' : 'dna.page.manualSet')} · {t('dna.page.usage')}: {rule.usageCount}</p>}
                        </div>
                        <div className="flex shrink-0 items-center gap-1 self-end sm:self-center">
                          <button type="button" onClick={(event) => openEditFromButton(event, cabin.id, rule)} aria-label={ruleActionLabel('dna.page.editRuleLabel', rule.title)} className="studio-secondary text-xs">
                            <Pencil size={13} />{t('dna.page.edit')}
                          </button>
                          <button type="button" onClick={() => toggleRuleEnabled(cabin.id, rule.id)} aria-label={ruleActionLabel(rule.enabled ? 'dna.page.disableRuleLabel' : 'dna.page.enableRuleLabel', rule.title)} aria-pressed={rule.enabled} className="studio-secondary text-xs">
                            {rule.enabled ? <ToggleRight size={18} className="text-violet-500 dark:text-violet-300" /> : <ToggleLeft size={18} />}
                            {t(rule.enabled ? 'dna.page.disable' : 'dna.page.enable')}
                          </button>
                        </div>
                      </article>)}
                    </div>
                  )}
                </section>;
              })}
            </div>
          </fieldset>
        </main>
      </div>

      <div
        aria-hidden={isDrawerOpen && !showCloneModal && !editing ? undefined : true}
        className={`fixed inset-0 z-40 transition ${isDrawerOpen ? 'pointer-events-auto' : 'pointer-events-none'}`}
      >
        <div className={`absolute inset-0 bg-slate-950/45 backdrop-blur-[1px] transition-opacity duration-500 ease-out dark:bg-slate-950/72 ${isDrawerOpen ? 'opacity-100' : 'opacity-0'}`} onClick={closeDrawerAndRestoreFocus} />
        <aside
          role={isDrawerOpen ? 'dialog' : undefined}
          aria-modal={isDrawerOpen ? true : undefined}
          aria-labelledby={isDrawerOpen ? 'dna-drawer-title' : undefined}
          onKeyDown={isDrawerOpen ? (event) => handleDialogTabTrap(event, event.currentTarget, closeDrawerAndRestoreFocus) : undefined}
          className={`absolute right-0 top-0 h-full w-full max-w-2xl transform border-l border-white/20 bg-white/88 shadow-2xl backdrop-blur-lg transition-transform duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] dark:border-white/8 dark:bg-slate-950/96 ${isDrawerOpen ? 'translate-x-0' : 'translate-x-full'}`}
        >
          {drawerCabin && activeDrawerCabin && (
            <div className="flex h-full flex-col">
              <div className="relative border-b border-white/40 p-4 dark:border-white/10">
                <div className={`absolute inset-x-0 top-0 h-1 bg-gradient-to-r ${drawerCabin.color.mask}`} />
                <div className="mb-3 flex items-center justify-between gap-2">
                  <div>
                    <h4 id="dna-drawer-title" className="text-sm font-semibold text-slate-900 dark:text-slate-100">{t('dna.page.drawerTitle')}</h4>
                    <p className="text-xs text-slate-600 dark:text-slate-300">{drawerCabin.name} · {drawerCabin.tag}</p>
                  </div>
                  <button type="button" onClick={closeDrawerAndRestoreFocus} aria-label={t('dna.page.closeDrawerLabel')} className="inline-flex min-h-11 items-center gap-1 rounded-lg border border-white/45 bg-white/75 px-3 py-2 text-xs font-semibold text-slate-700 transition hover:border-indigo-300 hover:text-indigo-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:ring-offset-2 dark:border-white/10 dark:bg-slate-900/78 dark:text-slate-200 dark:hover:border-indigo-500 dark:hover:text-indigo-300 dark:focus-visible:ring-offset-slate-950">
                    <X className="h-3.5 w-3.5" />
                    {t('dna.page.close')}
                  </button>
                </div>

                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <span className="mr-auto rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                    {t('dna.page.drawerSelectedCount').replace('{count}', String(drawerSelectedIds.length))}
                  </span>
                  <button type="button" onClick={() => batchSetEnabled(activeDrawerCabin, true)} disabled={drawerSelectedIds.length === 0} className="min-h-11 rounded-lg bg-emerald-100/90 px-3 py-2 text-xs font-semibold text-emerald-700 transition disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60 focus-visible:ring-offset-2 dark:bg-emerald-500/18 dark:text-emerald-300 dark:focus-visible:ring-offset-slate-950">
                    {t('dna.page.batchEnable')}
                  </button>
                  <button type="button" onClick={() => batchSetEnabled(activeDrawerCabin, false)} disabled={drawerSelectedIds.length === 0} className="min-h-11 rounded-lg bg-rose-100/90 px-3 py-2 text-xs font-semibold text-rose-700 transition disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-500/60 focus-visible:ring-offset-2 dark:bg-rose-500/18 dark:text-rose-300 dark:focus-visible:ring-offset-slate-950">
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
                    className="h-11 w-full rounded-xl border border-white/45 bg-white/85 pl-9 pr-24 text-sm text-slate-700 outline-none transition focus:border-indigo-300 focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:ring-offset-2 dark:border-white/10 dark:bg-slate-900/84 dark:text-slate-100 dark:focus-visible:ring-offset-slate-950"
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
                  <div key={rule.id} className={`flex flex-col gap-3 rounded-xl border px-3 py-3 backdrop-blur-sm transition sm:flex-row sm:items-center ${isHighlightedRule ? 'border-emerald-300 bg-emerald-50/80 shadow-[0_0_0_1px_rgba(16,185,129,0.22),0_16px_35px_-28px_rgba(16,185,129,0.75)] dark:border-emerald-500/55 dark:bg-emerald-500/12' : 'border-white/50 bg-white/68 dark:border-white/10 dark:bg-slate-900/76'} ${rule.enabled ? '' : 'opacity-70 saturate-50'}`}>
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

      {addingPreference && <BrowserPreferenceDialog onClose={() => { setAddingPreference(false); window.setTimeout(() => cloneTriggerRef.current?.focus(), 0); }} onSave={(category, title, description) => {
        setRuleLibrary(previous => ({ ...previous, [category]: [...previous[category], {
          id: Math.max(0, ...Object.values(previous).flat().map(rule => rule.id)) + 1,
          title, preview: description, source: 'manual', enabled: true, pinned: true, usageCount: 0, updatedAt: isZh ? '刚刚' : 'just now',
        }] }));
        setAddingPreference(false); window.setTimeout(() => cloneTriggerRef.current?.focus(), 0);
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
          className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/40 px-3 py-3 backdrop-blur-md sm:items-center sm:px-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="dna-edit-dialog-title"
          onKeyDown={(event) => handleDialogTabTrap(event, editDialogRef.current, closeEditModal)}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeEditModal();
          }}
        >
          <div ref={editDialogRef} className="max-h-[calc(100dvh-1.5rem)] w-full max-w-lg overflow-y-auto rounded-2xl border border-white/35 bg-white/90 p-4 shadow-2xl backdrop-blur-lg dark:border-white/8 dark:bg-slate-950/96 sm:p-5">
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
                  className="h-11 w-full rounded-xl border border-white/45 bg-white/85 px-3 text-sm text-slate-700 outline-none transition focus:border-indigo-300 focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:ring-offset-2 dark:border-white/10 dark:bg-slate-900/82 dark:text-slate-100 dark:focus-visible:ring-offset-slate-950"
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
                  className="w-full rounded-xl border border-white/45 bg-white/85 px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-indigo-300 focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:ring-offset-2 dark:border-white/10 dark:bg-slate-900/82 dark:text-slate-100 dark:focus-visible:ring-offset-slate-950"
                />
                {editErrors.preview && <p id="dna-edit-preview-error" role="alert" className="mt-1 text-xs font-medium text-rose-600 dark:text-rose-300">{t('dna.page.modalRulePreviewRequired')}</p>}
              </label>
            </div>
            <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={closeEditModal} className="min-h-11 rounded-lg border border-white/45 bg-white/75 px-4 py-2 text-sm font-medium text-slate-600 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:ring-offset-2 dark:border-white/10 dark:bg-slate-900/82 dark:text-slate-200 dark:focus-visible:ring-offset-slate-950">{t('dna.page.cancel')}</button>
              <button type="button" onClick={submitEdit} disabled={!canSaveEdit} className="min-h-11 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-950">{t('dna.page.save')}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
