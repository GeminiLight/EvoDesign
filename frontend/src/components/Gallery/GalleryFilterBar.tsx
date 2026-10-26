import type { KeyboardEvent } from 'react';
import type { IndustryTag, ComplexityTag } from '../../data/galleryMockData';
import { INDUSTRY_TAGS, COMPLEXITY_TAGS } from '../../data/galleryMockData';

type SortValue = 'trending' | 'newest' | 'mostCloned';

interface GalleryFilterBarProps {
  t: (key: string) => string;
  activeTab: 'works' | 'dna';
  selectedIndustryTags: IndustryTag[];
  onToggleIndustry: (tag: IndustryTag) => void;
  selectedComplexity: ComplexityTag | null;
  onSetComplexity: (tag: ComplexityTag | null) => void;
  sortBy: SortValue;
  onSortChange: (sort: SortValue) => void;
  resultCount: number;
}

const INDUSTRY_I18N: Record<IndustryTag, string> = {
  fintech: 'gallery.filterFintech',
  healthcare: 'gallery.filterHealthcare',
  ecommerce: 'gallery.filterEcommerce',
  devops: 'gallery.filterDevops',
  education: 'gallery.filterEducation',
  gaming: 'gallery.filterGaming',
  saas: 'gallery.filterSaas',
  iot: 'gallery.filterIot',
};

const COMPLEXITY_I18N: Record<ComplexityTag, string> = {
  simple: 'gallery.complexitySimple',
  medium: 'gallery.complexityMedium',
  complex: 'gallery.complexityComplex',
};

const SORT_OPTIONS: Array<{ value: SortValue; key: string }> = [
  { value: 'trending', key: 'gallery.sortTrending' },
  { value: 'newest', key: 'gallery.sortNewest' },
  { value: 'mostCloned', key: 'gallery.sortMostCloned' },
];

const SORT_BUTTON_IDS: Record<SortValue, string> = {
  trending: 'gallery-sort-trending',
  newest: 'gallery-sort-newest',
  mostCloned: 'gallery-sort-most-cloned',
};

export const GalleryFilterBar = ({
  t,
  activeTab,
  selectedIndustryTags,
  onToggleIndustry,
  selectedComplexity,
  onSetComplexity,
  sortBy,
  onSortChange,
  resultCount,
}: GalleryFilterBarProps) => {
  // Glassmorphism pill styles
  const pillBase =
    'inline-flex min-h-11 shrink-0 items-center rounded-xl border px-3 py-2 text-xs font-medium transition-all cursor-pointer select-none backdrop-blur-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-brand-500 dark:focus-visible:ring-offset-slate-900';
  const pillOff =
    'border-white/40 bg-white/50 text-slate-600 shadow-sm hover:border-brand-300/60 hover:text-brand-600 hover:bg-white/70 dark:border-slate-600/50 dark:bg-slate-800/60 dark:text-slate-200 dark:hover:border-brand-500/50 dark:hover:text-brand-400 dark:hover:bg-slate-700/50';
  const pillOn =
    'border-brand-300/60 bg-brand-50/70 text-brand-700 shadow-sm shadow-brand-200/20 dark:border-brand-500/50 dark:bg-brand-500/15 dark:text-brand-300';

  const handleSortKeyDown = (event: KeyboardEvent<HTMLButtonElement>, value: SortValue) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;

    event.preventDefault();
    const currentIndex = SORT_OPTIONS.findIndex((opt) => opt.value === value);
    let nextValue: SortValue;

    if (event.key === 'Home') {
      nextValue = SORT_OPTIONS[0].value;
    } else if (event.key === 'End') {
      nextValue = SORT_OPTIONS[SORT_OPTIONS.length - 1].value;
    } else {
      const direction = event.key === 'ArrowRight' ? 1 : -1;
      nextValue = SORT_OPTIONS[(currentIndex + direction + SORT_OPTIONS.length) % SORT_OPTIONS.length].value;
    }

    onSortChange(nextValue);
    window.requestAnimationFrame(() => document.getElementById(SORT_BUTTON_IDS[nextValue])?.focus());
  };

  return (
    <div className="space-y-3">
      {/* Filter rows — one category per row */}
      {activeTab === 'works' && (
        <div className="space-y-2">
          {/* Row 1: Industry */}
          <div
            role="group"
            aria-label={t('gallery.filterIndustryLabel')}
            className="custom-scrollbar -mx-1 flex items-center gap-1.5 overflow-x-auto px-1 pb-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 sm:pb-0"
          >
            <span className="mr-1 text-[10px] font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">
              {t('gallery.filterIndustryLabel')}
            </span>
            {INDUSTRY_TAGS.map((tag) => (
              <button
                key={tag}
                type="button"
                aria-pressed={selectedIndustryTags.includes(tag)}
                onClick={() => onToggleIndustry(tag)}
                className={`${pillBase} ${selectedIndustryTags.includes(tag) ? pillOn : pillOff}`}
              >
                {t(INDUSTRY_I18N[tag])}
              </button>
            ))}
          </div>

          {/* Row 2: Complexity */}
          <div
            role="group"
            aria-label={t('gallery.filterComplexityLabel')}
            className="custom-scrollbar -mx-1 flex items-center gap-1.5 overflow-x-auto px-1 pb-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 sm:pb-0"
          >
            <span className="mr-1 text-[10px] font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">
              {t('gallery.filterComplexityLabel')}
            </span>
            {COMPLEXITY_TAGS.map((tag) => (
              <button
                key={tag}
                type="button"
                aria-pressed={selectedComplexity === tag}
                onClick={() => onSetComplexity(selectedComplexity === tag ? null : tag)}
                className={`${pillBase} ${selectedComplexity === tag ? pillOn : pillOff}`}
              >
                {t(COMPLEXITY_I18N[tag])}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Row 2: Result count + sort */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <span className="text-xs text-slate-500 dark:text-slate-400" aria-live="polite" aria-atomic="true">
          {t('gallery.resultCount').replace('{count}', String(resultCount))}
        </span>

        <div
          role="radiogroup"
          aria-label={t('gallery.sortByLabel')}
          className="custom-scrollbar flex max-w-full items-center gap-1 overflow-x-auto rounded-xl border border-white/40 bg-white/60 p-0.5 shadow-sm backdrop-blur-sm dark:border-slate-700/40 dark:bg-slate-800/60"
        >
          {SORT_OPTIONS.map((opt) => (
            <button
              id={SORT_BUTTON_IDS[opt.value]}
              key={opt.value}
              type="button"
              role="radio"
              aria-checked={sortBy === opt.value}
              tabIndex={sortBy === opt.value ? 0 : -1}
              onClick={() => onSortChange(opt.value)}
              onKeyDown={(event) => handleSortKeyDown(event, opt.value)}
              className={`min-h-11 shrink-0 rounded-lg px-3 py-1.5 text-xs font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-brand-500 dark:focus-visible:ring-offset-slate-900 ${
                sortBy === opt.value
                  ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-slate-100'
                  : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
              }`}
            >
              {t(opt.key)}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};
