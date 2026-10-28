import { useEffect, useId, useRef, useState } from 'react';
import { MoreHorizontal, Pencil, Star, Trash2 } from 'lucide-react';
import type { RecentDiagram } from '../../types/app';
import { RecentProjectPreview } from './RecentProjectPreview';

type Props = {
  project: RecentDiagram;
  title: string;
  metadata: string;
  pinned: boolean;
  onOpen: () => void;
  onTogglePin: () => void;
  onDelete: () => void;
  t: (key: string) => string;
};

export function HomeProjectTile({ project, title, metadata, pinned, onOpen, onTogglePin, onDelete, t }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    menuRef.current?.querySelector<HTMLButtonElement>('button')?.focus();
    const dismiss = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', dismiss);
    return () => document.removeEventListener('pointerdown', dismiss);
  }, [open]);

  const runAction = (action: () => void) => {
    setOpen(false);
    triggerRef.current?.focus();
    action();
  };

  return (
    <article className="home-project-tile">
      <button type="button" className="home-project-open" onClick={onOpen} aria-label={title}>
        <span className="home-project-thumb">
          <RecentProjectPreview project={project} title={title} unavailableLabel={t('home.previewUnavailable')} />
        </span>
        <span className="home-project-title">{pinned && <Star size={12} className="home-pin" aria-label={t('home.pinnedTab')} />}{title}</span>
        <span className="home-project-meta">{metadata}</span>
      </button>
      <div className="home-project-menu" ref={rootRef} onBlur={event => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false);
      }}>
        <button type="button" ref={triggerRef} className="home-project-action" aria-label={`${t('home.projectActions')}: ${title}`} aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined} onClick={() => setOpen(value => !value)} onKeyDown={event => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); setOpen(true); }
        }}><MoreHorizontal size={19} /></button>
        {open && <div id={menuId} ref={menuRef} className="home-project-menu-panel" role="menu" aria-label={t('home.projectActions')} onKeyDown={event => {
          const items = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('button')];
          const index = items.indexOf(document.activeElement as HTMLButtonElement);
          if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setOpen(false); triggerRef.current?.focus(); }
          if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
            event.preventDefault();
            const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
            items[next]?.focus();
          }
        }}>
          <button type="button" role="menuitem" onClick={() => runAction(onOpen)}><Pencil size={15} />{t('home.actionEdit')}</button>
          <button type="button" role="menuitem" onClick={() => runAction(onTogglePin)}><Star size={15} />{t(pinned ? 'dashboard.unmarkFavorite' : 'dashboard.markFavorite')}</button>
          <button type="button" role="menuitem" className="is-danger" onClick={() => runAction(onDelete)}><Trash2 size={15} />{t('home.actionDelete')}</button>
        </div>}
      </div>
    </article>
  );
}
