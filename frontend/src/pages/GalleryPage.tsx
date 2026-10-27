import { useState, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { DnaSyncStatus } from '../components/DNA/DnaSyncStatus';
import { Header } from '../components/Header';
import { GalleryHero } from '../components/Gallery/GalleryHero';
import { GalleryFilterBar } from '../components/Gallery/GalleryFilterBar';
import { WorksGrid } from '../components/Gallery/WorksGrid';
import { DnaMarketGrid } from '../components/Gallery/DnaMarketGrid';
import { WorkPreviewModal } from '../components/Gallery/WorkPreviewModal';
import { DnaPreviewModal } from '../components/Gallery/DnaPreviewModal';
import { useLanguage } from '../i18n/LanguageProvider';
import { useToast } from '../components/toastContext';
import { useRuleLibrary } from '../hooks/useRuleLibrary';
import {
  GALLERY_WORKS,
  GALLERY_DNA,
} from '../data/galleryMockData';
import type { GalleryWork, GalleryDna, IndustryTag, ComplexityTag } from '../data/galleryMockData';
import type { CabinId } from '../types/dna';
import type { DiagramType } from '../types/api';
import { defaultConfigs } from '../constants/app';

const WORKS_TAB_ID = 'gallery-tab-works';
const DNA_TAB_ID = 'gallery-tab-dna';
const RESULTS_PANEL_ID = 'gallery-results-panel';

const toWorkspaceDiagramType = (diagramType: string): DiagramType => {
  switch (diagramType) {
    case 'architecture':
      return 'architecture';
    case 'flowchart':
    case 'swimlane':
      return 'flow';
    case 'sequence':
      return 'sequence';
    case 'er':
      return 'er';
    case 'mindmap':
      return 'mindmap';
    case 'network':
    case 'stateDiagram':
      return 'network';
    case 'gantt':
    default:
      return 'automated';
  }
};

export const GalleryPage = () => {
  const { t, language } = useLanguage();
  const navigate = useNavigate();
  const ruleLib = useRuleLibrary();
  const { ruleLibrary, setRuleLibrary, canEditRules } = ruleLib;
  const { showToast } = useToast();

  // ─── Local state ─────────────────────────
  const [activeTab, setActiveTab] = useState<'works' | 'dna'>('works');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedIndustryTags, setSelectedIndustryTags] = useState<IndustryTag[]>([]);
  const [selectedComplexity, setSelectedComplexity] = useState<ComplexityTag | null>(null);
  const [sortBy, setSortBy] = useState<'trending' | 'newest' | 'mostCloned'>('trending');
  const [previewWork, setPreviewWork] = useState<GalleryWork | null>(null);
  const [previewDna, setPreviewDna] = useState<GalleryDna | null>(null);
  const [injectedDnaNotice, setInjectedDnaNotice] = useState<{ name: string; cabinId: CabinId; ruleId: number } | null>(null);

  const handleCloneWork = useCallback((work: GalleryWork) => {
    const title = language === 'zh' ? work.titleZh : work.title;
    const description = language === 'zh' ? work.descriptionZh : work.description;
    const promptText = `${title}\n\n${description}`.trim();
    const diagramType = toWorkspaceDiagramType(work.diagramType);
    const llmConfigId = defaultConfigs[0]?.id ?? 'default';
    navigate('/workspace', {
      state: {
        preflightGeneration: true,
        preflightKind: 'gallery',
        preflightSourceName: title,
        preflightSourceDescription: description,
        initialPrompt: promptText,
        initialDiagramType: diagramType,
        initialLlmConfigId: llmConfigId,
        initialCanvasMode: 'excalidraw',
        initialSource: 'gallery',
      },
    });
  }, [navigate, language]);

  const handleInjectDna = useCallback((dna: GalleryDna) => {
    if (!canEditRules) { showToast(language === 'zh' ? '请先完成设计记忆的加载或恢复。' : 'Load or recover your design memory first.', 'info'); return; }
    const name = language === 'zh' ? dna.nameZh : dna.name;
    const description = language === 'zh' ? dna.descriptionZh : dna.description;
    const targetCabin = dna.category as CabinId;
    const nextId = Math.max(
      ...(['structure', 'style', 'layout'] as CabinId[]).flatMap((cabinId) => ruleLibrary[cabinId].map((rule) => rule.id)),
      0,
    ) + 1;

    setRuleLibrary((prev) => {
      return {
        ...prev,
        [targetCabin]: [
          {
            id: nextId,
            title: name,
            preview: description,
            source: 'ai',
            enabled: true,
            pinned: true,
            usageCount: 0,
            updatedAt: language === 'zh' ? '刚刚' : 'just now',
          },
          ...prev[targetCabin],
        ],
      };
    });

    setInjectedDnaNotice({ name, cabinId: targetCabin, ruleId: nextId });
    showToast(t('gallery.dnaInjectedToast').replace('{name}', name), 'success');
    setPreviewDna(null);
  }, [canEditRules, language, ruleLibrary, setRuleLibrary, showToast, t]);

  const handleUndoInjectedDna = useCallback(() => {
    if (!injectedDnaNotice) return;

    setRuleLibrary((prev) => ({
      ...prev,
      [injectedDnaNotice.cabinId]: prev[injectedDnaNotice.cabinId].filter(
        (rule) => rule.id !== injectedDnaNotice.ruleId,
      ),
    }));
    showToast(t('gallery.dnaInjectUndoneToast').replace('{name}', injectedDnaNotice.name), 'info');
    setInjectedDnaNotice(null);
  }, [injectedDnaNotice, setRuleLibrary, showToast, t]);

  const handleTabChange = useCallback((tab: 'works' | 'dna') => {
    setActiveTab(tab);
    setSortBy('trending');
  }, []);

  // ─── Filter toggles ─────────────────────
  const handleToggleIndustry = useCallback((tag: IndustryTag) => {
    setSelectedIndustryTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );
  }, []);

  const hasActiveSearch = searchQuery.trim().length > 0;
  const hasActiveWorksFilters = selectedIndustryTags.length > 0 || selectedComplexity !== null;

  const handleClearSearch = useCallback(() => {
    setSearchQuery('');
  }, []);

  const handleResetFilters = useCallback(() => {
    setSelectedIndustryTags([]);
    setSelectedComplexity(null);
  }, []);

  // ─── Derived data ───────────────────────
  const filteredWorks = useMemo(() => {
    let result = [...GALLERY_WORKS];

    // Search
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      result = result.filter(
        (w) =>
          w.title.toLowerCase().includes(q) ||
          w.titleZh.includes(q) ||
          w.description.toLowerCase().includes(q) ||
          w.descriptionZh.includes(q) ||
          t(`gallery.diagram_${w.diagramType}`).toLowerCase().includes(q) ||
          w.diagramType.toLowerCase().includes(q),
      );
    }

    // Industry filter
    if (selectedIndustryTags.length > 0) {
      result = result.filter((w) => selectedIndustryTags.includes(w.industry));
    }

    // Complexity filter
    if (selectedComplexity) {
      result = result.filter((w) => w.complexity === selectedComplexity);
    }

    // Sort
    if (sortBy === 'trending') {
      // Preserve the curated sample order.
    } else if (sortBy === 'newest') {
      result.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
    } else {
      result.sort((a, b) => (language === 'zh' ? a.titleZh : a.title).localeCompare(language === 'zh' ? b.titleZh : b.title, language));
    }

    return result;
  }, [searchQuery, selectedIndustryTags, selectedComplexity, sortBy, language, t]);

  const filteredDna = useMemo(() => {
    let result = [...GALLERY_DNA];

    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      result = result.filter(
        (d) =>
          d.name.toLowerCase().includes(q) ||
          d.nameZh.includes(q) ||
          d.description.toLowerCase().includes(q) ||
          d.descriptionZh.includes(q) ||
          d.category.toLowerCase().includes(q),
      );
    }

    // Sort
    if (sortBy === 'mostCloned') {
      result.sort((a, b) => (language === 'zh' ? a.nameZh : a.name).localeCompare(language === 'zh' ? b.nameZh : b.name, language));
    }

    return result;
  }, [searchQuery, sortBy, language]);

  const resultCount = activeTab === 'works' ? filteredWorks.length : filteredDna.length;

  return (
    <div className="min-h-screen flex flex-col bg-[#fafbfe] dark:bg-[#080d1b]">
      <Header />

      <GalleryHero
        t={t}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        activeTab={activeTab}
        onTabChange={handleTabChange}
      />

      <main id="main-content" className="mx-auto flex w-full max-w-6xl flex-1 flex-col px-4 pb-12 sm:px-6">
        {activeTab === 'dna' && <DnaSyncStatus {...ruleLib} />}
        <div className="flex w-full flex-col gap-5 lg:flex-row lg:gap-6">
          {/* Left: filter + content */}
          <div className="min-w-0 flex-1">
            <GalleryFilterBar
              t={t}
              activeTab={activeTab}
              selectedIndustryTags={selectedIndustryTags}
              onToggleIndustry={handleToggleIndustry}
              selectedComplexity={selectedComplexity}
              onSetComplexity={setSelectedComplexity}
              sortBy={sortBy}
              onSortChange={setSortBy}
              resultCount={resultCount}
              onResetFilters={handleResetFilters}
            />

            {injectedDnaNotice && (
              <div className="flex flex-col gap-3 rounded-xl border border-emerald-200 bg-emerald-50/80 px-4 py-3 text-sm text-emerald-800 shadow-sm backdrop-blur dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200 sm:flex-row sm:items-center sm:justify-between">
                <p className="font-medium">
                  {t('gallery.dnaInjectedInline').replace('{name}', injectedDnaNotice.name)}
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => navigate(`/dna?cabin=${injectedDnaNotice.cabinId}&rule=${injectedDnaNotice.ruleId}`)}
                    className="inline-flex min-h-11 items-center justify-center rounded-lg bg-emerald-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-emerald-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-900"
                  >
                    {t('gallery.viewInDna')}
                  </button>
                  <button
                    type="button"
                    onClick={handleUndoInjectedDna}
                    className="inline-flex min-h-11 items-center justify-center rounded-lg border border-emerald-300 bg-emerald-100/80 px-3 py-2 text-xs font-semibold text-emerald-800 transition hover:border-emerald-400 hover:bg-emerald-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60 focus-visible:ring-offset-2 dark:border-emerald-500/35 dark:bg-emerald-500/15 dark:text-emerald-100 dark:hover:border-emerald-400/50 dark:hover:bg-emerald-500/20 dark:focus-visible:ring-offset-slate-900"
                  >
                    {t('gallery.undoInjectDna')}
                  </button>
                  <button
                    type="button"
                    onClick={() => setInjectedDnaNotice(null)}
                    className="inline-flex min-h-11 items-center justify-center rounded-lg border border-emerald-200 bg-white/70 px-3 py-2 text-xs font-semibold text-emerald-700 transition hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60 focus-visible:ring-offset-2 dark:border-emerald-500/30 dark:bg-slate-900/60 dark:text-emerald-200 dark:hover:bg-slate-900 dark:focus-visible:ring-offset-slate-900"
                  >
                    {t('common.dismissNotification')}
                  </button>
                </div>
              </div>
            )}

            <div
              id={RESULTS_PANEL_ID}
              key={activeTab}
              role="tabpanel"
              aria-labelledby={activeTab === 'works' ? WORKS_TAB_ID : DNA_TAB_ID}
              tabIndex={0}
              className="gallery-cross-fade-in rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-brand-500 dark:focus-visible:ring-offset-slate-900"
            >
              {activeTab === 'works' ? (
                <WorksGrid
                  works={filteredWorks}
                  t={t}
                  language={language}
                  onClickWork={setPreviewWork}
                  onCloneWork={handleCloneWork}
                  hasActiveSearch={hasActiveSearch}
                  hasActiveFilters={hasActiveWorksFilters}
                  onClearSearch={handleClearSearch}
                  onResetFilters={handleResetFilters}
                />
              ) : (
                <DnaMarketGrid
                  dnaList={filteredDna}
                  t={t}
                  language={language}
                  onClickDna={setPreviewDna}
                  hasActiveSearch={hasActiveSearch}
                  onClearSearch={handleClearSearch}
                />
              )}
            </div>
          </div>

        </div>
      </main>

      {/* Modals */}
      {previewWork && (
        <WorkPreviewModal
          work={previewWork}
          t={t}
          language={language}
          onClose={() => setPreviewWork(null)}
          onClone={() => handleCloneWork(previewWork)}
        />
      )}
      {previewDna && (
        <DnaPreviewModal
          dna={previewDna}
          t={t}
          language={language}
          onClose={() => setPreviewDna(null)}
          onInject={() => handleInjectDna(previewDna)}
        />
      )}
    </div>
  );
};
