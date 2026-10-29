import type { ReactNode } from 'react';

type Props = {
  title: string;
  description?: string;
  actions?: ReactNode;
  titleInHeader?: boolean;
};

/** A shared rhythm for library pages; the canvas keeps its own document toolbar. */
export function StudioPageHeading({ title, description, actions, titleInHeader = false }: Props) {
  return (
    <header className={`studio-page-heading ${titleInHeader ? 'studio-page-heading-actions-only' : ''}`}>
      <div className="studio-page-heading-copy">
        {!titleInHeader && <h1>{title}</h1>}
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="studio-page-actions">{actions}</div>}
    </header>
  );
}
