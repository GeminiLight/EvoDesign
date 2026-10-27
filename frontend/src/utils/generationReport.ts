import type { StreamStage } from '../types/api';

export interface GenerationReport {
  browserEdition?: boolean;
  memory: { status: string; retrievedCount: number };
  refinement: { status: string; fixesApplied: number };
  learning: { status: string; savedCount: number; jobId?: string };
  qualityStatus?: string;
  beforeScore?: number;
  afterScore?: number;
  timings: Partial<Record<StreamStage, number>>;
  durationMs: number;
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}
function number(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : undefined;
}
function status(value: unknown): string {
  return typeof value === 'string' ? value : 'unavailable';
}

/** Older snapshots intentionally have no report. Reject malformed metrics. */
export function parseGenerationReport(metrics: unknown): GenerationReport | undefined {
  const report = record(record(metrics).generation);
  const durationMs = number(report.total_duration_ms);
  if (durationMs === undefined) return undefined;
  const memory = record(report.memory);
  const refinement = record(report.refinement);
  const learning = record(report.learning);
  const timings: GenerationReport['timings'] = {};
  const rawTimings = record(report.timings_ms);
  const stages: StreamStage[] = ['memory', 'structure', 'styling', 'layout', 'render', 'verification', 'refining', 'final_verification', 'learning'];
  for (const stage of stages) {
    const value = number(rawTimings[stage]);
    if (value !== undefined) timings[stage] = value;
  }
  return {
    memory: { status: status(memory.status), retrievedCount: number(memory.retrieved_count) ?? 0 },
    refinement: { status: status(refinement.status), fixesApplied: number(refinement.fixes_applied) ?? 0 },
    learning: { status: status(learning.status), savedCount: number(learning.saved_count) ?? 0,
      jobId: typeof learning.job_id === 'string' ? learning.job_id : undefined },
    qualityStatus: typeof report.quality_status === 'string' ? report.quality_status : undefined,
    beforeScore: number(record(report.before).score),
    afterScore: number(record(report.after).score),
    timings, durationMs,
  };
}

export function formatGenerationDuration(ms: number): string {
  const seconds = Math.round(ms / 1000);
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}
