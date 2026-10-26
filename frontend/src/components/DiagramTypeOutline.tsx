type DiagramOutlineKind = 'architecture' | 'sequence' | 'flowchart' | 'mindmap';

/**
 * Schematic previews for the diagram-type starter cards.
 *
 * Home previously picked these by array index rather than by type, so the
 * Sequence card drew boxes and the Flowchart card drew circles. Keying off the
 * kind keeps each card's picture honest about what it will produce, and gives
 * Landing and Home one shared source instead of two diverging sets of SVG.
 */
export function DiagramTypeOutline({ kind }: { kind: DiagramOutlineKind }) {
  const common = {
    className: 'h-full w-full',
    viewBox: '0 0 300 120',
    fill: 'none',
    'aria-hidden': true as const,
    xmlns: 'http://www.w3.org/2000/svg',
  };

  if (kind === 'sequence') {
    // Participants across the top, dashed lifelines dropping from each, and
    // messages crossing between them.
    return (
      <svg {...common}>
        <g stroke="currentColor" strokeWidth="2">
          {[60, 150, 240].map((x) => (
            <rect key={x} x={x - 30} y="10" width="60" height="20" rx="6" />
          ))}
        </g>
        <g stroke="currentColor" strokeWidth="1.5" strokeOpacity="0.4" strokeDasharray="4 5">
          {[60, 150, 240].map((x) => (
            <path key={x} d={`M${x} 32V112`} />
          ))}
        </g>
        <g stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M60 52H144" />
          <path d="M138 47l6 5-6 5" />
          <path d="M150 76H234" />
          <path d="M228 71l6 5-6 5" />
          <path d="M240 100H66" strokeDasharray="5 5" />
          <path d="M72 95l-6 5 6 5" />
        </g>
      </svg>
    );
  }

  if (kind === 'flowchart') {
    // Start terminator, a step, then a decision diamond branching two ways.
    return (
      <svg {...common}>
        <g stroke="currentColor" strokeWidth="2">
          <rect x="112" y="8" width="76" height="20" rx="10" />
          <path d="M150 62l22 18-22 18-22-18z" />
          <path d="M40 90h44M216 90h44" />
          <rect x="18" y="78" width="44" height="22" rx="6" />
          <rect x="238" y="78" width="44" height="22" rx="6" />
        </g>
        <g stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M150 28v34" />
          <path d="M145 56l5 6 5-6" />
          <path d="M128 80H84" />
          <path d="M172 80h44" />
        </g>
      </svg>
    );
  }

  if (kind === 'mindmap') {
    // A central concept with branches radiating to satellite nodes.
    return (
      <svg {...common}>
        <g stroke="currentColor" strokeWidth="2">
          <circle cx="150" cy="60" r="22" />
          <circle cx="52" cy="26" r="15" />
          <circle cx="52" cy="94" r="15" />
          <circle cx="248" cy="26" r="15" />
          <circle cx="248" cy="94" r="15" />
        </g>
        <g stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeOpacity="0.75">
          <path d="M131 49C110 36 92 30 67 27" />
          <path d="M131 71C110 84 92 90 67 93" />
          <path d="M169 49C190 36 208 30 233 27" />
          <path d="M169 71C190 84 208 90 233 93" />
        </g>
      </svg>
    );
  }

  // Architecture: tiers of services with a shared layer beneath them.
  return (
    <svg {...common}>
      <g stroke="currentColor" strokeWidth="2">
        <rect x="22" y="14" width="64" height="24" rx="7" />
        <rect x="118" y="14" width="64" height="24" rx="7" />
        <rect x="214" y="14" width="64" height="24" rx="7" />
        <rect x="70" y="82" width="72" height="24" rx="7" />
        <rect x="164" y="82" width="72" height="24" rx="7" />
      </g>
      <g stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        <path d="M86 26h32M182 26h32" />
        <path d="M54 38v20h92v24" />
        <path d="M246 38v20h-46v24" />
        <path d="M142 94h22" strokeDasharray="4 4" />
      </g>
    </svg>
  );
}

export default DiagramTypeOutline;
