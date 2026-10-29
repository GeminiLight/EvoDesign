import { useEffect, useRef } from 'react';
import { ArrowUpRight, ChevronDown, Loader2, Settings2, Sparkles, X } from 'lucide-react';
import type { PromptOption, PromptPill } from '../DiagramPromptComposer';
import { StageProgress } from '../StageProgress';
import { ChoiceSelect } from '../ChoiceSelect';
import type { GenerationProgress } from '../../types/app';
import { useLanguage } from '../../i18n/LanguageProvider';
import { BROWSER_MODE, openModelSettings } from '../../services/browser/runtime';
import { shouldSubmitOnModifiedEnter } from '../../utils/keyboard';

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
  useIcons, onUseIconsChange, open, onClose, prompt, onPromptChange,
  onGenerate, onCancelGeneration, onEnhance, onSelectPill, selectedPillId,
  pills, morePills, modelOptions, modelIndex, onModelChange,
  canvasOptions, canvasIndex, onCanvasChange, isGenerating,
  isWorkspaceLocked = false, workspaceLockedReason, progress, handoff,
}: CreateDiagramDialogProps) {
  const { t } = useLanguage();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const isDialogLocked = isGenerating || isWorkspaceLocked;
  const lockedReason = workspaceLockedReason || t('workspace.createDialogLockedHint');
  const promptIsEmpty = !prompt.trim();
  const supportsIcons = canvasOptions[canvasIndex]?.id === 'excalidraw';
  const allPills = [...pills, ...morePills];
  const requirementsAdded = prompt.includes(t('home.enhancePromptInstruction'));
  const modelLabel = modelOptions[modelIndex]?.label ?? modelOptions[0]?.label;

  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current!;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.showModal();
    promptRef.current?.focus({ preventScroll: true });
    return () => {
      dialog.close();
      document.body.style.overflow = previousOverflow;
      window.setTimeout(() => { if (trigger?.isConnected) trigger.focus(); }, 0);
    };
  }, [open]);

  if (!open) return null;

  return (
    <dialog ref={dialogRef} className="create-diagram-dialog" aria-labelledby="workspace-create-dialog-title"
      onCancel={(event) => { event.preventDefault(); if (!isDialogLocked) onClose(); }}
      onKeyDown={(event) => event.stopPropagation()} onKeyUp={(event) => event.stopPropagation()}
      onClick={(event) => {
        if (event.target !== event.currentTarget || isDialogLocked) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose();
      }}>
      <form className="flex max-h-[calc(100dvh-2rem)] flex-col" onSubmit={(event) => { event.preventDefault(); if (!isDialogLocked && !promptIsEmpty) onGenerate(); }}>
        <header className="flex shrink-0 items-start justify-between gap-4 px-5 pb-4 pt-5 sm:px-7 sm:pt-6">
          <div className="min-w-0">
            <h2 id="workspace-create-dialog-title" className="text-lg font-semibold tracking-tight text-slate-900 dark:text-slate-100">{handoff?.title ?? t('workspace.createDiagram')}</h2>
            {handoff?.sourceValue ? <p className="mt-1.5 break-words text-xs leading-5 text-slate-500 dark:text-slate-400" data-testid="workspace-preflight-handoff">{handoff.sourceLabel}<span className="mx-1.5 text-slate-300 dark:text-slate-600">/</span>{handoff.sourceValue}</p>
              : <p className="mt-1.5 text-xs leading-5 text-slate-500 dark:text-slate-400">{t('workspace.createDialogIntro')}</p>}
          </div>
          <button type="button" onClick={onClose} disabled={isDialogLocked} title={isDialogLocked ? lockedReason : undefined} className="studio-icon-button -mr-2 -mt-2 disabled:cursor-not-allowed disabled:opacity-40" aria-label={t('workspace.close')}><X size={17} /></button>
        </header>

        <div data-testid="workspace-create-dialog-scroll" className="min-h-0 overflow-y-auto px-5 pb-5 sm:px-7">
          {isWorkspaceLocked && !isGenerating && <div className="mb-4 flex items-start gap-2 rounded-lg bg-amber-50 p-3 text-xs leading-5 text-amber-800 dark:bg-amber-400/10 dark:text-amber-200" role="status" data-testid="workspace-create-dialog-lock-notice"><Loader2 size={14} className="mt-0.5 shrink-0 animate-spin" /><span>{lockedReason}</span></div>}

          <label htmlFor="create-diagram-prompt" className="mb-2 block text-xs font-medium text-slate-600 dark:text-slate-300">{t('workspace.createDialogPromptLabel')}</label>
          <textarea id="create-diagram-prompt" ref={promptRef} value={prompt} onChange={(event) => onPromptChange(event.target.value)} disabled={isDialogLocked}
            placeholder={t('workspace.createDialogPlaceholder')} aria-describedby="create-diagram-prompt-hint" rows={5} className="create-diagram-prompt"
            onKeyDown={(event) => {
              if (shouldSubmitOnModifiedEnter(event)) {
                event.preventDefault();
                if (!isDialogLocked && !promptIsEmpty) onGenerate();
              }
            }} />
          <div className="mt-1 flex flex-wrap items-center justify-between gap-x-3">
            <p id="create-diagram-prompt-hint" className="py-2 text-[11px] text-slate-400 dark:text-slate-500">{t('workspace.createDialogKeyboardHint')}</p>
            <button type="button" onClick={onEnhance} disabled={isDialogLocked || promptIsEmpty || requirementsAdded} className="studio-secondary -mr-2 gap-1.5 px-2 text-[11px]"><Sparkles size={13} />{t(requirementsAdded ? 'workspace.createDialogRequirementsAdded' : 'workspace.createDialogAddRequirements')}</button>
          </div>

          <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400"><label htmlFor="create-diagram-type">{t('workspace.createDialogTypeLabel')}</label>
              <ChoiceSelect id="create-diagram-type" label={t('workspace.createDialogTypeLabel')} value={selectedPillId} disabled={isDialogLocked}
                options={allPills.map(pill => ({ value: pill.id, label: pill.label, featured: pill.id === 'adaptive' }))}
                onChange={value => { const pill = allPills.find(item => item.id === value); if (pill) onSelectPill(pill); }} />
            </div>
            <label className={`relative flex min-h-11 items-center gap-2.5 text-xs text-slate-600 dark:text-slate-300 ${isDialogLocked || !supportsIcons ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}>
              <input type="checkbox" role="switch" checked={useIcons && supportsIcons} onChange={(event) => onUseIconsChange(event.target.checked)} disabled={isDialogLocked || !supportsIcons} aria-describedby="create-diagram-icons-hint" className="peer absolute inset-0 z-10 h-full w-full cursor-[inherit] opacity-0" />
              <span aria-hidden="true" className="create-diagram-switch" />
              <span>{t('workspace.useIcons')}</span>
            </label>
          </div>
          {!supportsIcons && <p id="create-diagram-icons-hint" className="mt-2 text-xs text-slate-500 dark:text-slate-400">{t('workspace.useIconsCanvasHint')}</p>}
          {supportsIcons && <span id="create-diagram-icons-hint" className="sr-only">{t('workspace.useIconsHint')}</span>}

          {handoff?.rulesLabel && <details className="create-diagram-details mt-4" data-testid="workspace-preflight-handoff">
            <summary><span>{handoff.rulesLabel}{handoff.moreRulesLabel && <span className="ml-2 text-slate-400">{handoff.moreRulesLabel}</span>}</span><ChevronDown size={14} /></summary>
            <div className="divide-y divide-slate-200/60 dark:divide-white/[0.07]">
              {handoff.rules?.length ? handoff.rules.map((rule) => <div key={`${rule.cabinLabel}:${rule.title}:${rule.preview}`} className="py-3">
                <p className="text-xs font-medium text-slate-700 dark:text-slate-200"><span className="mr-2 text-indigo-500 dark:text-indigo-300">{rule.cabinLabel}</span>{rule.title}</p>
                <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{rule.preview}</p>
              </div>) : <p className="py-3 text-xs leading-5 text-slate-500 dark:text-slate-400">{handoff.emptyRulesLabel}</p>}
            </div>
          </details>}

          {(canvasOptions.length > 1 || modelOptions.length > 1) && <details className="create-diagram-details mt-3">
            <summary><span className="flex items-center gap-2"><Settings2 size={14} />{t('workspace.createDialogAdvanced')}</span><ChevronDown size={14} /></summary>
            <fieldset disabled={isDialogLocked} className="space-y-3 pb-2 pt-3">
              {modelOptions.length > 1 && <div className="flex items-center justify-between gap-3 text-xs text-slate-500 dark:text-slate-400"><label htmlFor="create-diagram-model">{t('home.modelIconTitle')}</label><ChoiceSelect id="create-diagram-model" label={t('home.modelIconTitle')} value={String(modelIndex)} disabled={isDialogLocked} align="end" options={modelOptions.map((model, index) => ({ value: String(index), label: model.label }))} onChange={value => onModelChange(Number(value))} /></div>}
              {canvasOptions.length > 1 && <div className="flex items-center justify-between gap-3 text-xs text-slate-500 dark:text-slate-400"><label htmlFor="create-diagram-canvas">{t('settings.canvasEngine')}</label><ChoiceSelect id="create-diagram-canvas" label={t('settings.canvasEngine')} value={String(canvasIndex)} disabled={isDialogLocked} align="end" options={canvasOptions.map((canvas, index) => ({ value: String(index), label: canvas.label }))} onChange={value => onCanvasChange(Number(value))} /></div>}
            </fieldset>
          </details>}

          {promptIsEmpty && !isDialogLocked && <p className="mt-3 text-xs text-slate-500 dark:text-slate-400" role="status" data-testid="workspace-create-dialog-prompt-required">{t('workspace.createDialogPromptRequired')}</p>}
          {isGenerating && progress && <div className="mt-4" role="status" aria-live="polite"><StageProgress progress={progress} t={t} />{progress.message && <p className="mt-2 text-xs leading-5 text-indigo-600 dark:text-indigo-300">{progress.message}</p>}</div>}
        </div>

        <footer className="flex shrink-0 flex-col gap-3 border-t border-slate-200/70 px-5 pb-[max(env(safe-area-inset-bottom),1.25rem)] pt-4 dark:border-white/[0.07] sm:flex-row sm:items-center sm:justify-between sm:px-7">
          <div className="flex min-w-0 items-center gap-2 text-[11px] text-slate-500 dark:text-slate-400">
            <span className="truncate" title={modelLabel}>{modelLabel}</span>
            {BROWSER_MODE && <button type="button" onClick={openModelSettings} disabled={isDialogLocked} className="studio-secondary shrink-0 gap-1 px-2 text-[11px]">{t('workspace.createDialogModelSettings')}<ArrowUpRight size={12} /></button>}
          </div>
          <div className="flex shrink-0 items-center justify-end gap-2">
            <button type="button" onClick={isGenerating ? onCancelGeneration : onClose} className="studio-secondary shrink-0" disabled={(isGenerating && !onCancelGeneration) || isWorkspaceLocked} title={isWorkspaceLocked ? lockedReason : undefined}>
              {isGenerating ? t('workspace.stopGeneration') : isWorkspaceLocked ? t('workspace.createDialogLockedAction') : t('workspace.cancel')}
            </button>
            <button type="submit" className="studio-primary flex-1 sm:flex-none" disabled={isDialogLocked || promptIsEmpty} aria-busy={isGenerating} title={isDialogLocked ? lockedReason : promptIsEmpty ? t('workspace.createDialogPromptRequired') : undefined}>
              {isGenerating && <Loader2 size={14} className="animate-spin" />}{t(isGenerating ? 'workspace.generating' : 'workspace.onboardingGenerate')}
            </button>
          </div>
        </footer>
      </form>
    </dialog>
  );
}
