import { useRef } from 'react';
import { ChevronDown, SlidersHorizontal, X } from 'lucide-react';
import type { IndustryTag, ComplexityTag } from '../../data/galleryMockData';
import { INDUSTRY_TAGS, COMPLEXITY_TAGS } from '../../data/galleryMockData';
import { ChoiceSelect } from '../ChoiceSelect';

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
  onResetFilters: () => void;
}

export const GalleryFilterBar = ({ t, activeTab, selectedIndustryTags, onToggleIndustry, selectedComplexity, onSetComplexity, sortBy, onSortChange, resultCount, onResetFilters }: GalleryFilterBarProps) => {
  const filters = useRef<HTMLDetailsElement>(null);
  const count = selectedIndustryTags.length + Number(Boolean(selectedComplexity));
  const labelKey = (prefix: string, tag: string) => `gallery.${prefix}${tag[0].toUpperCase()}${tag.slice(1)}`;
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-2 text-xs text-slate-500 dark:text-slate-400" aria-live="polite" aria-atomic="true">{t('gallery.resultCount').replace('{count}', String(resultCount))}</span>
        {activeTab === 'works' && <>
          <details ref={filters} className="relative" onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false; }} onKeyDown={(event) => { if (event.key === 'Escape') { event.currentTarget.open = false; event.currentTarget.querySelector('summary')?.focus(); } }}>
            <summary className="studio-secondary list-none cursor-pointer [&::-webkit-details-marker]:hidden"><SlidersHorizontal size={14} />{t('gallery.filters')}{count > 0 && <span className="text-indigo-600 dark:text-indigo-300">{count}</span>}<ChevronDown size={12} /></summary>
            <div className="absolute -left-16 top-full z-20 sm:left-0 mt-1 w-64 rounded-xl border border-slate-200 bg-white p-4 shadow-lg shadow-slate-900/5 dark:border-white/10 dark:bg-[#151b2c]">
              <fieldset><legend className="mb-2 text-xs font-medium text-slate-500">{t('gallery.filterIndustryLabel')}</legend>
                <div className="grid grid-cols-2 gap-x-3">{INDUSTRY_TAGS.map((tag) => <label key={tag} className="flex min-h-10 cursor-pointer items-center gap-2 text-xs text-slate-600 dark:text-slate-300"><input type="checkbox" checked={selectedIndustryTags.includes(tag)} onChange={() => onToggleIndustry(tag)} className="h-3.5 w-3.5 rounded border-slate-300 text-indigo-600 focus:ring-indigo-400 dark:border-slate-600 dark:bg-slate-800" />{t(labelKey('filter', tag))}</label>)}</div>
              </fieldset>
              <div className="mt-3 text-xs font-medium text-slate-500">
                <label htmlFor="gallery-complexity">{t('gallery.filterComplexityLabel')}</label>
                <ChoiceSelect id="gallery-complexity" className="choice-select-field mt-2" label={t('gallery.filterComplexityLabel')} value={selectedComplexity ?? ''} menuWidth="anchor"
                  options={[{ value: '', label: t('gallery.filterAll') }, ...COMPLEXITY_TAGS.map(tag => ({ value: tag, label: t(labelKey('complexity', tag)) }))]}
                  onChange={value => onSetComplexity(value as ComplexityTag || null)} />
              </div>
              <button type="button" className="studio-secondary mt-2 w-full" onClick={() => { if (filters.current) { filters.current.open = false; filters.current.querySelector('summary')?.focus(); } }}>{t('gallery.done')}</button>
            </div>
          </details>
          {count > 0 && <button type="button" onClick={onResetFilters} className="studio-secondary"><X size={13} />{t('gallery.resetFilters')}</button>}
        </>}
      </div>
      <ChoiceSelect label={t('gallery.sortByLabel')} value={sortBy} menuWidth={188} align="end" onChange={value => onSortChange(value as SortValue)}
        options={[{ value: 'trending', label: t('gallery.sortTrending') }, ...(activeTab === 'works' ? [{ value: 'newest', label: t('gallery.sortNewest') }] : []), { value: 'mostCloned', label: t('gallery.sortMostCloned') }]} />
    </div>
  );
};
