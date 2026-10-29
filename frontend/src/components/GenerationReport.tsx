import { Activity, AlertTriangle, Check, ChevronDown, Clock3, PencilLine, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { apiV1Url, getStoredAuthToken } from '../services/httpClient';
import { formatGenerationDuration, getGenerationReviewState, hasCurrentVisualScores, type GenerationReport as Report } from '../utils/generationReport';

const stageKeys: Record<string, string> = {
  memory: 'workflowMemory', structure: 'workflowExtract', styling: 'workflowIntent',
  layout: 'workflowLayout', render: 'workflowRender', verification: 'workflowVerification',
  refining: 'workflowRefining', final_verification: 'workflowFinalVerification', learning: 'workflowLearning',
};

export function GenerationReport({ report, t, compact = false, compactLabel }: { report: Report; t: (key: string) => string; compact?: boolean; compactLabel?: string }) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (!compact) return;
    const details = detailsRef.current;
    const fitToViewport = () => {
      if (!details?.open) return;
      const panel = details.querySelector<HTMLElement>(':scope > .report-content');
      if (!panel) return;
      const viewport = window.visualViewport;
      const bottom = viewport ? Math.min(window.innerHeight, viewport.height + viewport.offsetTop) : window.innerHeight;
      panel.style.maxHeight = `${Math.max(0, Math.min(480, bottom - panel.getBoundingClientRect().top - 12))}px`;
    };
    details?.addEventListener('toggle', fitToViewport);
    window.addEventListener('resize', fitToViewport);
    window.visualViewport?.addEventListener('resize', fitToViewport);
    window.visualViewport?.addEventListener('scroll', fitToViewport);
    fitToViewport();
    return () => {
      details?.removeEventListener('toggle', fitToViewport);
      window.removeEventListener('resize', fitToViewport);
      window.visualViewport?.removeEventListener('resize', fitToViewport);
      window.visualViewport?.removeEventListener('scroll', fitToViewport);
    };
  }, [compact]);
  useEffect(() => {
    if (!compact) return;
    const closeOutside = (event: Event) => {
      if (detailsRef.current && !detailsRef.current.contains(event.target as Node)) detailsRef.current.open = false;
    };
    const closeEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && detailsRef.current?.open) {
        event.preventDefault();
        event.stopPropagation();
        detailsRef.current.open = false;
        detailsRef.current.querySelector('summary')?.focus();
      }
    };
    document.addEventListener('pointerdown', closeOutside);
    document.addEventListener('focusin', closeOutside);
    document.addEventListener('keydown', closeEscape);
    return () => {
      document.removeEventListener('pointerdown', closeOutside);
      document.removeEventListener('focusin', closeOutside);
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
  const state = getGenerationReviewState(report);
  const statusLabel = t(`workspace.reportState_${state}`);
  const warning = ['needs_attention', 'unverified', 'kept_original'].includes(state);
  const positive = ['reviewed', 'refined', 'not_needed'].includes(state);
  const edited = state === 'edited';
  const note = edited ? t('workspace.reportEditedNote') : state === 'needs_attention' ? t('workspace.reportAttentionNote')
    : state === 'unverified' ? t(report.browserEdition ? 'workspace.reportContentUnavailable' : 'workspace.reportVisualUnavailable') : null;
  const memory = report.memory.status === 'used' ? label('memoryUsed', report.memory.retrievedCount)
    : t(`workspace.${report.memory.status === 'unavailable' ? 'reportMemoryUnavailable' : report.memory.status === 'disabled' ? 'reportMemoryDisabled' : 'memoryEmpty'}`);
  const refined = report.refinement.status === 'completed';
  const refinement = refined ? (report.browserEdition
    ? t(edited ? 'workspace.reportReviewedOriginal' : 'workspace.reportCompleted')
    : label('reportFixCount', report.refinement.fixesApplied))
    : t(`workspace.reportState_${['failed', 'unresolved'].includes(report.refinement.status) ? 'kept_original'
      : report.browserEdition ? 'not_reviewed' : report.refinement.status === 'unsupported' ? 'unsupported'
        : report.refinement.status === 'disabled' ? 'disabled' : report.refinement.status === 'skipped' ? 'not_needed' : 'unverified'}`);
  const showLearning = !report.browserEdition && ['saved', 'queued', 'running', 'unavailable'].includes(learningState.status);
  const learning = learningState.status === 'saved' ? label('reportLearnedCount', learningState.savedCount)
    : t(['queued', 'running'].includes(learningState.status) ? 'workspace.reportLearning' : 'workspace.reportLearningUnavailable');
  const timings = Object.entries(report.timings).filter(([, ms]) => typeof ms === 'number' && Number.isFinite(ms) && ms >= 0);
  const stageLabel = (stage: string) => {
    if (stage === 'memory') return t('workspace.reportMemory');
    if (report.browserEdition && ['structure', 'refining', 'layout'].includes(stage)) {
      return t(`browser.${stage === 'structure' ? 'planStage' : stage === 'refining' ? 'reviewStage' : 'layoutStage'}`);
    }
    return stageKeys[stage] ? t(`landing.${stageKeys[stage]}`) : t('workspace.reportOtherStage');
  };
  const title = t('workspace.reportTitle');
  const duration = formatGenerationDuration(report.durationMs);
  const close = () => {
    if (detailsRef.current) detailsRef.current.open = false;
    detailsRef.current?.querySelector('summary')?.focus();
  };

  return (
    <details ref={detailsRef} data-compact={compact} className="generation-report">
      <summary aria-label={`${title} · ${statusLabel} · ${duration}`} title={`${title} · ${statusLabel}`}>
        {compact && warning && <span className="report-attention-dot" aria-hidden="true" />}
        {compactLabel ? <Activity size={14} aria-hidden="true" /> : <><Clock3 size={14} aria-hidden="true" /><span className="report-duration">{duration}</span></>}
        <span className="report-label">{compactLabel || title}</span><ChevronDown className="report-chevron" size={13} aria-hidden="true" />
      </summary>
      <section className="report-content" aria-label={title}>
        <header className="report-heading">
          <h3>{title}</h3>
          <span className="report-total" title={t('workspace.reportTotalTime')}>{duration}</span>
          {compact && <button type="button" className="report-close" onClick={close} aria-label={t('workspace.reportClose')}><X size={15} aria-hidden="true" /></button>}
        </header>
        <div className="report-body">
          <div className="report-status" data-tone={warning ? 'attention' : positive ? 'positive' : 'neutral'}>
            {edited ? <PencilLine size={14} aria-hidden="true" /> : warning ? <AlertTriangle size={14} aria-hidden="true" /> : positive ? <Check size={14} aria-hidden="true" /> : null}
            <span>{statusLabel}</span>
          </div>
          {note && <p className="report-note">{note}</p>}
          {hasCurrentVisualScores(report) && <div className="report-score"><span>{t('workspace.reportScore')}</span>
            <strong>{report.beforeScore!.toFixed(1)} <span>→</span> {report.afterScore!.toFixed(1)} <small>/ 10</small></strong></div>}
          {timings.length > 0 && <section className="report-timing-section" aria-label={t('workspace.reportTimings')}>
            <h4>{t('workspace.reportTimings')}</h4>
            <dl className="report-timings">
              {timings.map(([stage, ms]) => <div key={stage}><dt>{stageLabel(stage)}</dt><dd>{formatGenerationDuration(ms!)}</dd></div>)}
            </dl>
          </section>}
          <details className="report-more">
            <summary>{t('workspace.reportMore')}<ChevronDown size={13} aria-hidden="true" /></summary>
            <div className="report-more-content">
              <dl className="report-metadata">
                <div><dt>{t(report.browserEdition ? 'workspace.reportContentReview' : 'workspace.reportRefinement')}</dt><dd>{refinement}</dd></div>
                {!report.browserEdition && <div><dt>{t('workspace.reportMemory')}</dt><dd>{memory}</dd></div>}
                {showLearning && <div><dt>{t('workspace.reportLearningLabel')}</dt><dd>{learning}</dd></div>}
              </dl>
              {report.browserEdition && <p className="report-scope">{t('workspace.reportBrowserScope')}</p>}
              {!report.browserEdition && hasCurrentVisualScores(report) && <p className="report-scope">{t('workspace.reportScoreScope')}</p>}
              {report.refinement.reason && <p className="report-reason">{report.refinement.reason}</p>}
            </div>
          </details>
        </div>
      </section>
    </details>
  );
}
