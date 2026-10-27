import { useEffect, useId, useRef, useState } from 'react';
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
  const { t, language } = useLanguage();
  const promptHintId = useId();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [promptDraft, setPromptDraft] = useState('');

  useEffect(() => {
    const trimmedInitialPrompt = initialPrompt.trim();
    if (!trimmedInitialPrompt) return;
    setPromptDraft((current) => current || trimmedInitialPrompt);
  }, [initialPrompt]);

  if (dismissed) {
    return (
      <div className="pointer-events-none absolute inset-x-0 bottom-16 z-10 flex justify-center px-4">
        <button type="button" data-testid="workspace-onboarding-launcher" onClick={() => onDismissedChange(false)}
          className="studio-secondary pointer-events-auto border border-slate-200 bg-white/95 shadow-sm dark:border-white/10 dark:bg-slate-900/95">
          <Sparkles size={16} className="text-violet-500 dark:text-violet-300" />
          {t('workspace.onboardingLauncherAction')}<ArrowRight size={14} />
        </button>
      </div>
    );
  }

  const hasPromptDraft = promptDraft.trim().length > 0;
  const promptHint = hasPromptDraft ? t('workspace.onboardingPromptReadyHint') : (language === 'zh' ? '写下想法，或选择一个示例开始。' : 'Write your idea or choose an example to get started.');
  const canSubmit = hasPromptDraft && !isGenerating;
  const examples = [
    { label: language === 'zh' ? '微服务架构' : 'Architecture', prompt: t('workspace.onboardingPlaceholder') },
    { label: language === 'zh' ? '登录流程' : 'Login flow', prompt: t('workspace.onboardingExample2') },
    { label: language === 'zh' ? '数据关系' : 'Data model', prompt: t('workspace.onboardingExample3') },
  ];

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (canSubmit) onGeneratePrompt(promptDraft.trim());
  };

  return (
    <div className="pointer-events-none absolute inset-0 z-10 flex items-start justify-center overflow-y-auto overscroll-contain px-4 pb-20 pt-20 sm:items-center sm:p-6">
      <section data-testid="workspace-onboarding" aria-labelledby="workspace-onboarding-title"
        className="pointer-events-auto relative w-full max-w-lg rounded-2xl border border-slate-200/80 bg-white p-5 shadow-[0_8px_40px_-20px_rgba(15,23,42,0.25)] dark:border-white/10 dark:bg-[#101524] sm:p-6">
        <button type="button" onClick={() => onDismissedChange(true)} className="studio-icon-button absolute right-2 top-2" aria-label={t('workspace.dismissOnboarding')}><X size={16} /></button>
        <div className="pr-6">
          <Sparkles size={20} className="mb-3 text-violet-500 dark:text-violet-300" />
          <h2 id="workspace-onboarding-title" className="text-base font-semibold text-slate-900 dark:text-slate-100">{t('workspace.onboardingTitle')}</h2>
          <p className="mt-1.5 text-[13px] leading-6 text-slate-500 dark:text-slate-400">{language === 'zh' ? '描述你的想法，再确认生成选项。' : 'Describe your idea, then choose how to create it.'}</p>
        </div>
        <form onSubmit={handleSubmit} className="mt-4">
          <div className="overflow-hidden rounded-xl border border-slate-200 transition focus-within:border-violet-400 focus-within:ring-2 focus-within:ring-violet-400/10 dark:border-white/10 dark:focus-within:border-violet-400/60">
            <textarea ref={inputRef} value={promptDraft} onChange={(event) => setPromptDraft(event.target.value)} rows={3}
              placeholder={t('workspace.onboardingInputPlaceholder')} aria-label={t('workspace.onboardingPromptLabel')} aria-describedby={promptHintId}
              className="block min-h-24 w-full resize-y border-0 bg-transparent p-3 text-sm leading-6 text-slate-800 placeholder:text-slate-400 focus:ring-0 dark:text-slate-100 dark:placeholder:text-slate-500" />
            <div className="flex flex-wrap items-center gap-1 border-t border-slate-200/60 px-2 py-1 dark:border-white/[0.06]">
              {examples.map((example) => <button key={example.label} type="button" disabled={isGenerating}
                onClick={() => { setPromptDraft(example.prompt); inputRef.current?.focus(); }}
                className="studio-secondary min-h-9 px-2 text-xs" title={example.prompt}>{example.label}</button>)}
            </div>
          </div>
          <div className="mt-4 flex justify-end">
            <span id={promptHintId} className="sr-only">{promptHint}</span>
            <button type="submit" disabled={!canSubmit} className="studio-primary" title={!hasPromptDraft ? t('workspace.onboardingPromptRequiredHint') : undefined}>
              {t('workspace.onboardingContinueSetup')}<ArrowRight size={15} />
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
