import type { KeyboardEvent } from 'react';
import { Search, X } from 'lucide-react';

interface GalleryHeroProps {
  t: (key: string) => string;
  searchQuery: string;
  onSearchChange: (value: string) => void;
  activeTab: 'works' | 'dna';
  onTabChange: (tab: 'works' | 'dna') => void;
}

export const GalleryHero = ({ t, searchQuery, onSearchChange, activeTab, onTabChange }: GalleryHeroProps) => {
  const tabs = ['works', 'dna'] as const;
  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 'works' : event.key === 'End' ? 'dna' : activeTab === 'works' ? 'dna' : 'works';
    onTabChange(next);
    document.getElementById(`gallery-tab-${next}`)?.focus();
  };

  return (
    <div className="gallery-heading">
      <div className="gallery-browse-bar">
        <div className="gallery-search">
          <Search size={15} className="pointer-events-none absolute left-3 top-3 text-slate-400" />
          <input type="search" value={searchQuery} onChange={(event) => onSearchChange(event.target.value)} placeholder={t('gallery.searchPlaceholder')} aria-label={t('gallery.searchAriaLabel')} className="studio-search pr-10 [&::-webkit-search-cancel-button]:appearance-none" />
          {searchQuery && <button type="button" onClick={() => onSearchChange('')} aria-label={t('gallery.clearSearch')} className="studio-icon-button absolute -right-0.5 -top-0.5"><X size={14} /></button>}
        </div>
      <div role="tablist" aria-label={t('gallery.tabsLabel')} className="gallery-tabs flex gap-5">
        {tabs.map((tab) => <button key={tab} id={`gallery-tab-${tab}`} type="button" role="tab" aria-selected={activeTab === tab} aria-controls="gallery-results-panel" tabIndex={activeTab === tab ? 0 : -1} onClick={() => onTabChange(tab)} onKeyDown={handleTabKeyDown} className={`inspiration-tab ${activeTab === tab ? 'inspiration-tab-active' : ''}`}>
          {t(tab === 'works' ? 'gallery.tabWorks' : 'gallery.tabDna')}
        </button>)}
      </div>
      </div>
    </div>
  );
};
