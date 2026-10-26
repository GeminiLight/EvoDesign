import { useEffect, useRef } from 'react';
import { X, Copy, Eye, Calendar, User, Tag, Layers, BarChart3 } from 'lucide-react';
import type { GalleryWork } from '../../data/galleryMockData';

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
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const lastFocusedElementRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    lastFocusedElementRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const frameId = window.requestAnimationFrame(() => {
      closeButtonRef.current?.focus();
    });

    return () => {
      window.cancelAnimationFrame(frameId);
      document.body.style.overflow = previousBodyOverflow;
      lastFocusedElementRef.current?.focus();
    };
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/50 p-2 backdrop-blur-md sm:items-center sm:p-4"
      onClick={onClose}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          onClose();
          return;
        }

        if (event.key !== 'Tab') return;
        const container = dialogRef.current;
        if (!container) return;

        const focusable = Array.from(
          container.querySelectorAll<HTMLElement>(
            'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
          ),
        ).filter((element) => !element.hasAttribute('hidden'));

        if (focusable.length === 0) return;

        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        const active = document.activeElement;

        if (event.shiftKey && active === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && active === last) {
          event.preventDefault();
          first.focus();
        }
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="gallery-modal-enter relative max-h-[calc(100dvh-1rem)] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white/90 shadow-2xl ring-1 ring-black/5 backdrop-blur-xl dark:bg-slate-950/92 dark:ring-white/10"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close button */}
        <button
          ref={closeButtonRef}
          type="button"
          onClick={onClose}
          aria-label={t('gallery.modalClose')}
          className="absolute right-3 top-3 z-10 flex h-11 w-11 items-center justify-center rounded-xl bg-slate-100 text-slate-500 transition-colors hover:bg-slate-200 hover:text-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700 dark:hover:text-slate-200"
        >
          <X className="h-4 w-4" />
        </button>

        {/* SVG Preview */}
        <div className="flex h-56 items-center justify-center border-b border-slate-200/50 bg-slate-50/80 dark:border-slate-700/50 dark:bg-slate-900/60 sm:h-64">
          <svg
            className="h-full w-full p-6"
            viewBox={work.thumbnail.viewBox}
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            {work.thumbnail.edges.map((edge, i) => (
              <path
                key={`e-${i}`}
                d={edge.d}
                stroke={edge.color}
                strokeWidth="2"
                strokeLinecap="round"
                className="gallery-timelapse-edge"
                style={{ animationDelay: `${edge.delay * 0.15}s` }}
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
                className="gallery-timelapse-node"
                style={{ animationDelay: `${node.delay * 0.2}s` }}
              />
            ))}
          </svg>
        </div>

        {/* Details */}
        <div className="p-4 sm:p-6">
          <h2 id={titleId} className="mb-2 text-lg font-bold text-slate-900 dark:text-slate-100">{title}</h2>
          <p className="mb-5 text-sm text-slate-500 dark:text-slate-400">{description}</p>

          <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-3">
            <InfoItem icon={<User className="h-3.5 w-3.5" />} label={t('gallery.modalAuthor')} value={work.author} />
            <InfoItem icon={<Tag className="h-3.5 w-3.5" />} label={t('gallery.modalType')} value={work.diagramType} />
            <InfoItem icon={<Layers className="h-3.5 w-3.5" />} label={t('gallery.modalIndustry')} value={work.industry} />
            <InfoItem icon={<BarChart3 className="h-3.5 w-3.5" />} label={t('gallery.modalComplexity')} value={work.complexity} />
            <InfoItem icon={<Calendar className="h-3.5 w-3.5" />} label={t('gallery.modalCreated')} value={work.createdAt} />
            <InfoItem icon={<Eye className="h-3.5 w-3.5" />} label={t('gallery.modalViews')} value={work.viewCount.toLocaleString()} />
          </div>

          <div className="mt-5 flex flex-col gap-3 sm:flex-row">
            <button type="button" onClick={onClone} className="btn-primary min-h-11 flex-1 gap-1.5 text-sm">
              <Copy className="h-3.5 w-3.5" />
              {t('gallery.cloneWork')}
            </button>
            <button type="button" onClick={onClose} className="btn-muted min-h-11 text-sm">
              {t('gallery.modalClose')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

const InfoItem = ({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) => (
  <div className="flex items-start gap-2 rounded-lg bg-slate-50 p-2.5 dark:bg-slate-800/60">
    <span className="mt-0.5 text-slate-500 dark:text-slate-400">{icon}</span>
    <div>
      <div className="text-[10px] text-slate-500 dark:text-slate-400">{label}</div>
      <div className="capitalize font-medium text-slate-700 dark:text-slate-200">{value}</div>
    </div>
  </div>
);
