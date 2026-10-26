import { useEffect, useState } from 'react';
import type { RecentDiagram } from '../../types/app';

type PreviewNode = {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  label: string;
};

type PreviewEdge = {
  sourceId: string;
  targetId: string;
};

type RecentProjectPreviewProps = {
  project: RecentDiagram;
  title: string;
  unavailableLabel: string;
};

const PREVIEW_FILLS = ['#dbeafe', '#ccfbf1', '#fef3c7', '#fce7f3', '#e0e7ff', '#dcfce7'];

const isRecord = (value: unknown): value is Record<string, unknown> => (
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)
);

const asRecordArray = (value: unknown): Record<string, unknown>[] => (
  Array.isArray(value) ? value.filter(isRecord) : []
);

const readNumber = (...values: unknown[]): number | null => {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return null;
};

const readString = (...values: unknown[]): string => {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
};

const readNestedRecord = (record: Record<string, unknown>, key: string): Record<string, unknown> => (
  isRecord(record[key]) ? record[key] as Record<string, unknown> : {}
);

const isConnectorLike = (record: Record<string, unknown>): boolean => {
  const type = readString(record.type, record.typeName).toLowerCase();
  return ['arrow', 'line', 'edge', 'connector', 'binding'].some((token) => type.includes(token));
};

const nodeFromRecord = (record: Record<string, unknown>, index: number): PreviewNode | null => {
  if (record.isDeleted === true || record.deleted === true || isConnectorLike(record)) return null;

  const props = readNestedRecord(record, 'props');
  const geometry = readNestedRecord(record, 'geometry');
  const position = readNestedRecord(record, 'position');
  const bounds = readNestedRecord(record, 'bounds');

  const x = readNumber(record.x, geometry.x, position.x, bounds.x, bounds.left);
  const y = readNumber(record.y, geometry.y, position.y, bounds.y, bounds.top);
  const width = readNumber(record.width, record.w, props.w, props.width, geometry.width, geometry.w, bounds.width, bounds.w);
  const height = readNumber(record.height, record.h, props.h, props.height, geometry.height, geometry.h, bounds.height, bounds.h);

  if (x === null || y === null || width === null || height === null || width <= 0 || height <= 0) {
    return null;
  }

  const labelRecord = readNestedRecord(record, 'label');
  const label = readString(
    record.text,
    record.label,
    record.name,
    record.title,
    props.text,
    props.name,
    labelRecord.text,
    labelRecord.value,
  );

  return {
    id: readString(record.id, record.semantic_id, record.render_id) || `preview-node-${index}`,
    x,
    y,
    width,
    height,
    label,
  };
};

const collectRecords = (schema: Record<string, unknown> | null | undefined): Record<string, unknown>[] => {
  if (!schema) return [];

  const document = readNestedRecord(schema, 'document');
  const documentRecords = readNestedRecord(document, 'records');
  const rootRecords = readNestedRecord(schema, 'records');
  const records = Object.values(documentRecords).length > 0 ? documentRecords : rootRecords;
  if (Object.values(records).length > 0) {
    return Object.values(records).filter(isRecord);
  }

  return ['elements', 'nodes', 'shapes', 'blocks']
    .flatMap((key) => asRecordArray(schema[key]));
};

const collectPreviewEdges = (records: Record<string, unknown>[]): PreviewEdge[] => records
  .map((record) => {
    const startBinding = readNestedRecord(record, 'startBinding');
    const endBinding = readNestedRecord(record, 'endBinding');
    const sourceId = readString(
      startBinding.elementId,
      record.source,
      record.from,
      record.sourceId,
      record.startNodeId,
    );
    const targetId = readString(
      endBinding.elementId,
      record.target,
      record.to,
      record.targetId,
      record.endNodeId,
    );
    return sourceId && targetId ? { sourceId, targetId } : null;
  })
  .filter((edge): edge is PreviewEdge => edge !== null);

const getPreviewSource = (project: RecentDiagram): Record<string, unknown> | null => {
  if (isRecord(project.tldraw_snapshot)) return project.tldraw_snapshot;
  if (isRecord(project.excalidraw_payload)) return project.excalidraw_payload;
  return null;
};

const buildPreviewModel = (project: RecentDiagram) => {
  const records = collectRecords(getPreviewSource(project));
  const nodes = records
    .map(nodeFromRecord)
    .filter((node): node is PreviewNode => node !== null)
    .slice(0, 12);
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = collectPreviewEdges(records)
    .filter((edge) => nodeIds.has(edge.sourceId) && nodeIds.has(edge.targetId))
    .slice(0, 16);

  return { nodes, edges };
};

export const RecentProjectPreview = ({
  project,
  title,
  unavailableLabel,
}: RecentProjectPreviewProps) => {
  const [imageFailed, setImageFailed] = useState(false);

  useEffect(() => {
    setImageFailed(false);
  }, [project.thumbnail_url]);

  if (project.thumbnail_url && !imageFailed) {
    return (
      <img
        loading="lazy"
        decoding="async"
        src={project.thumbnail_url}
        alt={title}
        className="h-full w-full object-contain bg-white p-3"
        onError={() => setImageFailed(true)}
      />
    );
  }

  const { nodes, edges } = buildPreviewModel(project);

  if (nodes.length === 0) {
    return (
      <div
        className="flex h-full w-full items-center justify-center bg-[radial-gradient(circle_at_20%_20%,rgba(49,141,255,0.12),transparent_32%),linear-gradient(135deg,rgba(248,250,252,0.95),rgba(226,232,240,0.78))] px-4 text-center dark:bg-[radial-gradient(circle_at_20%_20%,rgba(45,212,191,0.14),transparent_32%),linear-gradient(135deg,rgba(15,23,42,0.98),rgba(30,41,59,0.9))]"
        data-preview-source="empty"
      >
        <span className="rounded-lg border border-white/60 bg-white/72 px-3 py-2 text-xs font-semibold text-slate-500 shadow-sm backdrop-blur dark:border-white/10 dark:bg-slate-900/72 dark:text-slate-300">
          {unavailableLabel}
        </span>
      </div>
    );
  }

  const minX = Math.min(...nodes.map((node) => node.x));
  const minY = Math.min(...nodes.map((node) => node.y));
  const maxX = Math.max(...nodes.map((node) => node.x + node.width));
  const maxY = Math.max(...nodes.map((node) => node.y + node.height));
  const sourceWidth = Math.max(maxX - minX, 1);
  const sourceHeight = Math.max(maxY - minY, 1);
  const viewWidth = 320;
  const viewHeight = 180;
  const gridId = `preview-grid-${project.request_id.replace(/[^A-Za-z0-9_-]/g, '') || 'recent-project'}`;
  const pad = 18;
  const scale = Math.min((viewWidth - pad * 2) / sourceWidth, (viewHeight - pad * 2) / sourceHeight);
  const offsetX = (viewWidth - sourceWidth * scale) / 2;
  const offsetY = (viewHeight - sourceHeight * scale) / 2;
  const transformX = (x: number) => (x - minX) * scale + offsetX;
  const transformY = (y: number) => (y - minY) * scale + offsetY;
  const nodeCenter = new Map(nodes.map((node) => [
    node.id,
    {
      x: transformX(node.x + node.width / 2),
      y: transformY(node.y + node.height / 2),
    },
  ]));

  return (
    <div className="h-full w-full bg-slate-50 dark:bg-slate-900" data-preview-source="schema">
      <svg className="h-full w-full" viewBox={`0 0 ${viewWidth} ${viewHeight}`} role="img" aria-label={title}>
        <defs>
          <pattern id={gridId} width="18" height="18" patternUnits="userSpaceOnUse">
            <path d="M18 0H0V18" fill="none" stroke="rgba(148,163,184,0.18)" strokeWidth="1" />
          </pattern>
        </defs>
        <rect width={viewWidth} height={viewHeight} fill={`url(#${gridId})`} />
        {edges.map((edge, index) => {
          const source = nodeCenter.get(edge.sourceId);
          const target = nodeCenter.get(edge.targetId);
          if (!source || !target) return null;
          return (
            <line
              key={`${edge.sourceId}-${edge.targetId}-${index}`}
              x1={source.x}
              y1={source.y}
              x2={target.x}
              y2={target.y}
              stroke="rgba(100,116,139,0.56)"
              strokeWidth="1.6"
              strokeLinecap="round"
            />
          );
        })}
        {nodes.map((node, index) => {
          const x = transformX(node.x);
          const y = transformY(node.y);
          const width = Math.max(node.width * scale, 18);
          const height = Math.max(node.height * scale, 14);
          return (
            <g key={node.id}>
              <rect
                x={x}
                y={y}
                width={width}
                height={height}
                rx="8"
                fill={PREVIEW_FILLS[index % PREVIEW_FILLS.length]}
                stroke="rgba(15,23,42,0.16)"
                strokeWidth="1"
              />
              {node.label && width > 44 && height > 20 && (
                <text
                  x={x + width / 2}
                  y={y + height / 2 + 3}
                  textAnchor="middle"
                  className="fill-slate-600 text-[9px] font-semibold"
                >
                  {node.label.slice(0, 18)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
};
