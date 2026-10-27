import { BROWSER_MODE } from '../services/browser/runtime';
import { BrowserPreferenceDialog } from '../components/DNA/BrowserPreferenceDialog';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  BrainCircuit,
  ChevronDown,
  LayoutTemplate,
  Palette,
  Pencil,
  Pin,
  Radio,
  Search,
  Sparkles,
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

  const displayName = user
    ? (user.username || user.email?.split('@')[0] || 'User')
    : t(BROWSER_MODE ? 'browser.localMode' : 'common.guestMode');

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
  const [heroOffset, setHeroOffset] = useState({ x: 0, y: 0 });
  const [cardGlow, setCardGlow] = useState<Record<string, { x: number; y: number; active: boolean }>>({});
  const cloneTriggerRef = useRef<HTMLButtonElement | null>(null);
  const drawerTriggerRef = useRef<HTMLButtonElement | null>(null);
  const drawerSearchRef = useRef<HTMLInputElement | null>(null);
  const editDialogRef = useRef<HTMLDivElement | null>(null);
  const editTitleRef = useRef<HTMLInputElement | null>(null);
  const editTriggerRef = useRef<HTMLButtonElement | null>(null);
  const heroFrameRef = useRef<number | null>(null);
  const cardGlowFrameRef = useRef<number | null>(null);
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
        border: 'border-indigo-300/70 dark:border-indigo-500/35',
        badge: 'bg-indigo-500/10 text-indigo-700 dark:bg-indigo-500/16 dark:text-indigo-200',
        glow: 'shadow-[inset_0_1px_0_rgba(255,255,255,0.55),0_10px_30px_-14px_rgba(99,102,241,0.65)] dark:shadow-none',
        mask: 'from-indigo-100/10 via-indigo-200/20 to-indigo-300/40 dark:from-indigo-950/35 dark:via-indigo-900/14 dark:to-indigo-500/8',
        glowLightRgb: '99,102,241',
        glowDarkRgb: '129,140,248',
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
        border: 'border-violet-300/70 dark:border-violet-500/35',
        badge: 'bg-violet-500/10 text-violet-700 dark:bg-violet-500/16 dark:text-violet-200',
        glow: 'shadow-[inset_0_1px_0_rgba(255,255,255,0.55),0_10px_30px_-14px_rgba(139,92,246,0.65)] dark:shadow-none',
        mask: 'from-violet-100/10 via-violet-200/20 to-violet-300/40 dark:from-violet-950/35 dark:via-violet-900/14 dark:to-violet-500/8',
        glowLightRgb: '139,92,246',
        glowDarkRgb: '167,139,250',
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
        border: 'border-teal-300/70 dark:border-teal-500/35',
        badge: 'bg-teal-500/10 text-teal-700 dark:bg-teal-500/16 dark:text-teal-200',
        glow: 'shadow-[inset_0_1px_0_rgba(255,255,255,0.55),0_10px_30px_-14px_rgba(20,184,166,0.55)] dark:shadow-none',
        mask: 'from-teal-100/10 via-teal-200/20 to-teal-300/40 dark:from-teal-950/35 dark:via-teal-900/14 dark:to-teal-500/8',
        glowLightRgb: '20,184,166',
        glowDarkRgb: '94,234,212',
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

  const setCardGlowPosition = (cardKey: string, x: number, y: number, active: boolean) => {
    if (cardGlowFrameRef.current !== null) {
      window.cancelAnimationFrame(cardGlowFrameRef.current);
    }
    cardGlowFrameRef.current = window.requestAnimationFrame(() => {
      setCardGlow((prev) => ({
        ...prev,
        [cardKey]: { x, y, active },
      }));
      cardGlowFrameRef.current = null;
    });
  };

  const setHeroParallax = (x: number, y: number) => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    if (heroFrameRef.current !== null) {
      window.cancelAnimationFrame(heroFrameRef.current);
    }
    heroFrameRef.current = window.requestAnimationFrame(() => {
      setHeroOffset({ x, y });
      heroFrameRef.current = null;
    });
  };

  useEffect(() => () => {
    if (heroFrameRef.current !== null) {
      window.cancelAnimationFrame(heroFrameRef.current);
    }
    if (cardGlowFrameRef.current !== null) {
      window.cancelAnimationFrame(cardGlowFrameRef.current);
    }
  }, []);

  const setCardGlowPositionImmediate = (cardKey: string, x: number, y: number, active: boolean) => {
    setCardGlow((prev) => ({
      ...prev,
      [cardKey]: { x, y, active },
    }));
  };

  const drawerCabin = activeDrawerCabin ? cabins.find((cabin) => cabin.id === activeDrawerCabin) ?? null : null;
  const isDrawerOpen = Boolean(activeDrawerCabin && drawerCabin);
  const drawerSearchTerm = activeDrawerCabin ? searchKeywords[activeDrawerCabin].trim() : '';
  const isAnyDnaOverlayOpen = isDrawerOpen || showCloneModal || Boolean(editing);

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

        <main id="main-content" className="relative mx-auto w-full max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <DnaSyncStatus syncStatus={syncStatus} retrySync={retrySync} acceptServerRules={acceptServerRules} />
        <fieldset disabled={!canEditRules} className="min-w-0">
        <section
          className="card-glass relative mb-7 overflow-hidden p-5 sm:p-6"
          onMouseMove={(event) => {
            const rect = event.currentTarget.getBoundingClientRect();
            const x = (event.clientX - rect.left - rect.width / 2) / rect.width;
            const y = (event.clientY - rect.top - rect.height / 2) / rect.height;
            setHeroParallax(x, y);
          }}
          onMouseLeave={() => setHeroParallax(0, 0)}
        >
          {/* Top-edge evolution scanline */}
          <div className="pointer-events-none absolute inset-x-0 top-0 h-[2px] overflow-hidden">
            <div className="dna-evo-scanline h-full w-full bg-gradient-to-r from-transparent via-indigo-400 to-transparent opacity-60 dark:via-indigo-500 dark:opacity-40" />
          </div>

          {/* Noise texture overlay */}
          <div className="pointer-events-none absolute inset-0 rounded-[28px] opacity-[0.03] dark:opacity-[0.05]" style={{ backgroundImage: 'url("data:image/svg+xml,%3Csvg viewBox=\'0 0 256 256\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cfilter id=\'n\'%3E%3CfeTurbulence type=\'fractalNoise\' baseFrequency=\'0.9\' numOctaves=\'4\' stitchTiles=\'stitch\'/%3E%3C/filter%3E%3Crect width=\'256\' height=\'256\' filter=\'url(%23n)\' opacity=\'1\'/%3E%3C/svg%3E")', backgroundRepeat: 'repeat', backgroundSize: '128px 128px' }} />

          {/* Animated DNA helix — slow drift parallax */}
          <div
            className="pointer-events-none absolute right-[-6%] top-[-12%] hidden h-[165%] w-[38%] opacity-30 dark:opacity-20 md:block"
            style={{ transform: `translate(${heroOffset.x * 14}px, ${heroOffset.y * 14}px)` }}
          >
            <svg viewBox="0 0 320 460" className="h-full w-full">
              <path d="M80 10 C220 70, 80 140, 220 210 C320 260, 130 340, 250 450" fill="none" stroke="rgba(99,102,241,0.30)" strokeWidth="2.5" className="dna-helix-strand" />
              <path d="M40 30 C190 90, 60 160, 200 230 C300 280, 100 360, 220 460" fill="none" stroke="rgba(139,92,246,0.22)" strokeWidth="1.5" className="dna-helix-strand" style={{ animationDelay: '-2s' }} />
              <path d="M120 20 C250 80, 120 150, 250 220 C330 275, 150 350, 270 455" fill="none" stroke="rgba(20,184,166,0.18)" strokeWidth="1.5" className="dna-helix-strand" style={{ animationDelay: '-4s' }} />
              {/* Cross rungs */}
              {[60, 120, 180, 240, 300, 360].map((y) => (
                <line key={y} x1={80 + (y % 120)} y1={y} x2={160 + (y % 80)} y2={y + 10} stroke="rgba(99,102,241,0.10)" strokeWidth="1" className="dna-helix-rung" style={{ animationDelay: `${y * -8}ms` }} />
              ))}
            </svg>
          </div>

          {/* Inner frosted glass edge highlight */}
          <div className="pointer-events-none absolute inset-0 rounded-[28px] ring-1 ring-inset ring-white/40 dark:ring-white/[0.06]" />

          <div className="relative flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="mb-2 text-xs font-medium text-slate-500 dark:text-slate-500">{t('dna.page.profileLabel')}</p>
              <div className="flex items-center gap-3">
                <h1 className="font-display text-3xl font-semibold tracking-tight">
                  {t('dna.page.heroTitlePrefix')}
                </h1>
                <span className="inline-flex items-center rounded-full border border-indigo-200/60 bg-indigo-50/60 px-2.5 py-0.5 text-xs font-semibold text-indigo-600 backdrop-blur-sm dark:border-indigo-500/25 dark:bg-indigo-500/10 dark:text-indigo-300">
                  {displayName}
                </span>
              </div>
              <p className="mt-2.5 max-w-2xl text-[15px] leading-relaxed text-slate-500 dark:text-slate-400">{t('dna.page.heroSubtitle')}</p>
            </div>

            <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
              {/* Primary CTA — DNA Cloning with glow */}
              <button
                type="button"
                onClick={openCloneFromButton}
                className="group/cta relative inline-flex min-h-11 w-full flex-col items-start gap-0.5 rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white shadow-[0_14px_28px_rgba(49,141,255,0.24)] transition-all hover:-translate-y-0.5 hover:bg-brand-500 hover:shadow-[0_18px_34px_rgba(49,141,255,0.3)] active:translate-y-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 sm:w-auto dark:shadow-brand-500/15 dark:focus-visible:ring-offset-slate-950"
              >
                <span className="relative inline-flex items-center gap-2">
                  <WandSparkles className="h-4 w-4 transition-transform duration-300 group-hover/cta:rotate-12" />
                  {BROWSER_MODE ? (isZh ? '添加设计偏好' : 'Add a preference') : t('dna.page.heroPrimaryAction')}
                </span>
                <span className="relative text-xs opacity-70 font-normal">{BROWSER_MODE ? (isZh ? '文字描述，本机保存' : 'Describe it. Keep it locally.') : t('dna.page.heroPrimaryActionDesc')}</span>
              </button>
              {/* Secondary — create with active DNA */}
              <button
                type="button"
                onClick={createWithCurrentDna}
                disabled={!canCreateWithCurrentDna}
                aria-describedby="dna-create-with-current-status"
                className="inline-flex min-h-11 w-full flex-col items-start gap-0.5 rounded-xl border border-brand-200/80 bg-white/72 px-4 py-2.5 text-[13px] font-semibold text-brand-700 shadow-sm backdrop-blur-md transition hover:border-brand-300 hover:bg-brand-50/80 hover:text-brand-800 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:border-slate-200/80 disabled:bg-white/45 disabled:text-slate-400 disabled:shadow-none disabled:hover:border-slate-200/80 disabled:hover:bg-white/45 disabled:hover:text-slate-400 disabled:active:scale-100 sm:w-auto dark:border-brand-500/30 dark:bg-slate-800/55 dark:text-brand-200 dark:hover:border-brand-400/50 dark:hover:bg-brand-500/10 dark:hover:text-brand-100 dark:disabled:border-slate-700 dark:disabled:bg-slate-900/45 dark:disabled:text-slate-500 dark:disabled:hover:border-slate-700 dark:disabled:hover:bg-slate-900/45 dark:disabled:hover:text-slate-500 dark:focus-visible:ring-offset-slate-950"
              >
                <span className="inline-flex items-center gap-1.5">
                  <Zap className="h-4 w-4" />
                  {t('dna.page.heroCreateAction')}
                </span>
                <span id="dna-create-with-current-status" className="text-xs opacity-70 font-normal">
                  {canCreateWithCurrentDna
                    ? t('dna.page.heroCreateActionDesc')
                    : t('dna.page.heroCreateDisabledDesc')}
                </span>
              </button>
            </div>
          </div>

          <div className="relative mt-4 grid grid-cols-1 gap-2 border-t border-white/30 pt-4 dark:border-white/[0.06] sm:grid-cols-3">
            {cabins.map((cabin) => {
              const CabinIcon = cabin.icon;
              const totalRules = evoStats.counts[cabin.id];

              return (
                <button
                  key={cabin.id}
                  type="button"
                  onClick={(event) => openDrawerFromButton(event, cabin.id)}
                  className="group/library flex min-h-12 items-center justify-between gap-3 rounded-xl border border-white/55 bg-white/62 px-3 py-2.5 text-left shadow-sm backdrop-blur-md transition hover:-translate-y-0.5 hover:border-brand-200 hover:bg-white/82 hover:shadow-[0_14px_26px_-20px_rgba(15,23,42,0.45)] active:translate-y-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:border-white/10 dark:bg-slate-900/72 dark:hover:border-brand-500/40 dark:hover:bg-slate-900/92 dark:focus-visible:ring-offset-slate-950"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/70 dark:bg-slate-950/45 ${cabin.color.accent}`}>
                      <CabinIcon className="h-4 w-4" />
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-semibold text-slate-800 dark:text-slate-100">
                        {cabin.name}
                      </span>
                      <span className="block text-xs text-slate-500 dark:text-slate-400">
                        {t('dna.page.manageLibraryAction')}
                      </span>
                    </span>
                  </span>
                  <span className="shrink-0 rounded-full bg-slate-100 px-2 py-1 font-mono text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                    {totalRules}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Evolution stats bar */}
          <div className="relative mt-5 flex flex-wrap items-center gap-x-5 gap-y-3 border-t border-white/30 pt-4 dark:border-white/[0.06]">
            {/* Genome counters */}
            <div className="flex items-center gap-1.5 text-xs">
              <span className="font-medium text-slate-500 dark:text-slate-400">{t('dna.page.evoGenomeCount')}</span>
              <span className="font-mono font-bold text-slate-700 dark:text-slate-200">{evoStats.total}</span>
            </div>
            <div className="flex items-center gap-1.5 text-xs">
              <span className="font-medium text-slate-500 dark:text-slate-400">{t('dna.page.evoActiveCount')}</span>
              <span className="font-mono font-bold text-emerald-600 dark:text-emerald-400">{evoStats.enabled}</span>
            </div>


          </div>

        </section>

        <section className="mb-4 flex flex-col gap-1.5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">
              {t('dna.page.sectionTitle')}
            </h2>
            <p className="mt-1 max-w-3xl text-sm leading-relaxed text-slate-500 dark:text-slate-400">
              {t('dna.page.sectionHint')}
            </p>
          </div>
        </section>

        <div className="space-y-4">
          {cabins.map((cabin) => {
            const CabinIcon = cabin.icon;
            const topRules = topRulesByCabin(cabin.id);

            return (
              <section key={cabin.id} className={`group relative overflow-hidden rounded-xl border bg-white p-5 dark:bg-slate-900 ${cabin.color.border}`}>
                <div className="pointer-events-none absolute inset-x-0 top-0 h-16 bg-gradient-to-b from-white/45 to-transparent dark:from-transparent" />
                <div className="mb-4 flex flex-col items-start justify-between gap-3 sm:flex-row">
                  <div className="relative pl-4">
                    <span className={`absolute left-0 top-1 h-9 w-1.5 rounded-full ${cabin.id === 'structure' ? 'bg-indigo-500/70' : cabin.id === 'style' ? 'bg-violet-500/70' : 'bg-teal-500/70'}`} />
                    <h3 className="flex items-center gap-2 text-xl font-bold leading-tight text-slate-900 dark:text-slate-100">
                      <CabinIcon className={`h-5 w-5 ${cabin.color.accent}`} />
                      {cabin.name}
                    </h3>
                  </div>
                </div>

                {topRules.length === 0 ? (
                  <div className="relative overflow-hidden rounded-2xl border border-dashed border-white/55 bg-white/35 p-5 text-sm text-slate-500 dark:border-white/10 dark:bg-slate-900/70 dark:text-slate-200">
                    {/* Scan line animation */}
                    <div className="pointer-events-none absolute inset-x-0 top-0 h-full overflow-hidden">
                      <div className="dna-scan-line absolute inset-x-0 h-[2px] bg-gradient-to-r from-transparent via-current to-transparent opacity-30" style={{ color: cabin.id === 'structure' ? 'rgb(99,102,241)' : cabin.id === 'style' ? 'rgb(139,92,246)' : 'rgb(20,184,166)' }} />
                    </div>
                    <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-400">
                      <Radio className="h-3.5 w-3.5 dna-scan-icon" />
                      {t('dna.page.observeTitle')}
                    </div>
                    <p className="font-mono text-[13px] leading-relaxed">{BROWSER_MODE ? (isZh ? '还没有偏好。添加一条你希望模型遵循的设计规则。' : 'No preferences yet. Add a design rule for your model to follow.') : t('dna.page.emptyState')}</p>
                    <button type="button" onClick={openCloneFromButton} className={`mt-3 inline-flex min-h-11 items-center gap-1 rounded-lg border px-3 py-2 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-950 ${cabin.id === 'structure' ? 'border-indigo-300/50 bg-indigo-100/55 text-indigo-700 focus-visible:ring-indigo-500/60 dark:border-indigo-500/35 dark:bg-indigo-500/12 dark:text-indigo-300' : cabin.id === 'style' ? 'border-violet-300/50 bg-violet-100/55 text-violet-700 focus-visible:ring-violet-500/60 dark:border-violet-500/35 dark:bg-violet-500/12 dark:text-violet-300' : 'border-teal-300/50 bg-teal-100/55 text-teal-700 focus-visible:ring-teal-500/60 dark:border-teal-500/35 dark:bg-teal-500/12 dark:text-teal-300'}`}>
                      <WandSparkles className="h-3.5 w-3.5" />
                      {BROWSER_MODE ? (isZh ? '添加偏好' : 'Add preference') : t('dna.page.clonePickHint')}
                    </button>
                    {/* Scan pulse rings */}
                    <div className="pointer-events-none absolute -bottom-2 right-8 flex h-24 w-24 items-center justify-center">
                      <span className="absolute h-3 w-3 rounded-full bg-current opacity-60 dna-scan-dot" style={{ color: cabin.id === 'structure' ? 'rgb(99,102,241)' : cabin.id === 'style' ? 'rgb(139,92,246)' : 'rgb(20,184,166)' }} />
                      <span className="absolute h-8 w-8 rounded-full border border-current opacity-30 dna-scan-ring-1" style={{ color: cabin.id === 'structure' ? 'rgb(99,102,241)' : cabin.id === 'style' ? 'rgb(139,92,246)' : 'rgb(20,184,166)' }} />
                      <span className="absolute h-14 w-14 rounded-full border border-current opacity-20 dna-scan-ring-2" style={{ color: cabin.id === 'structure' ? 'rgb(99,102,241)' : cabin.id === 'style' ? 'rgb(139,92,246)' : 'rgb(20,184,166)' }} />
                      <span className="absolute h-22 w-22 rounded-full border border-current opacity-10 dna-scan-ring-3" style={{ color: cabin.id === 'structure' ? 'rgb(99,102,241)' : cabin.id === 'style' ? 'rgb(139,92,246)' : 'rgb(20,184,166)' }} />
                    </div>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                    {topRules.map((rule) => {
                      const cardKey = `${cabin.id}-${rule.id}`;
                      return (
                        <article
                        key={rule.id}
                        className={`group/card relative rounded-2xl border border-slate-200 bg-white p-5 text-left shadow-[inset_0_1px_0_rgba(255,255,255,0.55),0_12px_28px_-20px_rgba(15,23,42,0.6)] transition hover:-translate-y-0.5 hover:bg-white/65 dark:border-white/8 dark:bg-slate-900/88 dark:shadow-none dark:hover:bg-slate-900/92 md:pb-20 ${rule.enabled ? '' : 'opacity-70 saturate-50'}`}
                        onMouseMove={(event) => {
                          const rect = event.currentTarget.getBoundingClientRect();
                          setCardGlowPosition(cardKey, event.clientX - rect.left, event.clientY - rect.top, true);
                        }}
                        onMouseLeave={() => {
                          setCardGlowPositionImmediate(cardKey, 0, 0, false);
                        }}
                      >
                        <div
                          className="pointer-events-none absolute inset-0 rounded-2xl opacity-0 transition-opacity duration-300 group-hover/card:opacity-100"
                          style={{
                            background: `radial-gradient(88px circle at ${cardGlow[cardKey]?.x ?? 0}px ${cardGlow[cardKey]?.y ?? 0}px, rgba(${cabin.color.glowLightRgb},0.08), rgba(${cabin.color.glowDarkRgb},0.04) 46%, transparent 72%)`,
                            opacity: cardGlow[cardKey]?.active ? 1 : 0,
                          }}
                        />
                        <div className="pointer-events-none absolute inset-0 rounded-2xl border border-white/30 opacity-0 transition-opacity duration-300 group-hover/card:opacity-100 group-hover/card:animate-[pulse_1.2s_ease-in-out_infinite] dark:border-white/12" />
                        <div className="mb-2 flex items-center gap-2">
                          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${rule.source === 'ai' ? 'bg-emerald-100/80 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' : 'bg-slate-100/80 text-slate-600 dark:bg-slate-800/75 dark:text-slate-300'}`}>
                            {rule.source === 'ai' ? <Sparkles className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />}
                            {rule.source === 'ai' ? t('dna.page.aiLearned') : t('dna.page.manualSet')}
                          </span>
                          <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-bold uppercase tracking-wider ${rule.enabled ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' : 'bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-300'}`}>
                            {rule.enabled ? t('dna.page.ruleActive') : t('dna.page.ruleInactive')}
                          </span>
                          {rule.pinned && (
                            <span className="ml-auto inline-flex h-6 w-6 items-center justify-center rounded-full border border-amber-300/70 bg-amber-100/65 text-amber-600 shadow-[0_0_14px_rgba(251,191,36,0.45)] dark:border-amber-400/40 dark:bg-amber-500/10 dark:text-amber-300">
                              <Pin className="h-3.5 w-3.5" />
                            </span>
                          )}
                        </div>

                        <h4 className="line-clamp-1 text-sm font-semibold leading-6 text-slate-900 dark:text-slate-100">{rule.title}</h4>
                        <p className="mt-2 line-clamp-2 text-[13px] leading-6 text-slate-600 dark:text-slate-300">{rule.preview}</p>

                        <div className="mt-4 flex items-center justify-between text-xs text-slate-500 dark:text-slate-300">
                          <span
                            className="inline-flex items-center gap-0.5 rounded px-1 -ml-1"
                            title={t('dna.page.usageTooltip')}
                          >
                            {t('dna.page.usage')}: {rule.usageCount}
                          </span>
                          <span>{t('dna.page.updated')}: {rule.updatedAt}</span>
                        </div>

                        <div className="relative z-10 mt-4 flex items-center justify-end gap-2 md:pointer-events-none md:absolute md:inset-x-3 md:bottom-3 md:mt-0 md:translate-y-1 md:opacity-0 md:transition md:duration-200 md:group-hover/card:pointer-events-auto md:group-hover/card:translate-y-0 md:group-hover/card:opacity-100 md:group-focus-within/card:pointer-events-auto md:group-focus-within/card:translate-y-0 md:group-focus-within/card:opacity-100">
                          <button type="button" onClick={(event) => openEditFromButton(event, cabin.id, rule)} aria-label={ruleActionLabel('dna.page.editRuleLabel', rule.title)} className="min-h-11 rounded-lg border border-white/50 bg-white/85 px-3 py-2 text-xs font-medium text-slate-700 backdrop-blur-md transition hover:border-indigo-300 hover:text-indigo-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:ring-offset-2 dark:border-white/10 dark:bg-slate-900/78 dark:text-slate-200 dark:hover:border-indigo-500 dark:hover:text-indigo-300 dark:focus-visible:ring-offset-slate-950">
                            {t('dna.page.edit')}
                          </button>
                          <button type="button" onClick={() => toggleRuleEnabled(cabin.id, rule.id)} aria-label={ruleActionLabel(rule.enabled ? 'dna.page.disableRuleLabel' : 'dna.page.enableRuleLabel', rule.title)} aria-pressed={rule.enabled} className="inline-flex min-h-11 items-center gap-1 rounded-lg bg-slate-100/95 px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:ring-offset-2 dark:bg-slate-800/85 dark:text-slate-200 dark:hover:bg-slate-700 dark:focus-visible:ring-offset-slate-950">
                            {rule.enabled ? <ToggleRight className="h-3.5 w-3.5" /> : <ToggleLeft className="h-3.5 w-3.5" />}
                            {rule.enabled ? t('dna.page.disable') : t('dna.page.enable')}
                          </button>
                        </div>
                      </article>
                      );
                    })}
                  </div>
                )}

                <div className="mt-4 hidden justify-center sm:flex">
                  <button
                    type="button"
                    onClick={(event) => openDrawerFromButton(event, cabin.id)}
                    className="group/expand inline-flex min-h-11 items-center gap-2 rounded-full border border-white/50 bg-white/70 px-5 py-2 text-xs font-semibold text-slate-700 backdrop-blur-md transition-all hover:border-slate-300 hover:bg-white/85 hover:text-slate-900 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:ring-offset-2 dark:border-white/10 dark:bg-slate-900/60 dark:text-slate-300 dark:hover:border-white/20 dark:hover:bg-slate-900/80 dark:hover:text-slate-100 dark:focus-visible:ring-offset-slate-950"
                  >
                    <ChevronDown className="h-3.5 w-3.5 transition-transform duration-300 group-hover/expand:translate-y-0.5" />
                    {t('dna.page.showMore')}
                  </button>
                </div>
              </section>
            );
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
                <div className={`absolute inset-x-0 top-0 h-1 bg-gradient-to-r ${drawerCabin.color.mask} motion-safe:animate-[pulse_1.6s_ease-in-out_infinite]`} />
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
                  <div className="rounded-2xl border border-dashed border-white/55 bg-white/35 p-5 text-sm text-slate-500 dark:border-white/10 dark:bg-slate-900/68 dark:text-slate-300">
                    <p>{drawerSearchTerm ? t('dna.page.drawerNoSearchResults') : t('dna.page.emptyState')}</p>
                    {drawerSearchTerm && (
                      <button type="button" onClick={() => setSearchKeywords((prev) => ({ ...prev, [activeDrawerCabin]: '' }))} className="mt-3 inline-flex min-h-11 items-center rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-indigo-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-950">
                        {t('dna.page.drawerClearSearch')}
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </aside>
      </div>

      {addingPreference && <BrowserPreferenceDialog onClose={() => { setAddingPreference(false); cloneTriggerRef.current?.focus(); }} onSave={(category, title, description) => {
        setRuleLibrary(previous => ({ ...previous, [category]: [...previous[category], {
          id: Math.max(0, ...Object.values(previous).flat().map(rule => rule.id)) + 1,
          title, preview: description, source: 'manual', enabled: true, pinned: true, usageCount: 0, updatedAt: isZh ? '刚刚' : 'just now',
        }] }));
        setAddingPreference(false); cloneTriggerRef.current?.focus();
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
