import { useEffect, useRef } from 'react';
import { Loader2, X } from 'lucide-react';
import { DiagramPromptComposer, type PromptOption, type PromptPill } from '../DiagramPromptComposer';
import { StageProgress } from '../StageProgress';
import type { GenerationProgress } from '../../types/app';
import { useLanguage } from '../../i18n/LanguageProvider';

export type CreateDiagramDialogHandoffRule = {
  cabinLabel: string;
  title: string;
  preview: string;
};

export type CreateDiagramDialogHandoff = {
  title: string;
  description: string;
  sourceLabel?: string;
  sourceValue?: string;
  rulesLabel?: string;
  emptyRulesLabel?: string;
  rules?: CreateDiagramDialogHandoffRule[];
  moreRulesLabel?: string;
  badges?: string[];
};

export interface CreateDiagramDialogProps {
  useIcons: boolean;
  onUseIconsChange: (value: boolean) => void;
  open: boolean;
  onClose: () => void;
  prompt: string;
  onPromptChange: (value: string) => void;
  onGenerate: () => void;
  onCancelGeneration?: () => void;
  onEnhance: () => void;
  onSelectPill: (pill: PromptPill) => void;
  selectedPillId: string;
  pills: PromptPill[];
  morePills: PromptPill[];
  modelOptions: PromptOption[];
  modelIndex: number;
  onModelChange: (index: number) => void;
  canvasOptions: PromptOption[];
  canvasIndex: number;
  onCanvasChange: (index: number) => void;
  isGenerating: boolean;
  isWorkspaceLocked?: boolean;
  workspaceLockedReason?: string;
  progress: GenerationProgress | null;
  handoff?: CreateDiagramDialogHandoff | null;
}

export function CreateDiagramDialog({
  useIcons,
  onUseIconsChange,
  open,
  onClose,
  prompt,
  onPromptChange,
  onGenerate,
  onCancelGeneration,
  onEnhance,
  onSelectPill,
  selectedPillId,
  pills,
  morePills,
  modelOptions,
  modelIndex,
  onModelChange,
  canvasOptions,
  canvasIndex,
  onCanvasChange,
  isGenerating,
  isWorkspaceLocked = false,
  workspaceLockedReason,
  progress,
  handoff,
}: CreateDiagramDialogProps) {
  const { t } = useLanguage();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const lastFocusedElementRef = useRef<HTMLElement | null>(null);
  const isDialogLocked = isGenerating || isWorkspaceLocked;
  const lockedReason = workspaceLockedReason || t('workspace.createDialogLockedHint');
  const promptIsEmpty = !prompt.trim();
  const promptRequiredHint = t('workspace.createDialogPromptRequired');
  const generateDisabledReason = isDialogLocked
    ? lockedReason
    : promptIsEmpty
      ? promptRequiredHint
      : undefined;
  const showPromptRequiredHint = Boolean(handoff) && promptIsEmpty && !isDialogLocked;

  useEffect(() => {
    if (!open) return;

    lastFocusedElementRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;

    const previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.body.style.overflow = previousBodyOverflow;
      lastFocusedElementRef.current?.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open || !handoff) return;

    const focusTimer = window.setTimeout(() => {
      dialogRef.current?.focus({ preventScroll: true });
    }, 0);

    return () => {
      window.clearTimeout(focusTimer);
    };
  }, [handoff, open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 px-4 py-4 backdrop-blur-sm sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="workspace-create-dialog-title"
      onClick={(e) => {
        if (e.target === e.currentTarget && !isDialogLocked) {
          onClose();
        }
      }}
      onKeyDown={(e) => {
        if (e.defaultPrevented || e.nativeEvent.isComposing || e.keyCode === 229) return;
        if (e.key === 'Escape' && !isDialogLocked) {
          onClose();
        }

        if (e.key !== 'Tab') return;
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

        if (e.shiftKey && active === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }}
    >
      <div ref={dialogRef} tabIndex={-1} className="flex max-h-[calc(100dvh-2rem)] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white p-3 shadow-2xl outline-none dark:border-slate-700 dark:bg-slate-900">
        <div className="mb-2 flex shrink-0 items-center justify-between px-1">
          <p id="workspace-create-dialog-title" className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            {t('workspace.createDiagram')}
          </p>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            disabled={isDialogLocked}
            title={isDialogLocked ? lockedReason : undefined}
            className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-slate-200 text-slate-500 transition hover:border-slate-300 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-400 dark:hover:border-slate-600 dark:hover:text-slate-200 dark:focus-visible:ring-offset-slate-900"
            aria-label={t('workspace.close')}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div data-testid="workspace-create-dialog-scroll" className="min-h-0 flex-1 overflow-y-auto px-0.5 pb-1">
          {handoff && (
            <section
              className="mb-3 rounded-2xl border border-brand-200/75 bg-brand-50/70 px-4 py-3 text-brand-950 shadow-[0_14px_34px_rgba(37,99,235,0.10)] dark:border-brand-500/30 dark:bg-brand-500/10 dark:text-brand-50"
              aria-label={handoff.title}
              data-testid="workspace-preflight-handoff"
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <h2 className="text-sm font-semibold leading-6">{handoff.title}</h2>
                  <p className="mt-1 text-xs leading-relaxed text-brand-900/75 dark:text-brand-100/78">
                    {handoff.description}
                  </p>
                </div>
                {handoff.badges && handoff.badges.length > 0 && (
                  <div className="flex shrink-0 flex-wrap gap-1.5 sm:justify-end">
                    {handoff.badges.map((badge) => (
                      <span
                        key={badge}
                        className="rounded-lg border border-brand-200/70 bg-white/70 px-2 py-1 text-[10px] font-semibold text-brand-800 dark:border-brand-500/25 dark:bg-slate-950/30 dark:text-brand-100"
                      >
                        {badge}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {handoff.sourceLabel && handoff.sourceValue && (
                <div className="mt-3 rounded-xl border border-brand-200/70 bg-white/62 px-3 py-2 dark:border-brand-500/25 dark:bg-slate-950/28">
                  <p className="text-[10px] font-semibold text-brand-700/70 dark:text-brand-200/70">
                    {handoff.sourceLabel}
                  </p>
                  <p className="mt-1 line-clamp-2 text-xs font-semibold leading-relaxed text-brand-950 dark:text-brand-50">
                    {handoff.sourceValue}
                  </p>
                </div>
              )}

              {handoff.rulesLabel && (
                <div className="mt-3">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <p className="text-[10px] font-semibold text-brand-700/70 dark:text-brand-200/70">
                      {handoff.rulesLabel}
                    </p>
                    {handoff.moreRulesLabel && (
                      <span className="text-[10px] font-semibold text-brand-700/70 dark:text-brand-200/70">
                        {handoff.moreRulesLabel}
                      </span>
                    )}
                  </div>
                  {handoff.rules && handoff.rules.length > 0 ? (
                    <div className="grid gap-2 sm:grid-cols-2">
                      {handoff.rules.map((rule) => (
                        <div
                          key={`${rule.cabinLabel}:${rule.title}:${rule.preview}`}
                          className="min-w-0 rounded-xl border border-brand-200/70 bg-white/62 px-3 py-2 dark:border-brand-500/25 dark:bg-slate-950/28"
                        >
                          <div className="flex min-w-0 items-center gap-2">
                            <span className="shrink-0 rounded-md bg-brand-100 px-1.5 py-0.5 text-[9px] font-semibold text-brand-700 dark:bg-brand-500/18 dark:text-brand-100">
                              {rule.cabinLabel}
                            </span>
                            <p className="min-w-0 truncate text-xs font-semibold text-brand-950 dark:text-brand-50">
                              {rule.title}
                            </p>
                          </div>
                          <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-brand-900/70 dark:text-brand-100/72">
                            {rule.preview}
                          </p>
                        </div>
                      ))}
                    </div>
                  ) : handoff.emptyRulesLabel ? (
                    <p className="rounded-xl border border-brand-200/70 bg-white/62 px-3 py-2 text-xs font-medium text-brand-900/75 dark:border-brand-500/25 dark:bg-slate-950/28 dark:text-brand-100/72">
                      {handoff.emptyRulesLabel}
                    </p>
                  ) : null}
                </div>
              )}
            </section>
          )}

          {isWorkspaceLocked && !isGenerating && (
            <div
              className="mb-3 flex items-start gap-2 rounded-2xl border border-amber-200/80 bg-amber-50/80 px-4 py-3 text-amber-900 shadow-[0_14px_34px_rgba(217,119,6,0.10)] dark:border-amber-500/35 dark:bg-amber-500/10 dark:text-amber-100"
              role="status"
              data-testid="workspace-create-dialog-lock-notice"
            >
              <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-amber-600 dark:text-amber-300" />
              <div className="min-w-0">
                <p className="text-sm font-semibold">{t('workspace.createDialogLockedTitle')}</p>
                <p className="mt-1 text-xs leading-relaxed text-amber-800/85 dark:text-amber-100/80">
                  {lockedReason}
                </p>
              </div>
            </div>
          )}

          <DiagramPromptComposer
            variant="dialog"
            prompt={prompt}
            onPromptChange={onPromptChange}
            onGenerate={onGenerate}
            onEnhance={onEnhance}
            onSelectPill={onSelectPill}
            selectedPillId={selectedPillId}
            pills={pills}
            morePills={morePills}
            modelOptions={modelOptions}
            modelIndex={modelIndex}
            onModelChange={onModelChange}
            canvasOptions={canvasOptions}
            canvasIndex={canvasIndex}
            onCanvasChange={onCanvasChange}
            attachTitle={t('home.attachComingSoonTitle')}
            enhanceTitle={t('home.enhancePrompt')}
            generateTitle={isGenerating
              ? (progress?.message || t('workspace.generating'))
              : isDialogLocked
                ? lockedReason
                : promptIsEmpty
                  ? promptRequiredHint
                  : t('home.generateIconTitle')}
            moreLabel={t('home.pillMoreLabel')}
            disableGenerate={isDialogLocked}
            isGenerating={isGenerating}
            isDisabled={isDialogLocked}
            t={t}
            autoFocusPrompt={!handoff}
          />

          <label className="mx-3 mt-3 flex items-center gap-3 rounded-xl border border-slate-200 px-4 py-3 text-sm dark:border-slate-700">
            <input
              type="checkbox"
              checked={useIcons && canvasOptions[canvasIndex]?.id === 'excalidraw'}
              onChange={(event) => onUseIconsChange(event.target.checked)}
              disabled={isDialogLocked || canvasOptions[canvasIndex]?.id !== 'excalidraw'}
              className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 disabled:opacity-40"
            />
            <span>
              <span className="font-medium text-slate-800 dark:text-slate-100">{t('workspace.useIcons')}</span>
              <span className="mt-0.5 block text-xs text-slate-500 dark:text-slate-400">{t(canvasOptions[canvasIndex]?.id === 'excalidraw' ? 'workspace.useIconsHint' : 'workspace.useIconsCanvasHint')}</span>
            </span>
          </label>

          {showPromptRequiredHint && (
            <p
              className="mt-2 px-4 text-xs font-medium leading-relaxed text-slate-600 dark:text-slate-300"
              role="status"
              aria-live="polite"
              data-testid="workspace-create-dialog-prompt-required"
            >
              {promptRequiredHint}
            </p>
          )}

          {isGenerating && progress && (
            <div className="mt-3 px-4 pb-2">
              <StageProgress progress={progress} t={t} />
              {progress.message && (
                <p className="mt-2 text-xs font-medium leading-relaxed text-brand-700 dark:text-brand-200">
                  {progress.message}
                </p>
              )}
            </div>
          )}
        </div>

        <div className="mt-3 flex shrink-0 flex-col gap-2 border-t border-slate-100 px-1 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] pt-3 dark:border-slate-800 sm:flex-row sm:items-center sm:justify-end sm:pb-0">
          <button
            type="button"
            onClick={onGenerate}
            className="inline-flex min-h-11 w-full items-center justify-center rounded-full bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-[0_10px_24px_rgba(37,99,235,0.22)] transition hover:bg-brand-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500 disabled:shadow-none dark:bg-brand-500 dark:hover:bg-brand-400 dark:disabled:bg-slate-700 dark:disabled:text-slate-400 dark:focus-visible:ring-offset-slate-900 sm:w-auto"
            disabled={isDialogLocked || promptIsEmpty}
            title={generateDisabledReason}
          >
            {t('workspace.onboardingGenerate')}
          </button>
          <button
            type="button"
            onClick={isGenerating ? onCancelGeneration : onClose}
            className="min-h-11 w-full rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-600 transition hover:border-slate-300 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-slate-100 dark:focus-visible:ring-offset-slate-900 sm:w-auto"
            disabled={(isGenerating && !onCancelGeneration) || isWorkspaceLocked}
            title={isWorkspaceLocked ? lockedReason : undefined}
          >
            {isGenerating
              ? t('workspace.stopGeneration')
              : isWorkspaceLocked
                ? t('workspace.createDialogLockedAction')
                : t('workspace.cancel')}
          </button>
        </div>
      </div>
    </div>
  );
}
