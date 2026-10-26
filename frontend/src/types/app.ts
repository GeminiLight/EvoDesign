import type { GenerationReport } from '../utils/generationReport';

export type InputMode = 'text' | 'file';
export type SubmitStatus = 'idle' | 'loading' | 'success' | 'error';
export type HistoryViewMode = 'recent' | 'project';

import type { CanvasLibrary, DiagramType, StreamRefineStatus, StreamStage } from './api';

export type RecentCanvasLibrary = CanvasLibrary;

export type RecentDiagram = {
  id: number | string;
  request_id: string;
  diagram_id: string;
  project_id?: string | null;
  snapshot_id?: string | null;
  project_version?: number;
  prompt: string;
  diagram_type: DiagramType;
  summary?: string | null;
  excalidraw_payload?: Record<string, unknown> | null;
  tldraw_snapshot?: Record<string, unknown> | null;
  canvas_library?: RecentCanvasLibrary | null;
  thumbnail_url?: string | null;
  created_at: string;
  updated_at?: string;
  snapshot_count?: number;
  generation_report?: GenerationReport;
};

export type MoreDiagramOption = {
  id: string;
  label: string;
  diagramType: DiagramType;
};

export type StreamStageExtended = StreamStage | 'refining';

export interface GenerationProgress {
  startedAt?: number;
  stageStartedAt?: number;
  currentStage: StreamStageExtended;
  stageIndex: number;
  totalStages: number;
  message: string;
  completedStages: StreamStageExtended[];
  refineComplete?: {
    fixes_applied: number;
    status: Exclude<StreamRefineStatus, 'skipped'>;
    message: string;
  };
  refinerError?: {
    message: string;
    detail: string;
  };
  refinerSkipped?: boolean;
  refinerSkippedMessage?: string;
}
