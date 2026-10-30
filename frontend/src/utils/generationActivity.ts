import type { GenerationProgress, StreamStageExtended } from '../types/app';
import type { GenerationReport } from './generationReport';

export type ActivityStage = { key: StreamStageExtended; state: 'pending' | 'running' | 'done' | 'skipped' | 'interrupted'; durationMs?: number };
export const ACTIVITY_STAGES: StreamStageExtended[] = ['memory', 'structure', 'styling', 'layout', 'render', 'verification', 'refining', 'final_verification', 'learning'];

export function generationActivityStages(progress: GenerationProgress | null, report: GenerationReport | undefined,
  running: boolean, browser: boolean, now: number): ActivityStage[] {
  if (!running && report) return (browser ? ['memory', 'structure', 'refining', 'styling', 'layout', 'render', 'verification', 'final_verification', 'learning'] as StreamStageExtended[] : ACTIVITY_STAGES).flatMap(key => {
    const durationMs = report.timings[key];
    return typeof durationMs === 'number' && Number.isFinite(durationMs) && durationMs >= 0
      ? [{ key, state: (key === 'refining' && ['failed', 'unresolved'].includes(report.refinement.status)
        || ['verification', 'final_verification'].includes(key) && report.qualityStatus === 'needs_attention' ? 'interrupted' : 'done') as ActivityStage['state'], durationMs }] : [];
  });
  if (!progress) return [];
  const observed = new Set([...progress.completedStages, progress.currentStage]);
  const keys = browser ? ['structure', ...(progress.totalStages === 2 ? [] : ['refining']), 'layout'] as StreamStageExtended[]
    : ACTIVITY_STAGES.filter(key => !['refining', 'final_verification', 'learning'].includes(key) || observed.has(key)
      || key === 'refining' && progress.refinerSkipped);
  return keys.map(key => {
    const completed = progress.completedStages.includes(key);
    const current = progress.currentStage === key && !completed;
    const skipped = key === 'refining' && progress.refinerSkipped && !observed.has('refining');
    const measured = progress.stageDurations?.[key];
    return { key, state: skipped ? 'skipped' : completed ? 'done' : current ? running ? 'running' : 'interrupted' : 'pending',
      durationMs: typeof measured === 'number' && Number.isFinite(measured) && measured >= 0 ? measured
        : current && running && progress.stageStartedAt ? Math.max(0, now - progress.stageStartedAt) : undefined };
  });
}

export function activityCanAutoClose(running: boolean, failed: boolean, automatic: boolean): boolean {
  return !running && !failed && automatic;
}
