import { ChevronDown, FileText, X } from 'lucide-react';
import { useId, useRef, useState } from 'react';
import { useLanguage } from '../../i18n/LanguageProvider';
import type { HomeReference } from '../../utils/homeReference';

type Props = {
  reference: HomeReference;
  onRemove: () => void;
  disabled?: boolean;
};

export function HomeReferencePreview({ reference, onRemove, disabled }: Props) {
  const { t } = useLanguage();
  const [expanded, setExpanded] = useState(false);
  const excerptId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);

  return (
    <div className="home-reference" onKeyDown={event => {
      if (event.key === 'Escape' && expanded) {
        event.preventDefault();
        event.stopPropagation();
        setExpanded(false);
        triggerRef.current?.focus();
      }
    }}>
      <div className="home-reference-heading">
        <button ref={triggerRef} type="button" className="home-reference-toggle" disabled={disabled}
          aria-expanded={expanded} aria-controls={excerptId} onClick={() => setExpanded(value => !value)}>
          <FileText size={15} aria-hidden="true" />
          <span className="home-reference-name" title={reference.name}>{reference.name}</span>
          <span className="home-reference-label">{t(expanded ? 'home.collapseReference' : 'home.previewReference')}</span>
          <ChevronDown size={13} aria-hidden="true" />
        </button>
        <button type="button" className="home-reference-remove" onClick={onRemove} disabled={disabled}
          aria-label={`${t('home.removeReference')}: ${reference.name}`}><X size={15} aria-hidden="true" /></button>
      </div>
      <div id={excerptId} hidden={!expanded} className="home-reference-excerpt" role="region" tabIndex={expanded ? 0 : -1}
        aria-label={`${t('home.referenceExcerpt')}: ${reference.name}`}>
        <pre>{reference.text}</pre>
      </div>
    </div>
  );
}
