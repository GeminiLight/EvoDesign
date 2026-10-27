import { ArrowUpRight, Layers, Palette, Workflow } from 'lucide-react';
import type { GalleryDna } from '../../data/galleryMockData';

interface DnaCardProps {
  dna: GalleryDna;
  t: (key: string) => string;
  language: string;
  onClick: () => void;
}

export const DnaCard = ({ dna, t, language, onClick }: DnaCardProps) => {
  const name = language === 'zh' ? dna.nameZh : dna.name;
  const description = language === 'zh' ? dna.descriptionZh : dna.description;
  const Icon = dna.category === 'style' ? Palette : dna.category === 'layout' ? Workflow : Layers;
  return <article className="border-b border-slate-200/70 py-5 dark:border-white/[0.07]">
    <button type="button" onClick={onClick} aria-label={t('gallery.previewDnaLabel').replace('{name}', name)} className="group flex w-full items-start gap-4 rounded-lg text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-indigo-400">
      <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-500 dark:bg-indigo-400/10 dark:text-indigo-300"><Icon size={17} /></span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center justify-between gap-2"><span className="text-[13px] font-semibold text-slate-800 group-hover:text-indigo-600 dark:text-slate-100 dark:group-hover:text-indigo-300">{name}</span><ArrowUpRight size={14} className="shrink-0 text-slate-400" /></span>
        <span className="mt-1.5 block text-xs leading-5 text-slate-500 dark:text-slate-400">{description}</span>
        <span className="mt-3 flex items-center gap-2 text-[11px] text-slate-400"><span className="flex -space-x-0.5" aria-hidden="true">{dna.variants[0]?.previewColors.map((color) => <span key={color} className="h-2.5 w-2.5 rounded-full border border-slate-200/40" style={{ backgroundColor: color }} />)}</span>{t(`gallery.dnaCategory${dna.category[0].toUpperCase()}${dna.category.slice(1)}`)}</span>
      </span>
    </button>
  </article>;
};
