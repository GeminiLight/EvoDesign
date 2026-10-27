import { AlertTriangle, BrainCircuit, Check, ChevronDown, Clock3, Sparkles } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { apiV1Url, getStoredAuthToken } from '../services/httpClient';
import { formatGenerationDuration, type GenerationReport as Report } from '../utils/generationReport';

const stageKeys: Record<string, string> = {
  memory: 'workflowMemory', structure: 'workflowExtract', styling: 'workflowIntent',
  layout: 'workflowLayout', render: 'workflowRender', verification: 'workflowVerification',
  refining: 'workflowRefining', final_verification: 'workflowFinalVerification', learning: 'workflowLearning',
};

export function GenerationReport({ report, t, compact = false }: { report: Report; t: (key: string) => string; compact?: boolean }) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (!compact) return;
    const closeOutside = (event: MouseEvent) => {
      if (detailsRef.current && !detailsRef.current.contains(event.target as Node)) detailsRef.current.open = false;
    };
    const closeEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && detailsRef.current?.open) {
        detailsRef.current.open = false;
        detailsRef.current.querySelector('summary')?.focus();
      }
    };
    document.addEventListener('mousedown', closeOutside);
    document.addEventListener('keydown', closeEscape);
    return () => {
      document.removeEventListener('mousedown', closeOutside);
      document.removeEventListener('keydown', closeEscape);
    };
  }, [compact]);
  const [learned, setLearned] = useState<Report['learning']>();
  const jobId = report.learning.jobId;
  useEffect(() => {
    const token = getStoredAuthToken();
    if (!jobId || !token || !['queued', 'running'].includes(report.learning.status)) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let attempts = 0;
    const poll = async () => {
      attempts += 1;
      try {
        const response = await fetch(apiV1Url(`/diagram/learning/${encodeURIComponent(jobId)}`), {
          headers: { Authorization: `Bearer ${token}` }, signal: controller.signal,
        });
        if (response.ok) {
          const data = await response.json();
          if (typeof data.status === 'string') {
            setLearned({ jobId, status: data.status, savedCount: Number(data.saved_count) || 0 });
            if (!['queued', 'running'].includes(data.status)) return;
          }
        }
      } catch { /* A later poll or reopening the snapshot can recover. */ }
      if (!controller.signal.aborted && attempts < 24) timer = setTimeout(poll, Math.min(15000, attempts * 2000));
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [jobId, report.learning.status]);
  const learningState = learned && learned.jobId === jobId ? learned : report.learning;
  const label = (key: string, count: number) => t(`workspace.${key}`).replace('{count}', String(count));
  const memory = report.browserEdition ? t('browser.edition') : report.memory.status === 'used'
    ? label('memoryUsed', report.memory.retrievedCount)
    : t(`workspace.memory${report.memory.status === 'unavailable' ? 'Unavailable' : report.memory.status === 'disabled' ? 'Disabled' : 'Empty'}`);
  const edited = report.qualityStatus === 'edited';
  const attentionLabel = report.browserEdition ? '' : report.qualityStatus === 'needs_attention' ? t('workspace.qualityNeedsAttentionShort')
    : report.qualityStatus === 'unverified' ? t('workspace.qualityUnverified') : '';
  const detailsLabel = [t('workspace.generationDetails'), attentionLabel].filter(Boolean).join(' · ');
  const refined = report.refinement.status === 'completed';
  const keptOriginal = ['failed', 'unresolved'].includes(report.refinement.status);
  const skipLabel = report.refinement.status === 'unsupported' ? 'refinementUnsupported'
    : report.refinement.status === 'disabled' ? 'refinementDisabled' : 'refinementNotNeeded';
  const refinement = report.browserEdition ? t(`browser.${refined ? 'reviewDone' : report.refinement.status === 'skipped' ? 'reviewOff' : 'reviewKept'}`) : refined ? label('refinementApplied', report.refinement.fixesApplied)
    : t(`workspace.${keptOriginal ? 'refinementKeptOriginal' : skipLabel}`);
  const learning = learningState.status === 'saved'
    ? label('memoryLearned', learningState.savedCount)
    : t(`workspace.${['queued', 'running'].includes(learningState.status) ? 'memoryLearningQueued'
      : learningState.status === 'unavailable' ? 'memoryLearningUnavailable' : 'memoryNoNewLesson'}`);

  return (
    <details ref={detailsRef} data-compact={compact} className="generation-report group mb-2 rounded-xl border border-slate-200 bg-white text-slate-700 dark:border-brand-500/25 dark:from-brand-950/50 dark:via-slate-900 dark:to-violet-950/30 dark:text-slate-200">
      <summary aria-label={detailsLabel} title={detailsLabel} className="flex min-h-10 cursor-pointer list-none flex-wrap items-center gap-x-4 gap-y-2 rounded-xl px-3 py-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 [&::-webkit-details-marker]:hidden">
        {compact && attentionLabel && (
          <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-300">
            <AlertTriangle size={14} aria-hidden="true" />
            <span className="sr-only">{attentionLabel}</span>
          </span>
        )}
        <span className="report-memory inline-flex items-center gap-1.5 font-semibold text-brand-700 dark:text-brand-300"><BrainCircuit size={15} aria-hidden="true" />{memory}</span>
        <span className="report-quality inline-flex items-center gap-1.5"><Sparkles size={14} aria-hidden="true" />{edited ? t('workspace.qualityEditedShort') : refinement}{report.qualityStatus === 'needs_attention' && ` · ${t('workspace.qualityNeedsAttentionShort')}`}</span>
        <span className="ml-auto inline-flex items-center gap-1.5 tabular-nums text-slate-500 dark:text-slate-400"><Clock3 size={13} aria-hidden="true" />{formatGenerationDuration(report.durationMs)}</span>
        <span className="report-label text-[11px] font-medium text-brand-600 underline decoration-brand-200 underline-offset-4 dark:text-brand-300">{t('workspace.generationDetails')}</span>
        <ChevronDown className="report-chevron h-3 w-3 shrink-0 transition-transform group-open:rotate-180" />
      </summary>
      <div className="report-content border-t border-brand-100/80 px-4 pb-4 pt-3 text-xs dark:border-brand-500/20">
        {compact && <div className="mb-3 flex flex-wrap gap-x-4 gap-y-2 text-brand-700 dark:text-brand-300"><span>{memory}</span><span>{edited ? t('workspace.qualityEditedShort') : refinement}</span></div>}
        {edited && <p className="mb-2 text-slate-600 dark:text-slate-300">{t('workspace.qualityEdited')}</p>}
        {report.browserEdition && report.refinement.reason && <p className="mb-2 text-amber-700 dark:text-amber-300">{report.refinement.reason}</p>}
        {report.qualityStatus === 'needs_attention' && (
          <p className="mb-2 text-amber-700 dark:text-amber-300">{t('workspace.qualityNeedsAttention')}</p>
        )}
        {!report.browserEdition && report.qualityStatus === 'unverified' && (
          <p className="mb-2 text-amber-700 dark:text-amber-300">{t('workspace.qualityUnverified')}</p>
        )}
        <p className="flex items-center gap-1.5"><Check size={14} aria-hidden="true" />{report.browserEdition ? t('browser.scope') : learning}</p>
        <p className="mt-1.5 leading-relaxed text-slate-500 dark:text-slate-400">{t(report.browserEdition ? 'browser.memory' : 'workspace.memoryLearningHint')}</p>
        {!edited && report.beforeScore !== undefined && report.afterScore !== undefined && (
          <p className="mt-2 tabular-nums">{t('workspace.visualQualityScore')}: {report.beforeScore.toFixed(1)} → {report.afterScore.toFixed(1)} / 10</p>
        )}
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
          {Object.entries(report.timings).map(([stage, ms]) => (
            <div key={stage} className="flex justify-between gap-2"><dt className="text-slate-500 dark:text-slate-400">{t(report.browserEdition ? `browser.${stage === 'structure' ? 'planStage' : stage === 'refining' ? 'reviewStage' : 'layoutStage'}` : `landing.${stageKeys[stage]}`)}</dt><dd className="tabular-nums">{formatGenerationDuration(ms!)}</dd></div>
          ))}
        </dl>
      </div>
    </details>
  );
}
