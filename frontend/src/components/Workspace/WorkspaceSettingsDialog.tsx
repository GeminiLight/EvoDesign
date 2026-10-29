import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';
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
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!open || !dialog) return;
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
            <h2 id="workspace-settings-title" className="text-lg font-semibold text-slate-900 dark:text-slate-100">{t('settings.canvasOptions')}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label={t('workspace.close')}
            className="studio-icon-button"><X size={17} /></button>
        </div>
        <CanvasModeSelector canvasMode={canvasMode} onChange={onCanvasChange} getModeUnavailableReason={getModeUnavailableReason} />
      </div>
    </dialog>
  );
}
