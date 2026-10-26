import { Copy, Eye } from 'lucide-react';
import type { GalleryWork } from '../../data/galleryMockData';

interface WorkCardProps {
  work: GalleryWork;
  t: (key: string) => string;
  language: string;
  onClick: () => void;
  onClone?: () => void;
}

const SIZE_H: Record<string, string> = {
  sm: 'h-40',
  md: 'h-56',
  lg: 'h-72',
};

export const WorkCard = ({ work, t, language, onClick, onClone }: WorkCardProps) => {
  const title = language === 'zh' ? work.titleZh : work.title;
  const previewLabel = t('gallery.previewWorkLabel').replace('{title}', title);
  const cloneLabel = t('gallery.cloneWorkLabel').replace('{title}', title);
  // Use the primary node color for the subtle glow border on hover
  const glowColor = work.thumbnail.nodes[0]?.color ?? '#318dff';

  return (
    <article
      className="gallery-card-break group relative overflow-hidden rounded-2xl border border-slate-200/60 bg-white transition-all hover:shadow-lg dark:border-slate-700/80 dark:bg-slate-900/75 dark:hover:shadow-[0_14px_28px_rgba(2,6,23,0.5)]"
      style={{
        // 1px glow border on hover via box-shadow (avoids layout shift)
        boxShadow: undefined,
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.boxShadow = `0 0 0 1px ${glowColor}33, 0 8px 25px ${glowColor}15`;
        e.currentTarget.style.borderColor = `${glowColor}55`;
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = '';
        e.currentTarget.style.borderColor = '';
      }}
    >
      {/* SVG Thumbnail */}
      <div
        className={`relative ${SIZE_H[work.thumbnailSize]} flex items-center justify-center overflow-hidden bg-slate-50/80 dark:bg-slate-900/60`}
      >
        <svg
          className="h-full w-full px-3 py-3"
          viewBox={work.thumbnail.viewBox}
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          {/* Edges */}
          {work.thumbnail.edges.map((edge, i) => (
            <path
              key={`e-${i}`}
              d={edge.d}
              stroke={edge.color}
              strokeWidth="2"
              strokeLinecap="round"
              className="opacity-60 group-hover:gallery-timelapse-edge"
              style={{ animationDelay: `${edge.delay * 0.15}s` }}
            />
          ))}
          {/* Nodes with text labels */}
          {work.thumbnail.nodes.map((node, i) => (
            <g key={`n-${i}`}>
              <rect
                x={node.x}
                y={node.y}
                width={node.w}
                height={node.h}
                rx={node.rx}
                fill={node.color}
                className="opacity-70 group-hover:gallery-timelapse-node"
                style={{ animationDelay: `${node.delay * 0.2}s` }}
              />
              {node.label && (
                <text
                  x={node.x + node.w / 2}
                  y={node.y + node.h / 2 + 3}
                  fontSize="7"
                  fontWeight="600"
                  fill="#fff"
                  textAnchor="middle"
                  className="pointer-events-none select-none opacity-90"
                >
                  {node.label}
                </text>
              )}
            </g>
          ))}
        </svg>

        {/* Agent badge */}
        <span className="absolute right-2 top-2 rounded-full bg-brand-700 px-2 py-0.5 text-[10px] font-semibold text-white">
          {t('gallery.agentBadge').replace('{version}', work.agentVersion)}
        </span>
      </div>

      {/* Card info */}
      <div className="p-4">
        <h3 className="mb-1.5 truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
          {title}
        </h3>

        <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
          <div className="flex items-center gap-1">
            <div className={`h-4 w-4 rounded-full ${work.avatarColor} flex items-center justify-center text-[8px] font-bold text-white`}>
              E
            </div>
            <span className="max-w-[80px] truncate">EvoDesign</span>
          </div>
          <span className="text-slate-300 dark:text-slate-600">·</span>
          <span className="capitalize">{work.diagramType}</span>
        </div>



        <div className="mt-3 grid grid-cols-2 gap-2">
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
            {t('gallery.previewWork')}
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onClone?.();
            }}
            aria-label={cloneLabel}
            className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl bg-brand-600 px-3 text-xs font-semibold text-white transition hover:bg-brand-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-950"
          >
            <Copy className="h-3.5 w-3.5" />
            {t('gallery.cloneWork')}
          </button>
        </div>
      </div>
    </article>
  );
};
