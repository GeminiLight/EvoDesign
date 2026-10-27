import { ArrowUpRight } from 'lucide-react';
import type { GalleryWork } from '../../data/galleryMockData';
import { DiagramPreview } from './DiagramPreview';

interface WorkCardProps {
  work: GalleryWork;
  t: (key: string) => string;
  language: string;
  onClick: () => void;
  onClone?: () => void;
}

export const WorkCard = ({ work, t, language, onClick, onClone }: WorkCardProps) => {
  const title = language === 'zh' ? work.titleZh : work.title;
  return <article className="inspiration-card group">
    <button type="button" onClick={onClick} aria-label={t('gallery.previewWorkLabel').replace('{title}', title)} className="inspiration-preview-button">
      <span className="inspiration-preview"><DiagramPreview work={work} /></span>
      <span className="inspiration-preview-cue"><ArrowUpRight size={15} /></span>
    </button>
    <div className="px-1 pb-1 pt-4">
      <h3 className="text-[13px] font-semibold leading-5 text-slate-800 dark:text-slate-100"><button type="button" onClick={onClick} className="rounded-sm text-left transition-colors hover:text-indigo-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400 dark:hover:text-indigo-300">{title}</button></h3>
      <div className="mt-1 flex items-center justify-between gap-2">
        <p className="text-[11px] text-slate-500 dark:text-slate-400">{t(`gallery.diagram_${work.diagramType}`)}<span className="mx-2 text-slate-300 dark:text-slate-600">/</span>{t(`gallery.complexity${work.complexity[0].toUpperCase()}${work.complexity.slice(1)}`)}</p>
        <button type="button" onClick={onClone} aria-label={t('gallery.cloneWorkLabel').replace('{title}', title)} className="inspiration-use">{t('gallery.cloneWork')}<ArrowUpRight size={13} /></button>
      </div>
    </div>
  </article>;
};
