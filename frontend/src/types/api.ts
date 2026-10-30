import type {
  StreamErrorStage,
  StreamRefineStatus,
  StreamStage,
} from '../contracts/streamEvents';
import type {
  BackendDiagramLocalEditRequest,
  BackendDiagramLocalEditResponse,
} from '../contracts/backendApi.generated';

export type {
  StreamErrorStage,
  StreamRefineStatus,
  StreamStage,
} from '../contracts/streamEvents';

export type {
  BackendDiagramGenerateRequest,
  BackendDiagramGenerateResponse,
  BackendDiagramLocalEditRequest,
  BackendDiagramLocalEditResponse,
  BackendDnaAnalyzeResponse,
  BackendDnaRuleSchema,
  BackendDnaRulesPayload,
  BackendProjectCreateRequest,
  BackendProjectCreateResponse,
  BackendProjectListItem,
  BackendProjectListResponse,
  BackendProjectSnapshotItem,
  BackendProjectSnapshotListResponse,
  BackendSchemaSyncRequest,
  BackendSchemaSyncResponse,
} from '../contracts/backendApi.generated';

export type ProviderType = 'openai' | 'anthropic' | 'azure' | 'qwen' | 'ollama' | 'custom';

export type DiagramType =
  | 'flow'
  | 'architecture'
  | 'sequence'
  | 'er'
  | 'mindmap'
  | 'network'
  | 'automated';

export type StylePreset = 'neutral' | 'playful' | 'technical' | 'minimal';
export type CanvasLibrary = 'excalidraw' | 'tldraw';
export type SchemaEditor = CanvasLibrary | 'manual';

export interface LLMProviderConfig {
  id: string;
  provider: ProviderType;
  label: string;
  model: string;
  temperature: number;
  maxTokens: number;
  apiKey?: string;
  baseUrl?: string;
  useAccessPassword?: boolean;
  accessPassword?: string;
}

export interface DiagramConstraint {
  maxNodes?: number;
  maxConnections?: number;
  preferOrthogonal?: boolean;
  includeLegend?: boolean;
  autoLayout?: boolean;
}

export interface UploadedAsset {
  id: string;
  name: string;
  url?: string;
  sizeKB?: number;
  type: 'image' | 'dataset' | 'sketch';
}

export interface DiagramRequest {
  useIcons?: boolean;
  id: string;
  prompt: string;
  diagramType: DiagramType;
  style: StylePreset;
  refinementLevel: 'draft' | 'refine';
  constraints: DiagramConstraint;
  llmConfigId: string;
  assets?: UploadedAsset[];
  lockedNodes?: string[];
  metadata?: Record<string, string>;
}

export interface DiagramResponse {
  proposalId?: string;
  generationReport?: import('../utils/generationReport').GenerationReport;
  diagramId: string;
  requestId: string;
  projectId?: string;
  snapshotId?: string;
  projectVersion?: number;
  excalidrawPayload: string;
  tldrawSnapshot?: Record<string, unknown>;
  rawSchemaBlob?: Record<string, unknown>;
  summary: string;
  previewImage: string;
  thumbnailUrl?: string;
  warnings?: string[];
  generatedAt: string;
  persistError?: boolean;
}

export interface HistoryItem extends DiagramResponse {
  title: string;
  diagramType: DiagramType;
  style: StylePreset;
}

export interface ProjectSnapshotItem {
  is_checkpoint?: boolean;
  generation_report?: import('../utils/generationReport').GenerationReport;
  project_version?: number;
  snapshot_id: string;
  project_id: string;
  parent_id?: string | null;
  schema_blob: Record<string, unknown>;
  edit_source: string;
  thought_trace?: string | null;
  metrics_scores?: Record<string, unknown> | null;
  timestamp: string;
}

export interface ProjectSnapshotResponse {
  project_version?: number;
  snapshots: ProjectSnapshotItem[];
  page: number;
  page_size: number;
  total: number;
}

export interface SchemaSyncPayload {
  project_id: string;
  schema_patch: Record<string, unknown>;
  editor?: SchemaEditor;
  base_snapshot_id?: string | null;
  create_snapshot?: boolean;
  version?: number | null;
}

export interface SchemaSyncResult {
  project_id: string;
  snapshot_id: string;
  latest_schema: Record<string, unknown>;
  edit_source: string;
  version: number;
}

export interface AccessPasswordPayload {
  password: string;
  enable: boolean;
}

export interface DiagramService {
  generateDiagram(request: DiagramRequest): Promise<DiagramResponse>;
  editDiagramLocal(request: DiagramLocalEditRequest): Promise<DiagramLocalEditResponse>;
}

// SSE streaming types

export interface StreamStageStartEvent {
  stage: StreamStage;
  stage_index: number;
  total_stages: number;
  message: string;
}

export interface StreamStageCompleteEvent extends StreamStageStartEvent {
  duration_ms: number;
}

export type StreamStageEvent = StreamStageStartEvent | StreamStageCompleteEvent;

export interface StreamRefineCompleteEvent {
  fixes_applied: number;
  status: StreamRefineStatus;
  message: string;
}

export interface StreamRefineErrorEvent {
  message: string;
  detail: string;
}

export interface StreamResultEvent {
  proposal_id?: string;
  version?: number | null;
  request_id: string;
  project_id: string | null;
  snapshot_id: string | null;
  schema_blob: Record<string, unknown>;
  thought_trace?: Record<string, unknown> | null;
  metrics_scores?: Record<string, unknown> | null;
  summary: string;
  thumbnail_url?: string | null;
  persist_error?: boolean;
  persist_error_message?: string;
}

export interface StreamErrorEvent {
  stage: StreamErrorStage;
  message: string;
  detail: string;
}

export type DiagramLocalEditRequest = BackendDiagramLocalEditRequest;

export type DiagramLocalEditResponse = BackendDiagramLocalEditResponse;
