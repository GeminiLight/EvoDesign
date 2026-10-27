import dagre from '@dagrejs/dagre';

type Point = { x: number; y: number };
type Box = Point & { id: string; width: number; height: number };

/** Open interiors: touching a padded boundary is a valid routing lane. */
export function crossesBox(a: Point, b: Point, box: Box, padding = 0): boolean {
  const left = box.x - padding + 0.01; const right = box.x + box.width + padding - 0.01;
  const top = box.y - padding + 0.01; const bottom = box.y + box.height + padding - 0.01;
  let lo = 0; let hi = 1;
  for (const [origin, delta, min, max] of [[a.x, b.x - a.x, left, right], [a.y, b.y - a.y, top, bottom]]) {
    if (!delta) { if (origin < min || origin > max) return false; }
    else {
      const t1 = (min - origin) / delta; const t2 = (max - origin) / delta;
      lo = Math.max(lo, Math.min(t1, t2)); hi = Math.min(hi, Math.max(t1, t2));
      if (lo > hi) return false;
    }
  }
  return true;
}

function simplify(points: Point[]): Point[] {
  const out: Point[] = [];
  for (const p of points) {
    const a = out.at(-2); const b = out.at(-1);
    if (b?.x === p.x && b.y === p.y) continue;
    if (a && b && ((a.x === b.x && b.x === p.x) || (a.y === b.y && b.y === p.y))) out.pop();
    out.push(p);
  }
  return out;
}

/** Keep Dagre's route unless it crosses another node; detour only those edges. */
export function routeAroundNodes(points: Point[], source: Box, target: Box, nodes: Box[], direction: 'TB' | 'LR'): Point[] {
  if (source.id === target.id || !points.some((p, i) => i > 0 && nodes.some(n => n.id !== source.id && n.id !== target.id && crossesBox(points[i - 1], p, n, 8)))) return points;
  const horizontal = direction === 'LR';
  const forward = horizontal ? target.x >= source.x : target.y >= source.y;
  const sign = forward ? 1 : -1;
  const start = horizontal ? { x: source.x + (forward ? source.width : 0), y: source.y + source.height / 2 }
    : { x: source.x + source.width / 2, y: source.y + (forward ? source.height : 0) };
  const end = horizontal ? { x: target.x + (forward ? 0 : target.width), y: target.y + target.height / 2 }
    : { x: target.x + target.width / 2, y: target.y + (forward ? 0 : target.height) };
  const s = { x: start.x + (horizontal ? sign * 16 : 0), y: start.y + (horizontal ? 0 : sign * 16) };
  const t = { x: end.x - (horizontal ? sign * 16 : 0), y: end.y - (horizontal ? 0 : sign * 16) };
  const xs = [...new Set([s.x, t.x, (s.x + t.x) / 2, ...nodes.flatMap(n => [n.x - 12, n.x + n.width + 12])])].sort((a, b) => a - b);
  const ys = [...new Set([s.y, t.y, (s.y + t.y) / 2, ...nodes.flatMap(n => [n.y - 12, n.y + n.height + 12])])].sort((a, b) => a - b);
  const clear = (a: Point, b: Point) => !nodes.some(n => crossesBox(a, b, n, 12));
  const candidates = [
    ...xs.map(x => [s, { x, y: s.y }, { x, y: t.y }, t]),
    ...ys.map(y => [s, { x: s.x, y }, { x: t.x, y }, t]),
  ].filter(path => path.every((p, i) => !i || clear(path[i - 1], p)));
  const length = (path: Point[]) => path.reduce((sum, p, i) => sum + (i ? Math.abs(p.x - path[i - 1].x) + Math.abs(p.y - path[i - 1].y) : 0), 0);
  candidates.sort((a, b) => length(a) - length(b));
  if (candidates[0]) return simplify([start, ...candidates[0], end]);

  // Dense obstacles may need more than three segments. Search their boundary grid.
  const graph = new dagre.graphlib.Graph({ directed: false });
  const id = (x: number, y: number) => `${x}:${y}`;
  for (const x of xs) for (const y of ys) {
    const p = { x, y };
    if (clear(p, p)) graph.setNode(id(x, y), p);
  }
  xs.forEach((x, i) => ys.forEach((y, j) => {
    const p = { x, y }; const key = id(x, y);
    if (!graph.hasNode(key)) return;
    for (const q of [i ? { x: xs[i - 1], y } : null, j ? { x, y: ys[j - 1] } : null]) {
      if (q && graph.hasNode(id(q.x, q.y)) && clear(p, q)) graph.setEdge(key, id(q.x, q.y), Math.abs(p.x - q.x) + Math.abs(p.y - q.y));
    }
  }));
  const first = id(s.x, s.y); const last = id(t.x, t.y);
  const paths = dagre.graphlib.alg.dijkstra(graph, first, edge => graph.edge(edge) as number, node => graph.nodeEdges(node) || []);
  if (!Number.isFinite(paths[last]?.distance)) return points;
  const routed: Point[] = [];
  for (let key: string | undefined = last; key; key = paths[key]?.predecessor) {
    routed.push(graph.node(key) as Point);
    if (key === first) break;
  }
  return simplify([start, ...routed.reverse(), end]);
}
