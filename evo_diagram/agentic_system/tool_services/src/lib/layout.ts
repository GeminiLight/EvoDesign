import dagre from 'dagre';
import * as d3 from 'd3-force';

export type LayoutNode = {
  id: string;
  label?: string;
  width?: number;
  height?: number;
  x?: number;
  y?: number;
};

export type LayoutEdge = {
  source: string;
  target: string;
};

export type LayoutInput = {
  layout?: string;
  nodes?: LayoutNode[];
  edges?: LayoutEdge[];
  rankdir?: string;
  nodesep?: number;
  ranksep?: number;
};

export type LayoutResult = {
  positions: Record<string, [number, number]>;
};

export class LayoutInputError extends Error {}

export const SUPPORTED_LAYOUTS = new Set(['dagre', 'force', 'circular']);
export const SUPPORTED_RANKDIRS = new Set(['TB', 'BT', 'LR', 'RL']);
export const MAX_LAYOUT_NODES = 500;
export const MAX_LAYOUT_EDGES = 1000;
export const MAX_LAYOUT_DIMENSION = 10000;
export const MAX_LAYOUT_SPACING = 5000;
export const MAX_LAYOUT_LABEL_LENGTH = 2000;

function normalizeLayout(layout: unknown): string {
  if (layout !== undefined && layout !== null && typeof layout !== 'string') {
    throw new LayoutInputError('layout must be a string');
  }
  const value = (layout ?? 'dagre').toLowerCase();
  if (!SUPPORTED_LAYOUTS.has(value)) {
    throw new LayoutInputError(
      `Unknown layout '${layout}'. Use one of: ${Array.from(SUPPORTED_LAYOUTS).join(', ')}.`,
    );
  }
  return value;
}

function readBoundedNumber(
  value: unknown,
  fallback: number,
  field: string,
  min: number,
  max: number,
): number {
  const parsed = value === undefined || value === null ? fallback : value;
  if (typeof parsed !== 'number' || !Number.isFinite(parsed)) {
    throw new LayoutInputError(`${field} must be a finite number`);
  }
  if (parsed < min || parsed > max) {
    throw new LayoutInputError(`${field} must be between ${min} and ${max}`);
  }
  return parsed;
}

function readOptionalBoundedNumber(
  value: unknown,
  field: string,
  min: number,
  max: number,
): number | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new LayoutInputError(`${field} must be a finite number`);
  }
  if (value < min || value > max) {
    throw new LayoutInputError(`${field} must be between ${min} and ${max}`);
  }
  return value;
}

function readOptionalCoordinate(value: unknown, field: string): number | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new LayoutInputError(`${field} must be a finite number`);
  }
  return value;
}

function normalizeRankdir(value: unknown): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== 'string') {
    throw new LayoutInputError('rankdir must be a string');
  }
  const rankdir = value.toUpperCase();
  if (!SUPPORTED_RANKDIRS.has(rankdir)) {
    throw new LayoutInputError(
      `rankdir must be one of: ${Array.from(SUPPORTED_RANKDIRS).join(', ')}.`,
    );
  }
  return rankdir;
}

function readString(value: unknown, field: string): string {
  if (typeof value !== 'string' || value.trim() === '') {
    throw new LayoutInputError(`${field} must be a non-empty string`);
  }
  return value;
}

function readOptionalLabel(value: unknown, field: string): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== 'string') {
    throw new LayoutInputError(`${field} must be a string`);
  }
  if (value.length > MAX_LAYOUT_LABEL_LENGTH) {
    throw new LayoutInputError(`${field} must be at most ${MAX_LAYOUT_LABEL_LENGTH} characters`);
  }
  return value;
}

function parseNodes(value: unknown): LayoutNode[] {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) {
    throw new LayoutInputError('nodes must be an array');
  }
  if (value.length > MAX_LAYOUT_NODES) {
    throw new LayoutInputError(`nodes must contain at most ${MAX_LAYOUT_NODES} items`);
  }

  const seen = new Set<string>();
  return value.map((raw, index) => {
    if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
      throw new LayoutInputError(`nodes[${index}] must be a JSON object`);
    }
    const node = raw as Record<string, unknown>;
    const id = readString(node.id, `nodes[${index}].id`);
    if (seen.has(id)) {
      throw new LayoutInputError(`Duplicate node id: ${id}`);
    }
    seen.add(id);
    return {
      id,
      label: readOptionalLabel(node.label, `nodes[${index}].label`),
      width: readOptionalBoundedNumber(
        node.width,
        `nodes[${index}].width`,
        1,
        MAX_LAYOUT_DIMENSION,
      ),
      height: readOptionalBoundedNumber(
        node.height,
        `nodes[${index}].height`,
        1,
        MAX_LAYOUT_DIMENSION,
      ),
      x: readOptionalCoordinate(node.x, `nodes[${index}].x`),
      y: readOptionalCoordinate(node.y, `nodes[${index}].y`),
    };
  });
}

function parseEdges(value: unknown, nodeIds: Set<string>): LayoutEdge[] {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) {
    throw new LayoutInputError('edges must be an array');
  }
  if (value.length > MAX_LAYOUT_EDGES) {
    throw new LayoutInputError(`edges must contain at most ${MAX_LAYOUT_EDGES} items`);
  }

  return value.map((raw, index) => {
    if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
      throw new LayoutInputError(`edges[${index}] must be a JSON object`);
    }
    const edge = raw as Record<string, unknown>;
    const source = readString(edge.source, `edges[${index}].source`);
    const target = readString(edge.target, `edges[${index}].target`);
    if (!nodeIds.has(source)) {
      throw new LayoutInputError(`edges[${index}].source references unknown node '${source}'`);
    }
    if (!nodeIds.has(target)) {
      throw new LayoutInputError(`edges[${index}].target references unknown node '${target}'`);
    }
    return { source, target };
  });
}

export function parseLayoutRequest(value: unknown): LayoutInput {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new LayoutInputError('Request body must be a JSON object');
  }
  const body = value as Record<string, unknown>;
  const nodes = parseNodes(body.nodes);
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = parseEdges(body.edges, nodeIds);

  return {
    layout: normalizeLayout(body.layout),
    nodes,
    edges,
    rankdir: normalizeRankdir(body.rankdir),
    nodesep: readBoundedNumber(body.nodesep, 50, 'nodesep', 1, MAX_LAYOUT_SPACING),
    ranksep: readBoundedNumber(body.ranksep, 50, 'ranksep', 1, MAX_LAYOUT_SPACING),
  };
}

function computeDagre(input: Required<Pick<LayoutInput, 'nodes' | 'edges' | 'rankdir' | 'nodesep' | 'ranksep'>>): LayoutResult {
  const graph = new dagre.graphlib.Graph();
  graph.setGraph({
    rankdir: input.rankdir,
    nodesep: input.nodesep,
    ranksep: input.ranksep,
  });
  graph.setDefaultEdgeLabel(() => ({}));

  input.nodes.forEach((node) => graph.setNode(node.id, {
    label: node.label || node.id,
    width: node.width ?? 100,
    height: node.height ?? 40,
  }));
  input.edges.forEach((edge) => graph.setEdge(edge.source, edge.target));

  dagre.layout(graph);

  const positions: Record<string, [number, number]> = {};
  graph.nodes().forEach((id: string) => {
    const node = graph.node(id);
    if (node) {
      positions[id] = [node.x, node.y];
    }
  });
  return { positions };
}

function computeForce(nodes: LayoutNode[], edges: LayoutEdge[]): LayoutResult {
  const d3nodes = nodes.map((node) => ({
    id: node.id,
    x: node.x,
    y: node.y,
  }));
  const d3edges = edges.map((edge) => ({
    source: edge.source,
    target: edge.target,
  }));

  const simulation = d3.forceSimulation(d3nodes)
    .force('charge', d3.forceManyBody().strength(-300))
    .force('link', d3.forceLink(d3edges).id((node: any) => node.id).distance(150))
    .force('center', d3.forceCenter(0, 0))
    .stop();

  for (let i = 0; i < 300; i += 1) simulation.tick();

  const positions: Record<string, [number, number]> = {};
  d3nodes.forEach((node) => {
    positions[node.id] = [node.x || 0, node.y || 0];
  });
  return { positions };
}

function computeCircular(nodes: LayoutNode[]): LayoutResult {
  const positions: Record<string, [number, number]> = {};
  const count = nodes.length;
  if (count === 0) return { positions };

  const radius = Math.max(300, count * 30);
  nodes.forEach((node, index) => {
    const angle = (index / count) * Math.PI * 2;
    positions[node.id] = [Math.cos(angle) * radius, Math.sin(angle) * radius];
  });
  return { positions };
}

export function computeLayoutPositions(input: LayoutInput): LayoutResult {
  const layout = normalizeLayout(input.layout);
  const nodes = input.nodes || [];
  const edges = input.edges || [];
  const rankdir = normalizeRankdir(input.rankdir) || 'TB';
  const nodesep = readBoundedNumber(input.nodesep, 50, 'nodesep', 1, MAX_LAYOUT_SPACING);
  const ranksep = readBoundedNumber(input.ranksep, 50, 'ranksep', 1, MAX_LAYOUT_SPACING);

  if (layout === 'dagre') {
    return computeDagre({ nodes, edges, rankdir, nodesep, ranksep });
  }
  if (layout === 'force') {
    return computeForce(nodes, edges);
  }
  if (layout === 'circular') {
    return computeCircular(nodes);
  }
  throw new LayoutInputError(`Unsupported layout '${layout}'`);
}
