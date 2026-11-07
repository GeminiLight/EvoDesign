import { Minus } from 'lucide-react';
import { useEffect, useState } from 'react';
import { formatGenerationDuration } from '../utils/generationReport';
import type { StreamStageExtended } from '../types/app';
import type { GenerationProgress } from '../types/app';

const STAGE_DEFS: { key: StreamStageExtended; labelKey: string }[] = [
  { key: 'memory', labelKey: 'landing.workflowMemory' },
  { key: 'structure', labelKey: 'landing.workflowExtract' },
  { key: 'styling', labelKey: 'landing.workflowIntent' },
  { key: 'layout', labelKey: 'landing.workflowLayout' },
  { key: 'render', labelKey: 'landing.workflowRender' },
  { key: 'verification', labelKey: 'landing.workflowVerification' },
  { key: 'refining', labelKey: 'landing.workflowRefining' },
  { key: 'final_verification', labelKey: 'landing.workflowFinalVerification' },
  { key: 'learning', labelKey: 'landing.workflowLearning' },
];

export function StageProgress({ progress, t }: { progress: GenerationProgress; t: (key: string) => string }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const refinerSkipped = Boolean(progress.refinerSkipped);
  const refinerSkippedMessage = progress.refinerSkippedMessage;
  const refinerActive =
    progress.currentStage === 'refining' ||
    progress.completedStages.includes('refining') ||
    Boolean(progress.refineComplete);

  const visibleStages = STAGE_DEFS.filter(
    (stage) =>
      stage.key === 'refining' ? refinerActive || refinerSkipped
        : ['final_verification', 'learning'].includes(stage.key)
          ? progress.currentStage === stage.key || progress.completedStages.includes(stage.key)
          : true,
  );

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      {visibleStages.map((stage, idx) => {
        const isCompleted = progress.completedStages.includes(stage.key);
        const isActive = progress.currentStage === stage.key && !isCompleted;
        const isSkipped = stage.key === 'refining' && refinerSkipped && !refinerActive;
        const isLast = idx === visibleStages.length - 1;
        const label = t(stage.labelKey);
        return (
          <div
            key={stage.key}
            className="flex items-center gap-1.5"
            title={isSkipped ? refinerSkippedMessage : undefined}
          >
            {isSkipped ? (
              <span className="flex h-4 w-4 items-center justify-center rounded-full bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500">
                <Minus className="h-2.5 w-2.5" />
              </span>
            ) : isCompleted ? (
              <span className="flex h-4 w-4 items-center justify-center rounded-full bg-emerald-100 text-emerald-600 dark:bg-emerald-500/20 dark:text-emerald-400">
                <svg className="h-2.5 w-2.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
              </span>
            ) : isActive ? (
              <svg className="h-4 w-4 animate-spin text-brand-500" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" /></svg>
            ) : (
              <span className="flex h-4 w-4 items-center justify-center rounded-full border border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800" />
            )}
            <span className={`text-[11px] font-medium ${
              isSkipped
                ? 'text-slate-500 dark:text-slate-400'
                : isCompleted
                  ? 'text-emerald-700 dark:text-emerald-400'
                  : isActive
                    ? 'text-brand-600 dark:text-brand-400'
                    : 'text-slate-500 dark:text-slate-400'
            }`}>
              {label}
              {isSkipped && (
                <span className="ml-1 text-[10px] text-slate-500 dark:text-slate-400">
                  {t('landing.workflowSkipped')}
                </span>
              )}
            </span>
            {!isLast && <span className="text-slate-300 text-[10px] dark:text-slate-600">/</span>}
          </div>
        );
      })}
      {progress.startedAt && (
        <span className="basis-full pt-1 text-[10px] tabular-nums text-slate-500 dark:text-slate-400">
          {t('workspace.elapsedTime')} {formatGenerationDuration(Math.max(0, now - progress.startedAt))}
          {progress.stageStartedAt && <> · {t('workspace.currentStageTime')} {formatGenerationDuration(Math.max(0, now - progress.stageStartedAt))}</>}
        </span>
      )}
    </div>
  );
}
