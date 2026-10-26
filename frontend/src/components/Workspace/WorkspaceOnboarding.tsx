import { useEffect, useId, useState } from 'react';
import type { FormEvent } from 'react';
import { ArrowRight, Sparkles, X } from 'lucide-react';
import { useLanguage } from '../../i18n/LanguageProvider';

interface WorkspaceOnboardingProps {
  onGeneratePrompt: (prompt: string) => void;
  isGenerating?: boolean;
  initialPrompt?: string;
  dismissed: boolean;
  onDismissedChange: (dismissed: boolean) => void;
}

export function WorkspaceOnboarding({
  onGeneratePrompt,
  isGenerating = false,
  initialPrompt = '',
  dismissed,
  onDismissedChange,
}: WorkspaceOnboardingProps) {
  const { t } = useLanguage();
  const promptHintId = useId();
  const [promptDraft, setPromptDraft] = useState('');

  useEffect(() => {
    const trimmedInitialPrompt = initialPrompt.trim();
    if (!trimmedInitialPrompt) return;
    setPromptDraft((current) => current || trimmedInitialPrompt);
  }, [initialPrompt]);

  if (dismissed) {
    return (
      <div className="absolute inset-0 z-10 flex items-center justify-center p-3 pointer-events-none sm:p-6">
        <div
          data-testid="workspace-onboarding-launcher"
          className="pointer-events-auto w-full max-w-sm rounded-2xl border border-white/80 bg-white/88 p-4 text-center shadow-[0_20px_56px_rgba(82,112,148,0.22)] ring-1 ring-white/80 backdrop-blur-2xl dark:border-white/10 dark:bg-slate-950/86 dark:shadow-[0_24px_70px_rgba(2,6,23,0.58)] dark:ring-white/10"
        >
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-500 dark:bg-brand-500/20 dark:text-brand-300">
            <Sparkles className="h-6 w-6" />
          </div>
          <h2 className="mt-3 text-base font-bold leading-tight text-slate-900 dark:text-slate-100">
            {t('workspace.onboardingLauncherTitle')}
          </h2>
          <p className="mx-auto mt-1 max-w-[18rem] text-sm leading-relaxed text-slate-500 dark:text-slate-400">
            {t('workspace.onboardingLauncherHint')}
          </p>
          <button
            type="button"
            onClick={() => onDismissedChange(false)}
            className="mt-4 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-brand-600 px-4 text-sm font-semibold text-white shadow-[0_12px_26px_rgba(49,141,255,0.24)] transition hover:bg-brand-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-950 sm:w-auto"
          >
            {t('workspace.onboardingLauncherAction')}
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    );
  }

  const hasPromptDraft = promptDraft.trim().length > 0;
  const detailedExample = t('workspace.onboardingPlaceholder');
  const promptHint = hasPromptDraft
    ? t('workspace.onboardingPromptReadyHint')
    : t('workspace.onboardingPromptRequiredHint');
  const canSubmit = hasPromptDraft && !isGenerating;
  const examples = [
    t('workspace.onboardingExample1'),
    t('workspace.onboardingExample2'),
    t('workspace.onboardingExample3'),
  ];

  const submitPrompt = (value: string) => {
    const prompt = value.trim();
    if (!prompt || isGenerating) return;
    onGeneratePrompt(prompt);
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    submitPrompt(promptDraft);
  };

  return (
    <div className="absolute inset-0 z-10 flex items-start justify-center overflow-y-auto overscroll-contain p-3 pointer-events-none sm:items-center sm:p-6">
      <div
        data-testid="workspace-onboarding"
        className="pointer-events-auto relative max-h-full w-full max-w-2xl overflow-y-auto rounded-2xl border border-white/80 bg-white/90 p-4 text-left shadow-[0_24px_70px_rgba(82,112,148,0.24)] ring-1 ring-white/80 backdrop-blur-2xl dark:border-white/10 dark:bg-slate-950/88 dark:shadow-[0_26px_80px_rgba(2,6,23,0.58)] dark:ring-white/10 sm:p-5"
      >
        <button
          type="button"
          onClick={() => onDismissedChange(true)}
          className="absolute right-3 top-3 flex h-11 w-11 items-center justify-center rounded-xl text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300"
          aria-label={t('workspace.dismissOnboarding')}
        >
          <X className="h-4.5 w-4.5" />
        </button>

        <div className="flex items-start gap-3 pr-10">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-brand-50 text-brand-500 dark:bg-brand-500/20 dark:text-brand-300">
            <Sparkles className="h-6 w-6" />
          </div>
          <div className="min-w-0">
            <h2 className="text-lg font-bold leading-tight text-slate-900 dark:text-slate-100">
              {t('workspace.onboardingTitle')}
            </h2>
            <p className="mt-1 text-sm leading-relaxed text-slate-500 dark:text-slate-400">
              {t('workspace.onboardingHint')}
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="mt-5 rounded-2xl border border-slate-200 bg-slate-50/85 p-2 shadow-inner dark:border-slate-800 dark:bg-slate-900/80">
          <textarea
            value={promptDraft}
            onChange={(event) => setPromptDraft(event.target.value)}
            rows={4}
            placeholder={t('workspace.onboardingInputPlaceholder')}
            aria-label={t('workspace.onboardingPromptLabel')}
            aria-describedby={promptHintId}
            className="min-h-28 w-full resize-none rounded-xl border-0 bg-transparent px-3 py-3 text-sm leading-relaxed text-slate-800 outline-none placeholder:text-slate-400 dark:text-slate-100 dark:placeholder:text-slate-500"
          />
          {!hasPromptDraft && (
            <button
              type="button"
              onClick={() => setPromptDraft(detailedExample)}
              disabled={isGenerating}
              className="mx-1 mb-2 flex w-[calc(100%-0.5rem)] flex-col rounded-xl border border-brand-200/70 bg-white/75 px-3 py-2.5 text-left text-xs leading-relaxed text-slate-500 transition hover:border-brand-300 hover:bg-brand-50/60 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 disabled:cursor-not-allowed disabled:opacity-50 dark:border-brand-500/25 dark:bg-slate-950/35 dark:text-slate-400 dark:hover:border-brand-400/40 dark:hover:bg-brand-500/10 dark:hover:text-slate-200"
            >
              <span className="mb-1 font-semibold text-brand-600 dark:text-brand-300">
                {t('workspace.onboardingDetailedExampleLabel')}
              </span>
              <span className="line-clamp-2">
                {detailedExample}
              </span>
            </button>
          )}
          <div className="flex flex-col gap-2 border-t border-slate-200/80 px-1 pt-2 dark:border-slate-800 sm:flex-row sm:items-center sm:justify-between">
            <span id={promptHintId} className="min-w-0 px-2 text-xs font-medium leading-relaxed text-slate-500 dark:text-slate-400">
              {promptHint}
            </span>
            <button
              type="submit"
              disabled={!canSubmit}
              title={!hasPromptDraft ? t('workspace.onboardingPromptRequiredHint') : undefined}
              className={`inline-flex min-h-11 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-xl px-4 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-950 ${
                canSubmit
                  ? 'bg-brand-600 text-white shadow-[0_12px_26px_rgba(49,141,255,0.24)] hover:bg-brand-500'
                  : 'cursor-not-allowed bg-slate-200 text-slate-400 shadow-none dark:bg-slate-800 dark:text-slate-500'
              }`}
            >
              {t('workspace.onboardingContinueSetup')}
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </form>

        <div className="mt-4 grid gap-2 sm:grid-cols-3">
          <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 sm:col-span-3">
            {t('workspace.quickPromptsStartTitle')}
          </p>
          {examples.map((example) => (
            <button
              key={example}
              type="button"
              disabled={isGenerating}
              onClick={() => submitPrompt(example)}
              className="min-h-11 rounded-xl border border-slate-200/80 bg-white/75 px-3 py-2.5 text-sm font-medium leading-snug text-slate-700 transition hover:border-brand-300 hover:bg-brand-50/70 hover:text-brand-600 disabled:cursor-not-allowed disabled:opacity-45 dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-200 dark:hover:border-brand-500 dark:hover:bg-brand-500/10 dark:hover:text-brand-300"
            >
              {example}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
