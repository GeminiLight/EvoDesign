import { FileText } from 'lucide-react';

// Decorative, code-native illustration: the labels describe supported text references.
export function CreationSketch({ referenceLabel, diagramLabel }: { referenceLabel: string; diagramLabel: string }) {
  return (
    <aside className="home-creation-sketch" aria-hidden="true">
      <div className="home-sketch-note"><FileText size={26} strokeWidth={1.3} /><span>{referenceLabel}<small>design-notes.md</small></span></div>
      <svg viewBox="0 0 200 177" fill="none">
        <path className="sketch-dotted" d="M9 51C-6 21 10 10 36 7M29 2l8 4-6 7" />
        <rect className="sketch-frame" x="27" y="25" width="164" height="139" rx="9" />
        <path className="sketch-line" d="M109 66v15m0 34v14M93 98H70m55 0h24" />
        <path className="sketch-line" d="m106 77 3 4 3-4m-38 18-4 3 4 3m71-6 4 3-4 3m-39 24 3 4 3-4" />
        <rect x="85" y="44" width="48" height="22" rx="5" className="sketch-blue" />
        <path d="m109 83 15 15-15 15-15-15 15-15Z" className="sketch-violet" />
        <rect x="39" y="87" width="31" height="22" rx="4" className="sketch-muted" />
        <rect x="149" y="87" width="31" height="22" rx="4" className="sketch-muted" />
        <rect x="87" y="130" width="44" height="19" rx="4" className="sketch-teal" />
      </svg>
      <span className="home-sketch-caption">{diagramLabel}</span>
    </aside>
  );
}
