import { Plus } from 'lucide-react';
import type { GalleryDna } from '../../data/galleryMockData';
import { GalleryDialog } from './GalleryDialog';

interface DnaPreviewModalProps {
  dna: GalleryDna;
  t: (key: string) => string;
  language: string;
  onClose: () => void;
  onInject?: () => void;
}

export const DnaPreviewModal = ({ dna, t, language, onClose, onInject }: DnaPreviewModalProps) => {
  const name = language === 'zh' ? dna.nameZh : dna.name;
  const titleId = `dna-preview-title-${dna.id}`;
  return <GalleryDialog titleId={titleId} closeLabel={t('gallery.modalClose')} onClose={onClose}>
    <div className="p-6 sm:p-8">
      <p className="mb-3 text-xs text-indigo-600 dark:text-indigo-300">{t(`gallery.dnaCategory${dna.category[0].toUpperCase()}${dna.category.slice(1)}`)}</p>
      <h2 id={titleId} className="pr-10 text-lg font-semibold text-slate-900 dark:text-slate-100">{name}</h2>
      <p className="mt-3 text-[13px] leading-6 text-slate-500 dark:text-slate-400">{language === 'zh' ? dna.descriptionZh : dna.description}</p>
      {dna.category === 'style' && <div className="my-6 flex gap-4" aria-label={t('gallery.dnaVariants')}>{dna.variants.map((variant) => <div key={variant.label} className="min-w-0 flex-1"><div className="flex h-8 overflow-hidden rounded-md border border-slate-200/40 dark:border-white/10" aria-hidden="true">{variant.previewColors.map((color) => <span key={color} className="flex-1" style={{ backgroundColor: color }} />)}</div><p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">{language === 'zh' ? variant.labelZh : variant.label}</p></div>)}</div>}
      <div className="mt-6 flex flex-col gap-4 border-t border-slate-200/70 pt-5 dark:border-white/[0.07] sm:flex-row sm:items-center sm:justify-between">
        <p className="max-w-xs text-xs leading-5 text-slate-500 dark:text-slate-400">{t('gallery.preferenceNote')}</p>
        <button type="button" onClick={onInject} className="studio-primary shrink-0"><Plus size={15} />{t('gallery.injectDna')}</button>
      </div>
    </div>
  </GalleryDialog>;
};
