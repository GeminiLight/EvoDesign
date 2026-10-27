import { BROWSER_MODE } from '../services/browser/runtime';
import type { DiagramType, LLMProviderConfig, DiagramRequest } from '../types/api';
import type { MoreDiagramOption } from '../types/app';

export const createId = (prefix: string) => `${prefix}_${Math.random().toString(36).slice(2, 10)}`;

export const diagramOptions: Array<{ value: DiagramType; label: string }> = [
  { value: 'automated', label: 'Automated' },
  { value: 'flow', label: 'Flowchart' },
  { value: 'sequence', label: 'Sequence' },
  { value: 'er', label: 'ER Diagram' },
  { value: 'mindmap', label: 'Mind Map' },
  { value: 'network', label: 'Network Topology' },
];

export const moreDiagramOptions: MoreDiagramOption[] = [
  { id: 'concept-map', label: 'Concept Map', diagramType: 'automated' },
  { id: 'data-flow-diagram', label: 'Data Flow Diagram', diagramType: 'flow' },
  { id: 'entity-relationship', label: 'Entity Relationship', diagramType: 'er' },
  { id: 'fishbone-diagram', label: 'Fishbone Diagram', diagramType: 'automated' },
  { id: 'funnel-chart', label: 'Funnel Chart', diagramType: 'automated' },
  { id: 'gantt-chart', label: 'Gantt Chart', diagramType: 'automated' },
  { id: 'hybrid-diagram-matrixchart', label: 'Hybrid Diagram MatrixChart', diagramType: 'automated' },
  { id: 'orgchart', label: 'OrgChart', diagramType: 'automated' },
  { id: 'pyramid-chart', label: 'Pyramid Chart', diagramType: 'automated' },
  { id: 'sequence-diagram', label: 'Sequence Diagram', diagramType: 'sequence' },
  { id: 'state-diagram', label: 'State Diagram', diagramType: 'sequence' },
  { id: 'swimlane-diagram', label: 'Swimlane Diagram', diagramType: 'flow' },
  { id: 'swot-analysis', label: 'SWOT Analysis', diagramType: 'automated' },
  { id: 'timeline', label: 'Timeline', diagramType: 'automated' },
  { id: 'tree-diagram', label: 'Tree Diagram', diagramType: 'mindmap' },
  { id: 'venn-diagram', label: 'Venn Diagram', diagramType: 'automated' },
];

// The generation API resolves credentials and model selection on the server.
// Do not offer client-side model choices that the API does not accept.
export const defaultConfigs: LLMProviderConfig[] = [
  { id: 'provider_server', provider: 'custom', label: BROWSER_MODE ? 'Your model' : 'Server-configured model', model: 'server', temperature: 0, maxTokens: 16384 },
];

export const initialRequest: DiagramRequest = {
  id: createId('request'),
  prompt: '',
  diagramType: 'automated',
  style: 'technical',
  refinementLevel: 'draft',
  constraints: {
    maxNodes: 18,
    maxConnections: 24,
    includeLegend: true,
    preferOrthogonal: true,
    autoLayout: true,
  },
  llmConfigId: defaultConfigs[0].id,
};

// ---- Shared pill/diagram-type mappings ----

/** Map a pill ID to the corresponding DiagramType */
export const pillIdToDiagramType: Record<string, DiagramType> = {
  adaptive: 'automated',
  flow: 'flow',
  architecture: 'architecture',
  sequence: 'sequence',
  mindmap: 'mindmap',
  entity: 'er',
  state: 'network',
  gantt: 'flow',
  class: 'architecture',
};

/** Reverse map: DiagramType → default pill ID */
export const diagramTypeToPillId: Record<string, string> = {
  automated: 'adaptive',
  flow: 'flow',
  architecture: 'architecture',
  sequence: 'sequence',
  mindmap: 'mindmap',
  er: 'entity',
  network: 'state',
};

/** Get the localized label for a DiagramType. Requires a `t` function. */
export function getDiagramTypeLabel(diagramType: DiagramType, t: (key: string) => string): string {
  switch (diagramType) {
    case 'automated': return t('diagram.automated');
    case 'flow': return t('diagram.flowchart');
    case 'sequence': return t('diagram.sequence');
    case 'er': return t('diagram.er');
    case 'mindmap': return t('diagram.mindmap');
    case 'network': return t('diagram.network');
    case 'architecture': return t('home.pillArchitectureLabel');
    default: return t('diagram.automated');
  }
}
