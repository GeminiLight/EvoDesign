import { useId } from 'react';
import { useLanguage } from '../../i18n/LanguageProvider';
import type { CanvasLibrary } from '../../types/api';

export type CanvasMode = CanvasLibrary;

type CanvasModeSelectorProps = {
  canvasMode: CanvasMode;
  onChange: (mode: CanvasMode) => void;
  getModeUnavailableReason?: (mode: CanvasMode) => string | null;
};

export const CanvasModeSelector = ({ canvasMode, onChange, getModeUnavailableReason }: CanvasModeSelectorProps) => {
  const { t } = useLanguage();
  const id = useId();
  const modes: CanvasMode[] = ['excalidraw', 'tldraw'];
  const unavailableReason = modes.map(mode => getModeUnavailableReason?.(mode)).find(Boolean);
  return (
    <fieldset aria-describedby={`${id}-hint`}>
      <legend className="text-sm font-medium text-slate-800 dark:text-slate-100">{t('settings.canvasEngine')}</legend>
      <p id={`${id}-hint`} className="mb-3 mt-1.5 text-xs leading-5 text-slate-500 dark:text-slate-400">{t('settings.canvasEngineHint')}</p>
      <div className="grid grid-cols-2 gap-2">
        {modes.map(mode => (
          <label key={mode} className={`flex min-h-12 items-center gap-2.5 rounded-xl border px-3 text-sm transition-colors ${canvasMode === mode
            ? 'border-indigo-300 bg-indigo-50/70 text-indigo-800 dark:border-indigo-500/60 dark:bg-indigo-500/10 dark:text-indigo-200'
            : 'border-slate-200 text-slate-600 dark:border-slate-700 dark:text-slate-400'}`}>
            <input type="radio" name={id} value={mode} checked={canvasMode === mode}
              disabled={Boolean(getModeUnavailableReason?.(mode))}
              onChange={() => onChange(mode)} aria-describedby={unavailableReason ? `${id}-locked` : undefined}
              className="h-4 w-4 border-slate-300 text-indigo-600 focus:ring-indigo-500 disabled:cursor-not-allowed disabled:opacity-50" />
            {t(`canvas.${mode}`)}
          </label>
        ))}
      </div>
      {unavailableReason && <p id={`${id}-locked`} className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">{unavailableReason}</p>}
    </fieldset>
  );
};
