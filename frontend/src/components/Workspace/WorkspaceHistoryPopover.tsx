import { History } from 'lucide-react';
import { useEffect, useRef, type ReactNode, type RefObject } from 'react';
import { useAnchoredPopover } from '../../hooks/useAnchoredPopover';
import { useLanguage } from '../../i18n/LanguageProvider';

export function WorkspaceHistoryPopover({ open, onOpenChange, disabled, mobileAnchorRef, children }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  disabled: boolean;
  mobileAnchorRef?: RefObject<HTMLButtonElement | null>;
  children: ReactNode;
}) {
  const { t } = useLanguage();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const onChangeRef = useRef(onOpenChange);
  onChangeRef.current = onOpenChange;
  useAnchoredPopover(open, mobileAnchorRef ?? rootRef, panelRef, 344, 'below', 'end');

  useEffect(() => {
    if (!open) return;
    panelRef.current?.focus({ preventScroll: true });
    const dismiss = (event: Event) => {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !mobileAnchorRef?.current?.contains(target)) onChangeRef.current(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault(); event.stopPropagation();
      onChangeRef.current(false);
      (mobileAnchorRef?.current ?? triggerRef.current)?.focus({ preventScroll: true });
    };
    document.addEventListener('pointerdown', dismiss);
    document.addEventListener('focusin', dismiss);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('pointerdown', dismiss);
      document.removeEventListener('focusin', dismiss);
      document.removeEventListener('keydown', escape);
    };
  }, [open, mobileAnchorRef]);
  useEffect(() => { if (disabled && open) onChangeRef.current(false); }, [disabled, open]);

  return <div ref={rootRef} className="workspace-history-control">
    <button ref={triggerRef} type="button" className="tool-button workspace-project-toggle" disabled={disabled}
      aria-label={t('studio.documentVersions')} title={t('studio.documentVersions')}
      aria-haspopup="dialog" aria-expanded={open} aria-controls="workspace-history-popover"
      onClick={() => onOpenChange(!open)}><History size={16} aria-hidden="true" /></button>
    {open && <div ref={panelRef} id="workspace-history-popover" className="workspace-history-popover" popover="manual"
      role="dialog" aria-label={t('studio.documentVersions')} tabIndex={-1}>{children}</div>}
  </div>;
}
