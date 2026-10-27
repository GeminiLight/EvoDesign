import { useId } from 'react';
import type { GalleryWork } from '../../data/galleryMockData';

const NODE_TONES = ['inspiration-node-0', 'inspiration-node-1', 'inspiration-node-2'];

/** Shared schematic preview: the gallery and detail view show the same content. */
export const DiagramPreview = ({ work }: { work: GalleryWork }) => {
  const arrowId = useId();
  const isSequence = work.diagramType === 'sequence';
  return <svg viewBox={work.thumbnail.viewBox} fill="none" className="inspiration-diagram h-full w-full" aria-hidden="true">
    <defs><marker id={arrowId} viewBox="0 0 6 6" refX="5" refY="3" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M1 1 L5 3 L1 5" fill="none" stroke="currentColor" strokeWidth="1" /></marker></defs>
    {work.thumbnail.edges.map((edge, i) => <g key={i}>
      <path d={edge.d} className="inspiration-edge" strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round" strokeDasharray={isSequence && i < 4 ? '3 4' : undefined} markerEnd={work.diagramType !== 'mindmap' && !(isSequence && i < 4) ? `url(#${arrowId})` : undefined} />
      {edge.label && <text x={edge.labelX} y={edge.labelY} textAnchor="middle" className="inspiration-edge-label" fontSize="7">{edge.label}</text>}
    </g>)}
    {work.thumbnail.nodes.map((node, i) => node.h <= 1 ? <path key={i} d={`M${node.x} ${node.y} h${node.w}`} className="inspiration-edge" strokeWidth="0.6" strokeDasharray="3 4" /> : <g key={i} className={`inspiration-node ${NODE_TONES[i % NODE_TONES.length]}`}>
      <rect x={node.x} y={node.y} width={node.w} height={node.h} rx={node.rx >= 12 ? node.h / 2 : Math.min(node.rx, 5)} strokeWidth="0.8" />
      <text x={node.x + node.w / 2} y={node.y + node.h / 2} textAnchor="middle" dominantBaseline="central" fontSize={node.w < 50 ? '7.5' : '8.5'} fontWeight="500">{node.label}</text>
    </g>)}
  </svg>;
};
