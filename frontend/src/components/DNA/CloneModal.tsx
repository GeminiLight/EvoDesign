import {
  Check,
  Loader2,
  Sparkles,
  Upload,
  X,
} from 'lucide-react';
import { useEffect, useRef } from 'react';
import type { CabinId, CloneCandidate, CloneStatus, CloneStep } from '../../types/dna';
import { ChoiceSelect } from '../ChoiceSelect';

interface CloneModalProps {
  t: (key: string) => string;
  cloneStepList: Array<{ key: CloneStep; label: string }>;
  cloneCurrentStepIndex: number;
  cloneStatus: CloneStatus;
  cloneFileName: string;
  setCloneFileName: (name: string) => void;
  onFileChange: (file: File | null) => void;
  setCloneStep: (step: CloneStep) => void;
  cloneCandidates: CloneCandidate[];
  cloneMessage: string;
  runCloneExtraction: () => void;
  updateCloneCandidate: (tempId: number, patch: Partial<CloneCandidate>) => void;
  applyCloneCandidates: () => void;
  cloneCandidateErrors: Record<number, { title: boolean; preview: boolean }>;
  hasCloneCandidateErrors: boolean;
  selectedCandidateCount: number;
  canApplyCloneCandidates: boolean;
  onClose: () => void;
}

export function CloneModal({
  t,
  cloneStepList,
  cloneCurrentStepIndex,
  cloneStatus,
  cloneFileName,
  setCloneFileName,
  onFileChange,
  setCloneStep,
  cloneCandidates,
  cloneMessage,
  runCloneExtraction,
  updateCloneCandidate,
  applyCloneCandidates,
  cloneCandidateErrors,
  hasCloneCandidateErrors,
  selectedCandidateCount,
  canApplyCloneCandidates,
  onClose,
}: CloneModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const firstInputRef = useRef<HTMLInputElement>(null);
  const titleId = 'dna-clone-dialog-title';
  const descriptionId = 'dna-clone-dialog-description';
  const isParsing = cloneStatus === 'parsing';
  const messageIsError = cloneStatus === 'missing-source' || cloneStatus === 'error' || hasCloneCandidateErrors;
  const fallbackMessage = hasCloneCandidateErrors
    ? t('dna.page.cloneCandidateInvalid')
    : !canApplyCloneCandidates
      ? t('dna.page.cloneApplyDisabledHint')
      : '';
  const statusMessage = hasCloneCandidateErrors ? t('dna.page.cloneCandidateInvalid') : cloneMessage || fallbackMessage;

  useEffect(() => {
    firstInputRef.current?.focus();
  }, []);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.stopPropagation();
      onClose();
      return;
    }

    if (event.key !== 'Tab' || !dialogRef.current) return;

    const focusableElements = Array.from(
      dialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ),
    );

    if (focusableElements.length === 0) return;

    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];

    if (event.shiftKey && document.activeElement === firstElement) {
      event.preventDefault();
      lastElement.focus();
    } else if (!event.shiftKey && document.activeElement === lastElement) {
      event.preventDefault();
      firstElement.focus();
    }
  };

  return (
    <div className="studio-modal-backdrop fixed inset-0 z-[70] flex items-end justify-center px-3 py-3 sm:items-center sm:px-4" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        onKeyDown={handleKeyDown}
        className="studio-dialog-panel max-h-[calc(100dvh-1.5rem)] w-full max-w-3xl overflow-y-auto p-4 sm:p-5"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h3 id={titleId} className="text-lg font-semibold text-slate-900 dark:text-slate-100">{t('dna.page.cloneTitle')}</h3>
            <p id={descriptionId} className="mt-1 text-sm text-slate-600 dark:text-slate-300">{t('dna.page.cloneDesc')}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('dna.page.cloneCloseLabel')}
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg border border-white/45 bg-white/70 p-1.5 text-slate-600 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:ring-offset-2 dark:border-white/10 dark:bg-slate-900/78 dark:text-slate-200 dark:focus-visible:ring-offset-slate-950"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mb-4 grid grid-cols-4 gap-2">
          {cloneStepList.map((step, index) => {
            const active = index <= cloneCurrentStepIndex;
            return (
              <div key={step.key} className={`rounded-lg border px-2 py-2 text-center text-[11px] font-semibold ${active ? 'border-indigo-300 bg-indigo-100/70 text-indigo-700 dark:border-indigo-500/40 dark:bg-indigo-500/14 dark:text-indigo-300' : 'border-white/45 bg-white/65 text-slate-400 dark:border-white/10 dark:bg-slate-900/75 dark:text-slate-400'}`}>
                {step.label}
              </div>
            );
          })}
        </div>

        <div className="grid grid-cols-1 gap-4">
          <label className="rounded-xl border border-white/45 bg-white/65 p-3 dark:border-white/10 dark:bg-slate-900/78">
            <span className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-600 dark:text-slate-300">
              <Upload className="h-3.5 w-3.5" />
              {t('dna.page.cloneUpload')}
            </span>
            <input
              ref={firstInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(event) => {
                const file = event.target.files?.[0] ?? null;
                setCloneFileName(file?.name ?? '');
                onFileChange(file);
                if (file) setCloneStep('upload');
              }}
              className="w-full rounded-lg text-xs text-slate-600 file:mr-3 file:min-h-10 file:rounded-md file:border-0 file:bg-indigo-500 file:px-3 file:py-2 file:text-xs file:font-semibold file:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:ring-offset-2 dark:text-slate-300 dark:focus-visible:ring-offset-slate-950"
            />
            <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">{cloneFileName || t('dna.page.cloneFileHint')}</p>
          </label>
        </div>

        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-slate-600 dark:text-slate-300">{t('dna.page.cloneSelectHint')}</p>
          <button
            type="button"
            onClick={runCloneExtraction}
            disabled={isParsing}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-950"
          >
            {isParsing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
            {isParsing ? t('dna.page.cloneParsing') : t('dna.page.cloneExtract')}
          </button>
        </div>

        <div className="mt-4 rounded-xl border border-white/40 bg-white/55 p-3 dark:border-white/10 dark:bg-slate-900/76">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{t('dna.page.cloneReviewTitle')}</h4>
            <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {t('dna.page.cloneSelectedCount').replace('{count}', String(selectedCandidateCount))}
            </span>
          </div>
          <div className="custom-scrollbar max-h-[38dvh] space-y-2 overflow-y-auto pb-24 pr-1 sm:max-h-72 sm:pb-0">
            {cloneCandidates.map((candidate) => {
              const errors = cloneCandidateErrors[candidate.tempId];
              const titleErrorId = `dna-clone-title-error-${candidate.tempId}`;
              const previewErrorId = `dna-clone-preview-error-${candidate.tempId}`;
              const hasTitleError = Boolean(errors?.title);
              const hasPreviewError = Boolean(errors?.preview);

              return (
                <div key={candidate.tempId} className={`rounded-lg border bg-white/70 p-3 dark:bg-slate-900/78 ${hasTitleError || hasPreviewError ? 'border-rose-300/80 dark:border-rose-400/40' : 'border-white/45 dark:border-white/10'}`}>
                <div className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-center">
                  <label className="inline-flex min-h-11 items-center gap-2 rounded-lg px-1 text-xs font-semibold text-slate-600 dark:text-slate-300">
                    <input
                      type="checkbox"
                      checked={candidate.selected}
                      onChange={(event) => updateCloneCandidate(candidate.tempId, { selected: event.target.checked })}
                      aria-label={`${t('dna.page.cloneSelectCandidate')}: ${candidate.title}`}
                      className="h-5 w-5 rounded border-slate-300 text-indigo-600 focus-visible:ring-2 focus-visible:ring-indigo-500/60"
                    />
                    <span className="sm:sr-only">{t('dna.page.cloneSelectCandidate')}</span>
                  </label>
                  <input
                    value={candidate.title}
                    aria-label={t('dna.page.cloneCandidateTitleLabel')}
                    aria-invalid={hasTitleError}
                    aria-describedby={hasTitleError ? titleErrorId : undefined}
                    onChange={(event) => updateCloneCandidate(candidate.tempId, { title: event.target.value })}
                    className={`h-11 min-w-0 flex-1 rounded-md border bg-white/85 px-2 text-sm text-slate-700 outline-none transition focus-visible:ring-2 focus-visible:ring-offset-2 dark:bg-slate-900/86 dark:text-slate-100 dark:focus-visible:ring-offset-slate-950 ${hasTitleError ? 'border-rose-300 focus:border-rose-400 focus-visible:ring-rose-500/60 dark:border-rose-400/50' : 'border-white/45 focus:border-indigo-300 focus-visible:ring-indigo-500/60 dark:border-white/10'}`}
                  />
                  <ChoiceSelect value={candidate.cabinId} label={t('dna.page.cloneCabinLabel')} menuWidth={160}
                    options={[{ value: 'structure', label: t('dna.page.structureTag') }, { value: 'style', label: t('dna.page.styleTag') }, { value: 'layout', label: t('dna.page.layoutTag') }]}
                    onChange={value => updateCloneCandidate(candidate.tempId, { cabinId: value as CabinId })} />
                </div>
                <textarea
                  value={candidate.preview}
                  aria-label={t('dna.page.cloneCandidatePreviewLabel')}
                  aria-invalid={hasPreviewError}
                  aria-describedby={hasPreviewError ? previewErrorId : undefined}
                  onChange={(event) => updateCloneCandidate(candidate.tempId, { preview: event.target.value })}
                  rows={2}
                  className={`w-full rounded-md border bg-white/85 px-2 py-2 text-xs text-slate-700 outline-none transition focus-visible:ring-2 focus-visible:ring-offset-2 dark:bg-slate-900/86 dark:text-slate-100 dark:focus-visible:ring-offset-slate-950 ${hasPreviewError ? 'border-rose-300 focus:border-rose-400 focus-visible:ring-rose-500/60 dark:border-rose-400/50' : 'border-white/45 focus:border-indigo-300 focus-visible:ring-indigo-500/60 dark:border-white/10'}`}
                />
                {(hasTitleError || hasPreviewError) && (
                  <div className="mt-2 space-y-1 text-[11px] font-medium text-rose-600 dark:text-rose-300">
                    {hasTitleError && <p id={titleErrorId} role="alert">{t('dna.page.cloneCandidateTitleRequired')}</p>}
                    {hasPreviewError && <p id={previewErrorId} role="alert">{t('dna.page.cloneCandidatePreviewRequired')}</p>}
                  </div>
                )}
                </div>
              );
            })}

            {cloneCandidates.length === 0 && (
              <div className="rounded-lg border border-dashed border-white/45 bg-white/45 p-3 text-xs text-slate-500 dark:border-white/10 dark:bg-slate-900/72 dark:text-slate-300">
                {t('dna.page.cloneNoCandidate')}
              </div>
            )}
          </div>
        </div>

        <div className="sticky bottom-0 -mx-4 mt-4 flex flex-col gap-3 border-t border-white/55 bg-white/95 px-4 py-3 shadow-[0_-18px_32px_-24px_rgba(15,23,42,0.55)] dark:border-white/10 dark:bg-slate-950/98 sm:static sm:mx-0 sm:flex-row sm:items-center sm:justify-between sm:border-t-0 sm:bg-transparent sm:px-0 sm:py-0 sm:shadow-none dark:sm:bg-transparent">
          <p
            role={messageIsError ? 'alert' : 'status'}
            aria-live={messageIsError ? 'assertive' : 'polite'}
            className={`text-xs ${messageIsError ? 'text-rose-600 dark:text-rose-300' : 'text-emerald-700 dark:text-emerald-300'}`}
          >
            {statusMessage}
          </p>
          <button
            type="button"
            onClick={applyCloneCandidates}
            disabled={!canApplyCloneCandidates}
            className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2 text-xs font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-950 ${canApplyCloneCandidates ? 'bg-emerald-600 text-white hover:bg-emerald-500' : 'cursor-not-allowed bg-slate-200 text-slate-500 dark:bg-slate-800 dark:text-slate-500'}`}
          >
            <Check className="h-3.5 w-3.5" />
            {t('dna.page.cloneApply')}
          </button>
        </div>
      </div>
    </div>
  );
}
