import { ArrowUpRight } from 'lucide-react';
import type { GalleryWork } from '../../data/galleryMockData';
import { DiagramPreview } from './DiagramPreview';
import { GalleryDialog } from './GalleryDialog';

interface WorkPreviewModalProps {
  work: GalleryWork;
  t: (key: string) => string;
  language: string;
  onClose: () => void;
  onClone?: () => void;
}

export const WorkPreviewModal = ({ work, t, language, onClose, onClone }: WorkPreviewModalProps) => {
  const title = language === 'zh' ? work.titleZh : work.title;
  const description = language === 'zh' ? work.descriptionZh : work.description;
  const titleId = `work-preview-title-${work.id}`;
  return <GalleryDialog titleId={titleId} closeLabel={t('gallery.modalClose')} onClose={onClose}>
    <div className="inspiration-preview h-60 px-9 py-7 sm:h-72"><DiagramPreview work={work} /></div>
    <div className="p-5 sm:p-7">
      <p className="mb-2 text-xs text-indigo-600 dark:text-indigo-300">{t(`gallery.diagram_${work.diagramType}`)}<span className="mx-2 text-slate-300 dark:text-slate-600">/</span>{t(`gallery.complexity${work.complexity[0].toUpperCase()}${work.complexity.slice(1)}`)}</p>
      <h2 id={titleId} className="text-lg font-semibold tracking-tight text-slate-900 dark:text-slate-100">{title}</h2>
      <p className="mt-3 text-[13px] leading-6 text-slate-500 dark:text-slate-400">{description}</p>
      <div className="mt-6 flex flex-col gap-4 border-t border-slate-200/70 pt-5 dark:border-white/[0.07] sm:flex-row sm:items-center sm:justify-between">
        <p className="max-w-xs text-xs leading-5 text-slate-500 dark:text-slate-400">{t('gallery.sampleNote')}</p>
        <button type="button" onClick={onClone} className="studio-primary shrink-0">{t('gallery.cloneWork')}<ArrowUpRight size={15} /></button>
      </div>
    </div>
  </GalleryDialog>;
};
