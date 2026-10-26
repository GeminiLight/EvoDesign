import { useEffect, useRef } from 'react';
import { ChevronDown, SlidersHorizontal, X } from 'lucide-react';
import { useLanguage } from '../../i18n/LanguageProvider';
import { CanvasModeSelector, type CanvasMode } from '../DiagramCanvas/CanvasModeSelector';

type Props = {
  open: boolean;
  onClose: () => void;
  canvasMode: CanvasMode;
  onCanvasChange: (mode: CanvasMode) => void;
  getModeUnavailableReason: (mode: CanvasMode) => string | null;
};

export function WorkspaceSettingsDialog({ open, onClose, canvasMode, onCanvasChange, getModeUnavailableReason }: Props) {
  const { t } = useLanguage();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const advancedRef = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!open || !dialog) return;
    if (advancedRef.current) advancedRef.current.open = false;
    dialog.showModal();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      dialog.close();
      document.body.style.overflow = overflow;
    };
  }, [open]);

  return (
    <dialog ref={dialogRef} className="workspace-settings-dialog" aria-labelledby="workspace-settings-title"
      onCancel={onClose} onClose={() => { if (open) onClose(); }}
      onKeyDown={event => event.stopPropagation()} onKeyUp={event => event.stopPropagation()}
      onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="p-6 sm:p-7">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h2 id="workspace-settings-title" className="text-lg font-semibold text-slate-900 dark:text-slate-100">{t('settings.workspaceTitle')}</h2>
            <p className="mt-1.5 text-sm leading-6 text-slate-500 dark:text-slate-400">{t('settings.workspaceHint')}</p>
          </div>
          <button type="button" onClick={onClose} aria-label={t('workspace.close')}
            className="tool-button h-9 w-9 shrink-0 border-0 px-0"><X size={17} /></button>
        </div>
        <details ref={advancedRef} className="group rounded-xl border border-slate-200 dark:border-slate-700">
          <summary className="flex min-h-14 cursor-pointer list-none items-center gap-3 rounded-xl px-4 text-sm font-medium text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 dark:text-slate-200 [&::-webkit-details-marker]:hidden">
            <SlidersHorizontal size={17} className="text-slate-400" />{t('settings.advanced')}
            <ChevronDown size={15} className="ml-auto text-slate-400 transition-transform group-open:rotate-180" />
          </summary>
          <div className="border-t border-slate-100 p-4 dark:border-slate-800">
            <CanvasModeSelector canvasMode={canvasMode} onChange={onCanvasChange} getModeUnavailableReason={getModeUnavailableReason} />
          </div>
        </details>
      </div>
    </dialog>
  );
}
