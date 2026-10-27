import dagre from '@dagrejs/dagre';
import { routeAroundNodes } from './edgeRouting';

export type PlanNode = { id: string; label: string; shape: 'rectangle' | 'diamond' | 'ellipse'; color: string; icon?: string };
export type PlanEdge = { source: string; target: string; label: string; strokeStyle: 'solid' | 'dashed' };
export type DiagramPlan = { title: string; kind: 'graph' | 'sequence'; direction: 'TB' | 'LR'; nodes: PlanNode[]; edges: PlanEdge[] };
export type PlacedNode = PlanNode & { x: number; y: number; width: number; height: number; text: string };
export type PlacedEdge = PlanEdge & { points: { x: number; y: number }[] };
const colors = ['#e0e7ff', '#cffafe', '#ede9fe', '#dbeafe', '#ccfbf1'];
const text = (value: unknown, max: number) => typeof value === 'string' ? value.trim().slice(0, max) : '';
const object = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};

export function normalizePlan(value: unknown): DiagramPlan {
  const data = object(value);
  if (!Array.isArray(data.nodes) || !data.nodes.length || data.nodes.length > 60) throw new Error('A diagram must contain between 1 and 60 nodes.');
  if (!Array.isArray(data.edges) || data.edges.length > 120) throw new Error('A diagram supports up to 120 connections.');
  const ids = new Map<string, string>();
  const reserved = new Set(data.nodes.map(raw => text(object(raw).id, 80)));
  const nodes = data.nodes.map((raw, index): PlanNode => {
    const n = object(raw); const originalId = text(n.id, 80); const label = text(n.label, 240);
    if (!originalId || ids.has(originalId) || !label) throw new Error('The model returned duplicate/missing node identifiers or labels.');
    // Models sometimes use readable labels as IDs. Remap those consistently
    // instead of discarding a valid graph or asking for another paid call.
    let id = originalId;
    if (!/^[a-zA-Z0-9_-]+$/.test(id)) {
      id = `node_${index + 1}`;
      while (reserved.has(id)) id = `_${id}`;
      reserved.add(id);
    }
    ids.set(originalId, id);
    return { id, label, shape: n.shape === 'diamond' || n.shape === 'ellipse' ? n.shape : 'rectangle',
      color: typeof n.color === 'string' && /^#[0-9a-f]{6}$/i.test(n.color) ? n.color : colors[index % colors.length],
      icon: text(n.icon, 60) || undefined };
  });
  const edges = data.edges.map((raw): PlanEdge => {
    const e = object(raw); const source = text(e.source, 80); const target = text(e.target, 80);
    if (!ids.has(source) || !ids.has(target)) throw new Error('The model returned a connection to a missing node.');
    return { source: ids.get(source)!, target: ids.get(target)!, label: text(e.label, 160),
      strokeStyle: e.strokeStyle === 'dashed' ? 'dashed' : 'solid' };
  });
  return { title: text(data.title, 160) || 'Untitled diagram', kind: data.kind === 'sequence' ? 'sequence' : 'graph',
    direction: data.direction === 'LR' ? 'LR' : 'TB', nodes, edges };
}

export function preservesContent(before: DiagramPlan, after: DiagramPlan): boolean {
  const ids = new Set(after.nodes.map(n => n.id));
  if (before.kind === 'sequence') {
    // Added messages may be interleaved, but never reorder existing participants/messages.
    const participantOrder = after.nodes.filter(n => before.nodes.some(old => old.id === n.id)).map(n => n.id);
    if (participantOrder.join(':') !== before.nodes.map(n => n.id).join(':')) return false;
    let cursor = 0;
    for (const e of after.edges) {
      const expected = before.edges[cursor];
      if (expected && e.source === expected.source && e.target === expected.target) cursor++;
    }
    if (cursor !== before.edges.length) return false;
  }
  const counts = new Map<string, number>();
  for (const e of after.edges) { const k = `${e.source}:${e.target}`; counts.set(k, (counts.get(k) || 0) + 1); }
  for (const e of before.edges) {
    const k = `${e.source}:${e.target}`; if (!counts.get(k)) return false; counts.set(k, counts.get(k)! - 1);
  }
  return before.kind === after.kind && before.nodes.every(n => ids.has(n.id));
}

export function wrapLabel(label: string, max = 25): string {
  return label.split('\n').map(line => {
    const rows: string[] = []; let row = ''; let width = 0;
    for (const token of line.split(/(\s+|(?<=[\u2e80-\uffff])|(?=[\u2e80-\uffff]))/u).filter(Boolean)) {
      const size = Array.from(token).reduce((n, c) => n + (c.codePointAt(0)! > 255 ? 2 : 1), 0);
      if (width + size > max && row.trim()) { rows.push(row.trim()); row = ''; width = 0; }
      row += token; width += size;
    }
    if (row.trim()) rows.push(row.trim());
    return rows.join('\n');
  }).join('\n');
}

export function layoutPlan(plan: DiagramPlan, icons: boolean): { nodes: PlacedNode[]; edges: PlacedEdge[] } {
  const nodes: PlacedNode[] = plan.nodes.map(n => {
    const label = wrapLabel(n.label); const lines = label.split('\n');
    const units = Math.max(...lines.map(l => Array.from(l).reduce((v, c) => v + (c.codePointAt(0)! > 255 ? 2 : 1), 0)));
    const diamond = n.shape === 'diamond';
    return { ...n, text: label, x: 0, y: 0, width: Math.max(160, units * 8.5 + 52 + (icons && n.icon ? 38 : 0)) * (diamond ? 1.5 : 1),
      height: Math.max(72, lines.length * 24 + 32) * (diamond ? 1.5 : 1) };
  });
  if (plan.kind === 'sequence') {
    let x = 60;
    for (const n of nodes) { n.x = x; n.y = 70; x += n.width + 100; }
    const map = new Map(nodes.map(n => [n.id, n]));
    const top = Math.max(...nodes.map(n => n.height)) + 150;
    return { nodes, edges: plan.edges.map((e, i) => {
      const a = map.get(e.source)!; const b = map.get(e.target)!; const y = top + i * 95;
      const ax = a.x + a.width / 2; const bx = b.x + b.width / 2;
      return { ...e, points: ax === bx ? [{ x: ax, y }, { x: ax + 55, y }, { x: ax + 55, y: y + 34 }, { x: ax, y: y + 34 }] : [{ x: ax, y }, { x: bx, y }] };
    }) };
  }
  const graph = new dagre.graphlib.Graph({ multigraph: true });
  graph.setGraph({ rankdir: plan.direction, nodesep: 75, ranksep: 110, marginx: 60, marginy: 85 });
  graph.setDefaultEdgeLabel(() => ({}));
  nodes.forEach(n => graph.setNode(n.id, { width: n.width, height: n.height }));
  plan.edges.forEach((e, i) => graph.setEdge(e.source, e.target, { width: e.label ? Math.min(200, e.label.length * 8) : 0, height: e.label ? 40 : 0 }, String(i)));
  dagre.layout(graph);
  nodes.forEach(n => { const p = graph.node(n.id); n.x = p.x - n.width / 2; n.y = p.y - n.height / 2; });
  const byId = new Map(nodes.map(n => [n.id, n]));
  return { nodes, edges: plan.edges.map((e, i) => ({ ...e, points: routeAroundNodes(
    graph.edge({ v: e.source, w: e.target, name: String(i) }).points, byId.get(e.source)!, byId.get(e.target)!, nodes, plan.direction,
  ) })) };
}
