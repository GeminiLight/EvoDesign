import { RotateCcw, SearchX, X } from 'lucide-react';
import type { GalleryWork } from '../../data/galleryMockData';
import { WorkCard } from './WorkCard';

interface WorksGridProps {
  works: GalleryWork[];
  t: (key: string) => string;
  language: string;
  onClickWork: (work: GalleryWork) => void;
  onCloneWork?: (work: GalleryWork) => void;
  hasActiveSearch?: boolean;
  hasActiveFilters?: boolean;
  onClearSearch?: () => void;
  onResetFilters?: () => void;
}

export const WorksGrid = ({
  works,
  t,
  language,
  onClickWork,
  onCloneWork,
  hasActiveSearch = false,
  hasActiveFilters = false,
  onClearSearch,
  onResetFilters,
}: WorksGridProps) => {
  if (works.length === 0) {
    const showClearSearch = hasActiveSearch && onClearSearch;
    const showResetFilters = hasActiveFilters && onResetFilters;

    return (
      <div className="flex flex-col items-center justify-center px-5 py-14 text-center ">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-300">
          <SearchX className="h-5 w-5" />
        </div>
        <p className="mt-4 text-sm font-semibold text-slate-700 dark:text-slate-200">{t('gallery.noResults')}</p>
        <p className="mt-1 max-w-sm text-xs leading-relaxed text-slate-500 dark:text-slate-400">{t('gallery.noResultsHint')}</p>

        {(showClearSearch || showResetFilters) && (
          <div className="mt-5 flex w-full max-w-sm flex-col gap-2 sm:flex-row sm:justify-center">
            {showClearSearch && (
              <button
                type="button"
                onClick={onClearSearch}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 text-xs font-semibold text-slate-600 transition hover:border-brand-300 hover:text-brand-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300 dark:focus-visible:ring-offset-slate-950"
              >
                <X className="h-3.5 w-3.5" />
                {t('gallery.clearSearch')}
              </button>
            )}
            {showResetFilters && (
              <button
                type="button"
                onClick={onResetFilters}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-brand-600 px-4 text-xs font-semibold text-white transition hover:bg-brand-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-950"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                {t('gallery.resetFilters')}
              </button>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-x-6 gap-y-7 sm:grid-cols-2 lg:grid-cols-3">
      {works.map((work) => (
        <WorkCard
          key={work.id}
          work={work}
          t={t}
          language={language}
          onClick={() => onClickWork(work)}
          onClone={() => onCloneWork?.(work)}
        />
      ))}
    </div>
  );
};
