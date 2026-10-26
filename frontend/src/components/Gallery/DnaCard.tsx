import { Eye, Syringe } from 'lucide-react';
import type { GalleryDna } from '../../data/galleryMockData';

interface DnaCardProps {
  dna: GalleryDna;
  t: (key: string) => string;
  language: string;
  onClick: () => void;
  onInject?: () => void;
}

const CATEGORY_COLORS: Record<string, string> = {
  structure: 'bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300',
  style: 'bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300',
  layout: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300',
};

const CATEGORY_I18N: Record<string, string> = {
  structure: 'gallery.dnaCategoryStructure',
  style: 'gallery.dnaCategoryStyle',
  layout: 'gallery.dnaCategoryLayout',
};

export const DnaCard = ({ dna, t, language, onClick, onInject }: DnaCardProps) => {
  const name = language === 'zh' ? dna.nameZh : dna.name;
  const desc = language === 'zh' ? dna.descriptionZh : dna.description;
  const tags = language === 'zh' ? dna.tagsZh : dna.tags;
  const previewLabel = t('gallery.previewDnaLabel').replace('{name}', name);
  const injectLabel = t('gallery.injectDnaLabel').replace('{name}', name);
  const glowColor = dna.variants[0]?.previewColors[0] ?? '#318dff';

  return (
    <article
      className="group relative overflow-hidden rounded-2xl border border-slate-200/60 bg-white p-5 transition-all hover:shadow-lg dark:border-slate-700/80 dark:bg-slate-900/75 dark:hover:shadow-[0_14px_28px_rgba(2,6,23,0.5)]"
      onMouseEnter={(e) => {
        e.currentTarget.style.boxShadow = `0 0 0 1px ${glowColor}33, 0 8px 25px ${glowColor}15`;
        e.currentTarget.style.borderColor = `${glowColor}55`;
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = '';
        e.currentTarget.style.borderColor = '';
      }}
    >
      {/* 3-variant color preview */}
      <div className="mb-4 flex gap-2">
        {dna.variants.map((v, i) => (
          <div key={i} className="flex flex-1 flex-col items-center gap-1.5">
            <div className="flex h-10 w-full gap-0.5 overflow-hidden rounded-lg">
              {v.previewColors.map((color, ci) => (
                <div key={ci} className="flex-1" style={{ backgroundColor: color }} />
              ))}
            </div>
            <span className="text-[10px] text-slate-400 dark:text-slate-400">
              {language === 'zh' ? v.labelZh : v.label}
            </span>
          </div>
        ))}
      </div>

      {/* Category badge + name */}
      <div className="mb-2 flex items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${CATEGORY_COLORS[dna.category]}`}>
          {t(CATEGORY_I18N[dna.category])}
        </span>
        <h3 className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">{name}</h3>
      </div>

      {/* Description */}
      <p className="mb-3 line-clamp-2 text-xs text-slate-500 dark:text-slate-400">{desc}</p>

      {/* Tags */}
      <div className="mb-3 flex flex-wrap gap-1">
        {tags.map((tag) => (
          <span
            key={tag}
            className="rounded-full border border-slate-200 px-2.5 py-1 text-[10px] text-slate-500 dark:border-slate-600 dark:text-slate-300"
          >
            {tag}
          </span>
        ))}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
          <div className={`h-4 w-4 rounded-full ${dna.avatarColor} flex items-center justify-center text-[8px] font-bold text-white`}>
            E
          </div>
          <span>EvoDesign</span>
          <span className="text-slate-300 dark:text-slate-600">·</span>

        </div>

      </div>

      <div className="mt-4 grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onClick();
          }}
          aria-label={previewLabel}
          className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 transition hover:border-brand-300 hover:text-brand-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300 dark:focus-visible:ring-offset-slate-950"
        >
          <Eye className="h-3.5 w-3.5" />
          {t('gallery.previewDna')}
        </button>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onInject?.();
          }}
          aria-label={injectLabel}
          className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl bg-brand-600 px-3 text-xs font-semibold text-white transition hover:bg-brand-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-950"
        >
          <Syringe className="h-3.5 w-3.5" />
          {t('gallery.injectDna')}
        </button>
      </div>
    </article>
  );
};
