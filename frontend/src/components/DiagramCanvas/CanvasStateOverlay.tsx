import { AlertTriangle, FileWarning, Loader2, PanelsTopLeft } from 'lucide-react';
import { useLanguage } from '../../i18n/LanguageProvider';
import type { CanvasMode } from './CanvasModeSelector';

export type CanvasStateOverlayKind =
  | 'generating'
  | 'local-edit'
  | 'save-recovery'
  | 'history-switch'
  | 'empty'
  | 'invalid'
  | 'mismatch'
  | 'missing'
  | 'render-error';

type CanvasStateOverlayProps = {
  kind: CanvasStateOverlayKind;
  canvasMode: CanvasMode;
  actualCanvasMode?: CanvasMode | null;
  nodeCount?: number;
  progressMessage?: string | null;
  errorMessage?: string | null;
};

const getCanvasLabel = (mode: CanvasMode, t: (path: string) => string) => (
  mode === 'tldraw' ? t('canvas.tldraw') : t('canvas.excalidraw')
);

export function CanvasStateOverlay({
  kind,
  canvasMode,
  actualCanvasMode,
  nodeCount = 0,
  progressMessage,
  errorMessage,
}: CanvasStateOverlayProps) {
  const { t } = useLanguage();
  const expectedLabel = getCanvasLabel(canvasMode, t);
  const actualLabel = actualCanvasMode ? getCanvasLabel(actualCanvasMode, t) : t('workspace.canvasStateUnknownMode');
  const blocksCanvasInteraction = kind === 'generating' || kind === 'local-edit' || kind === 'save-recovery' || kind === 'history-switch';

  const copy = {
    generating: {
      title: t('workspace.canvasGeneratingTitle'),
      hint: progressMessage || t('workspace.canvasGeneratingHint'),
      Icon: Loader2,
      tone: 'border-brand-200 bg-brand-50/88 text-brand-900 dark:border-brand-500/35 dark:bg-brand-500/12 dark:text-brand-100',
      iconTone: 'text-brand-500 dark:text-brand-300',
      spin: true,
    },
    'local-edit': {
      title: t('workspace.canvasLocalEditTitle'),
      hint: t('workspace.canvasLocalEditHint'),
      Icon: Loader2,
      tone: 'border-brand-200 bg-brand-50/88 text-brand-900 dark:border-brand-500/35 dark:bg-brand-500/12 dark:text-brand-100',
      iconTone: 'text-brand-500 dark:text-brand-300',
      spin: true,
    },
    'save-recovery': {
      title: t('workspace.canvasSaveRecoveryTitle'),
      hint: t('workspace.canvasSaveRecoveryHint'),
      Icon: Loader2,
      tone: 'border-emerald-200 bg-emerald-50/90 text-emerald-950 dark:border-emerald-500/35 dark:bg-emerald-500/12 dark:text-emerald-100',
      iconTone: 'text-emerald-600 dark:text-emerald-300',
      spin: true,
    },
    'history-switch': {
      title: t('workspace.canvasHistorySwitchTitle'),
      hint: t('workspace.canvasHistorySwitchHint'),
      Icon: Loader2,
      tone: 'border-amber-200 bg-amber-50/90 text-amber-950 dark:border-amber-500/35 dark:bg-amber-500/12 dark:text-amber-100',
      iconTone: 'text-amber-600 dark:text-amber-300',
      spin: true,
    },
    empty: {
      title: t('workspace.canvasEmptyResultTitle'),
      hint: t('workspace.canvasEmptyResultHint'),
      Icon: PanelsTopLeft,
      tone: 'border-amber-200 bg-amber-50/90 text-amber-950 dark:border-amber-500/35 dark:bg-amber-500/12 dark:text-amber-100',
      iconTone: 'text-amber-600 dark:text-amber-300',
      spin: false,
    },
    invalid: {
      title: t('workspace.canvasInvalidPayloadTitle'),
      hint: t('workspace.canvasInvalidPayloadHint'),
      Icon: FileWarning,
      tone: 'border-red-200 bg-red-50/90 text-red-950 dark:border-red-500/35 dark:bg-red-500/12 dark:text-red-100',
      iconTone: 'text-red-600 dark:text-red-300',
      spin: false,
    },
    mismatch: {
      title: t('workspace.canvasMismatchTitle'),
      hint: t('workspace.canvasMismatchHint')
        .replace('{expected}', expectedLabel)
        .replace('{actual}', actualLabel),
      Icon: AlertTriangle,
      tone: 'border-amber-200 bg-amber-50/90 text-amber-950 dark:border-amber-500/35 dark:bg-amber-500/12 dark:text-amber-100',
      iconTone: 'text-amber-600 dark:text-amber-300',
      spin: false,
    },
    missing: {
      title: t('workspace.canvasMissingPayloadTitle'),
      hint: t('workspace.canvasMissingPayloadHint'),
      Icon: FileWarning,
      tone: 'border-red-200 bg-red-50/90 text-red-950 dark:border-red-500/35 dark:bg-red-500/12 dark:text-red-100',
      iconTone: 'text-red-600 dark:text-red-300',
      spin: false,
    },
    'render-error': {
      title: t('workspace.canvasRenderErrorTitle'),
      hint: errorMessage || t('workspace.canvasRenderErrorHint'),
      Icon: AlertTriangle,
      tone: 'border-red-200 bg-red-50/90 text-red-950 dark:border-red-500/35 dark:bg-red-500/12 dark:text-red-100',
      iconTone: 'text-red-600 dark:text-red-300',
      spin: false,
    },
  }[kind];

  const Icon = copy.Icon;

  // The stage bar already owns generation progress. Keep the canvas visible
  // while blocking edits, instead of covering it with a second progress card.
  if (blocksCanvasInteraction) {
    return <div className="pointer-events-auto absolute inset-0 z-20 flex items-end justify-center bg-white/10 px-4 pb-16 dark:bg-slate-950/10"
      aria-busy="true" data-canvas-blocking-overlay={kind}>
      {kind === 'generating' ? <p role="status" className="sr-only">{copy.title}: {copy.hint}</p>
        : <p role="status" className="flex max-w-full items-center gap-2 rounded-full border border-slate-200 bg-white/95 px-4 py-2 text-xs text-slate-600 shadow-sm dark:border-white/10 dark:bg-slate-900/95 dark:text-slate-300">
          <Loader2 size={14} className="shrink-0 animate-spin text-indigo-500" aria-hidden="true" />{copy.title}
        </p>}
    </div>;
  }

  return (
    <div
      className={`${blocksCanvasInteraction ? 'pointer-events-auto' : 'pointer-events-none'} absolute inset-0 z-20 flex items-center justify-center bg-white/55 px-4 backdrop-blur-[2px] dark:bg-slate-950/50`}
      aria-busy={blocksCanvasInteraction}
      data-canvas-blocking-overlay={blocksCanvasInteraction ? kind : undefined}
    >
      <div
        className={`pointer-events-auto w-full max-w-md rounded-2xl border p-4 shadow-[0_24px_70px_rgba(15,23,42,0.16)] backdrop-blur-xl ${copy.tone}`}
        role={blocksCanvasInteraction ? 'status' : 'alert'}
        aria-live={blocksCanvasInteraction ? 'polite' : 'assertive'}
      >
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/75 shadow-sm dark:bg-slate-950/35">
            <Icon className={`h-5 w-5 ${copy.iconTone} ${copy.spin ? 'animate-spin' : ''}`} />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold leading-6">{copy.title}</h2>
            <p className="mt-1 text-xs leading-relaxed opacity-85">{copy.hint}</p>
            {!blocksCanvasInteraction && (
              <div className="mt-3 flex flex-wrap gap-1.5 text-[11px] font-semibold">
                <span className="rounded-lg border border-current/15 bg-white/55 px-2 py-1 dark:bg-slate-950/25">
                  {expectedLabel}
                </span>
                <span className="rounded-lg border border-current/15 bg-white/55 px-2 py-1 dark:bg-slate-950/25">
                  {t('workspace.canvasStateNodeCount').replace('{count}', String(nodeCount))}
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
