import { TrendingUp, Dna, Eye, Syringe } from 'lucide-react';
import type { GalleryWork, GalleryDna } from '../../data/galleryMockData';

interface HotRankingsProps {
  t: (key: string) => string;
  language: string;
  trendingWorks: GalleryWork[];
  popularDna: GalleryDna[];
  onClickWork: (work: GalleryWork) => void;
  onClickDna: (dna: GalleryDna) => void;
}

/** Micro SVG preview for the #1 ranked work */
const TopWorkPreview = ({ work }: { work: GalleryWork }) => (
  <div className="mb-3 overflow-hidden rounded-lg border border-slate-200/40 bg-slate-50/60 dark:border-slate-600/50 dark:bg-slate-800/50">
    <svg
      className="h-20 w-full"
      viewBox={work.thumbnail.viewBox}
      fill="none"
      preserveAspectRatio="xMidYMid meet"
    >
      {work.thumbnail.edges.map((edge, i) => (
        <path
          key={`e-${i}`}
          d={edge.d}
          stroke={edge.color}
          strokeWidth="1.5"
          strokeLinecap="round"
          opacity="0.4"
        />
      ))}
      {work.thumbnail.nodes.map((node, i) => (
        <rect
          key={`n-${i}`}
          x={node.x}
          y={node.y}
          width={node.w}
          height={node.h}
          rx={node.rx}
          fill={node.color}
          opacity="0.6"
        />
      ))}
    </svg>
  </div>
);

export const HotRankings = ({
  t,
  language,
  trendingWorks,
  popularDna,
  onClickWork,
  onClickDna,
}: HotRankingsProps) => {
  return (
    <aside className="w-full shrink-0 space-y-4 lg:w-60 lg:space-y-5">
      {/* Trending Works */}
      <div className="rounded-2xl border border-white/40 bg-white/60 p-3.5 backdrop-blur-sm dark:border-slate-600/50 dark:bg-slate-900/60">
        <div className="mb-2.5 flex items-center gap-2">
          <TrendingUp className="h-3.5 w-3.5 text-brand-500" />
          <h3 className="text-xs font-semibold text-slate-900 dark:text-slate-100">
            {t('gallery.trendingWorksTitle')}
          </h3>
        </div>

        {/* #1 thumbnail micro-preview */}
        {trendingWorks[0] && (
          <button
            type="button"
            className="hidden w-full rounded-lg text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 lg:block"
            aria-label={t('gallery.previewWorkLabel').replace(
              '{title}',
              language === 'zh' ? trendingWorks[0].titleZh : trendingWorks[0].title,
            )}
            onClick={() => onClickWork(trendingWorks[0])}
          >
            <TopWorkPreview work={trendingWorks[0]} />
          </button>
        )}

        <ul className="custom-scrollbar -mx-1 flex gap-2 overflow-x-auto px-1 pb-1 lg:mx-0 lg:block lg:space-y-1.5 lg:overflow-visible lg:px-0 lg:pb-0">
          {trendingWorks.map((work, index) => {
            const title = language === 'zh' ? work.titleZh : work.title;
            return (
              <li key={work.id} className="min-w-52 lg:min-w-0">
                <button
                  type="button"
                  className="flex min-h-11 w-full items-start gap-2 rounded-xl border border-slate-200/70 bg-white/70 px-3 py-2 text-left transition-colors hover:bg-slate-100/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 dark:border-slate-700/70 dark:bg-slate-900/60 dark:hover:bg-slate-800/60 lg:border-transparent lg:bg-transparent lg:px-2"
                  onClick={() => onClickWork(work)}
                >
                <span className={`flex h-4.5 w-4.5 shrink-0 items-center justify-center rounded text-[9px] font-bold ${
                  index < 3
                    ? 'bg-brand-500/90 text-white'
                    : 'bg-slate-100/80 text-slate-500 dark:bg-slate-800/80 dark:text-slate-400'
                }`}>
                  {index + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[11px] font-medium text-slate-700 dark:text-slate-200">{title}</p>
                  <span className="flex items-center gap-1 text-[9px] text-slate-400 dark:text-slate-400">
                    <Eye className="h-2.5 w-2.5" />
                    {work.viewCount.toLocaleString()}
                  </span>
                </div>
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      {/* Popular DNA */}
      <div className="rounded-2xl border border-white/40 bg-white/60 p-3.5 backdrop-blur-sm dark:border-slate-600/50 dark:bg-slate-900/60">
        <div className="mb-2.5 flex items-center gap-2">
          <Dna className="h-3.5 w-3.5 text-violet-500" />
          <h3 className="text-xs font-semibold text-slate-900 dark:text-slate-100">
            {t('gallery.popularDnaTitle')}
          </h3>
        </div>
        <ul className="custom-scrollbar -mx-1 flex gap-2 overflow-x-auto px-1 pb-1 lg:mx-0 lg:block lg:space-y-1.5 lg:overflow-visible lg:px-0 lg:pb-0">
          {popularDna.map((dna, index) => {
            const name = language === 'zh' ? dna.nameZh : dna.name;
            return (
              <li key={dna.id} className="min-w-52 lg:min-w-0">
                <button
                  type="button"
                  className="flex min-h-11 w-full items-start gap-2 rounded-xl border border-slate-200/70 bg-white/70 px-3 py-2 text-left transition-colors hover:bg-slate-100/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-300 dark:border-slate-700/70 dark:bg-slate-900/60 dark:hover:bg-slate-800/60 lg:border-transparent lg:bg-transparent lg:px-2"
                  onClick={() => onClickDna(dna)}
                >
                <span className={`flex h-4.5 w-4.5 shrink-0 items-center justify-center rounded text-[9px] font-bold ${
                  index < 3
                    ? 'bg-violet-500/90 text-white'
                    : 'bg-slate-100/80 text-slate-500 dark:bg-slate-800/80 dark:text-slate-400'
                }`}>
                  {index + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[11px] font-medium text-slate-700 dark:text-slate-200">{name}</p>
                  <span className="flex items-center gap-1 text-[9px] text-slate-400 dark:text-slate-400">
                    <Syringe className="h-2.5 w-2.5" />
                    {dna.injectCount.toLocaleString()}
                  </span>
                </div>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </aside>
  );
};
