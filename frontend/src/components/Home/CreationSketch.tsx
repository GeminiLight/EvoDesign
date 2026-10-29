import { FileText, SquarePen } from 'lucide-react';

type Props = {
  referenceLabel: string;
  diagramLabel: string;
  labels: { idea: string; link: string; editable: string; edit: string };
};

// Decorative, code-native illustration: the labels describe supported text references.
export function CreationSketch({ referenceLabel, diagramLabel, labels }: Props) {
  return (
    <aside className="home-creation-sketch" aria-hidden="true">
      <div className="home-sketch-note"><span className="home-sketch-file-icon"><FileText size={23} strokeWidth={1.4} /></span><span>{referenceLabel}<small>design-notes.md</small></span></div>
      <svg viewBox="0 0 228 198" fill="none">
        <path className="sketch-dotted" d="M16 53C-3 24 10 11 39 8m-7-5 8 4-6 7" />
        <rect className="sketch-frame" x="25" y="25" width="194" height="160" rx="14" />
        <path className="sketch-guide" d="M40 50h164M40 162h164M122 38v133" />
        <path className="sketch-line sketch-trace" pathLength="1" d="M122 75v15m0 35v20M99 107H79m66 0h20" />
        <path className="sketch-line sketch-trace" pathLength="1" d="m119 86 3 4 3-4m-42 17-4 4 4 4m78-8 4 4-4 4m-42 30 3 4 3-4" />
        <g className="sketch-node sketch-node-one">
          <rect x="91" y="48" width="62" height="27" rx="7" className="sketch-blue" />
          <text x="122" y="65" textAnchor="middle" className="sketch-label">{labels.idea}</text>
        </g>
        <g className="sketch-node sketch-node-two">
          <path d="m122 88 22 19-22 19-22-19 22-19Z" className="sketch-violet" />
          <text x="122" y="110" textAnchor="middle" className="sketch-label sketch-label-small">{labels.link}</text>
          <rect x="45" y="97" width="34" height="20" rx="5" className="sketch-muted" />
          <path className="sketch-detail" d="M54 107h16" />
          <rect x="165" y="97" width="34" height="20" rx="5" className="sketch-muted" />
          <path className="sketch-detail" d="M174 107h16" />
        </g>
        <g className="sketch-node sketch-node-three">
          <rect x="85" y="145" width="74" height="25" rx="7" className="sketch-teal" />
          <text x="122" y="161" textAnchor="middle" className="sketch-label">{labels.editable}</text>
        </g>
      </svg>
      <span className="home-sketch-edit"><SquarePen size={12} strokeWidth={1.5} />{labels.edit}</span>
      <span className="home-sketch-caption">{diagramLabel}</span>
    </aside>
  );
}
