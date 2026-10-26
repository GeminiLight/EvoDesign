import { Dna, SearchX, X } from 'lucide-react';
import type { GalleryDna } from '../../data/galleryMockData';
import { DnaCard } from './DnaCard';

interface DnaMarketGridProps {
  dnaList: GalleryDna[];
  isLoading: boolean;
  t: (key: string) => string;
  language: string;
  onClickDna: (dna: GalleryDna) => void;
  onInjectDna?: (dna: GalleryDna) => void;
  hasActiveSearch?: boolean;
  onClearSearch?: () => void;
}

const SkeletonDna = () => (
  <div className="gallery-skeleton h-56 rounded-2xl border border-slate-200 bg-slate-100 dark:border-slate-700 dark:bg-slate-800" />
);

export const DnaMarketGrid = ({
  dnaList,
  isLoading,
  t,
  language,
  onClickDna,
  onInjectDna,
  hasActiveSearch = false,
  onClearSearch,
}: DnaMarketGridProps) => {
  if (isLoading) {
    return (
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <SkeletonDna key={i} />
        ))}
      </div>
    );
  }

  if (dnaList.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-white/55 px-5 py-14 text-center dark:border-slate-700 dark:bg-slate-900/45">
        <div className="relative flex h-12 w-12 items-center justify-center rounded-2xl bg-violet-50 text-violet-500 dark:bg-violet-500/15 dark:text-violet-300">
          <Dna className="h-5 w-5" />
          <SearchX className="absolute -right-1 -top-1 h-4 w-4 rounded-full bg-white text-slate-400 dark:bg-slate-900 dark:text-slate-500" />
        </div>
        <p className="mt-4 text-sm font-semibold text-slate-700 dark:text-slate-200">{t('gallery.noResults')}</p>
        <p className="mt-1 max-w-sm text-xs leading-relaxed text-slate-500 dark:text-slate-400">{t('gallery.noResultsHint')}</p>

        {hasActiveSearch && onClearSearch && (
          <button
            type="button"
            onClick={onClearSearch}
            className="mt-5 inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 text-xs font-semibold text-slate-600 transition hover:border-brand-300 hover:text-brand-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300 dark:focus-visible:ring-offset-slate-950"
          >
            <X className="h-3.5 w-3.5" />
            {t('gallery.clearSearch')}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {dnaList.map((dna) => (
        <DnaCard
          key={dna.id}
          dna={dna}
          t={t}
          language={language}
          onClick={() => onClickDna(dna)}
          onInject={() => onInjectDna?.(dna)}
        />
      ))}
    </div>
  );
};
