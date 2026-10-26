import { useEffect, useRef } from 'react';
import { X, Syringe, User, Tag, Layers } from 'lucide-react';
import type { GalleryDna } from '../../data/galleryMockData';

interface DnaPreviewModalProps {
  dna: GalleryDna;
  t: (key: string) => string;
  language: string;
  onClose: () => void;
  onInject?: () => void;
}

const CATEGORY_I18N: Record<string, string> = {
  structure: 'gallery.dnaCategoryStructure',
  style: 'gallery.dnaCategoryStyle',
  layout: 'gallery.dnaCategoryLayout',
};

export const DnaPreviewModal = ({ dna, t, language, onClose, onInject }: DnaPreviewModalProps) => {
  const name = language === 'zh' ? dna.nameZh : dna.name;
  const description = language === 'zh' ? dna.descriptionZh : dna.description;
  const tags = language === 'zh' ? dna.tagsZh : dna.tags;
  const titleId = `dna-preview-title-${dna.id}`;
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
        className="gallery-modal-enter relative max-h-[calc(100dvh-1rem)] w-full max-w-lg overflow-y-auto rounded-2xl bg-white/90 shadow-2xl ring-1 ring-black/5 backdrop-blur-xl dark:bg-slate-950/92 dark:ring-white/10"
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

        <div className="p-4 sm:p-6">
          <h2 id={titleId} className="mb-1 pr-8 text-lg font-bold text-slate-900 dark:text-slate-100">{name}</h2>
          <p className="mb-5 text-sm text-slate-500 dark:text-slate-400">{description}</p>

          {/* Variant previews */}
          <div className="mb-5">
            <h4 className="mb-2 text-xs font-semibold text-slate-700 dark:text-slate-200">{t('gallery.dnaVariants')}</h4>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {dna.variants.map((v, i) => (
                <div key={i} className="text-center">
                  <div className="flex h-16 w-full gap-0.5 overflow-hidden rounded-xl border border-slate-200 dark:border-slate-700">
                    {v.previewColors.map((color, ci) => (
                      <div key={ci} className="flex-1" style={{ backgroundColor: color }} />
                    ))}
                  </div>
                  <span className="mt-1 block text-[11px] text-slate-500 dark:text-slate-400">
                    {language === 'zh' ? v.labelZh : v.label}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Meta info */}
          <div className="mb-5 grid grid-cols-2 gap-3 text-xs">
            <div className="flex items-start gap-2 rounded-lg bg-slate-50 p-2.5 dark:bg-slate-800/60">
              <User className="mt-0.5 h-3.5 w-3.5 text-slate-500 dark:text-slate-400" />
              <div>
                <div className="text-[10px] text-slate-500 dark:text-slate-400">{t('gallery.modalAuthor')}</div>
                <div className="font-medium text-slate-700 dark:text-slate-200">{dna.author}</div>
              </div>
            </div>
            <div className="flex items-start gap-2 rounded-lg bg-slate-50 p-2.5 dark:bg-slate-800/60">
              <Layers className="mt-0.5 h-3.5 w-3.5 text-slate-500 dark:text-slate-400" />
              <div>
                <div className="text-[10px] text-slate-500 dark:text-slate-400">{t('gallery.dnaCategory')}</div>
                <div className="capitalize font-medium text-slate-700 dark:text-slate-200">{t(CATEGORY_I18N[dna.category])}</div>
              </div>
            </div>
            <div className="flex items-start gap-2 rounded-lg bg-slate-50 p-2.5 dark:bg-slate-800/60">
              <Syringe className="mt-0.5 h-3.5 w-3.5 text-slate-500 dark:text-slate-400" />
              <div>
                <div className="text-[10px] text-slate-500 dark:text-slate-400">{t('gallery.modalClones')}</div>
                <div className="font-medium text-slate-700 dark:text-slate-200">{dna.injectCount.toLocaleString()}</div>
              </div>
            </div>
            <div className="flex items-start gap-2 rounded-lg bg-slate-50 p-2.5 dark:bg-slate-800/60">
              <Tag className="mt-0.5 h-3.5 w-3.5 text-slate-500 dark:text-slate-400" />
              <div>
                <div className="text-[10px] text-slate-500 dark:text-slate-400">{t('gallery.modalTags')}</div>
                <div className="font-medium text-slate-700 dark:text-slate-200">{tags.join(', ')}</div>
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="flex flex-col gap-3 sm:flex-row">
            <button type="button" onClick={onInject} className="btn-primary min-h-11 flex-1 gap-1.5 text-sm">
              <Syringe className="h-3.5 w-3.5" />
              {t('gallery.injectDna')}
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
