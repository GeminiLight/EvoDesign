import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { X } from 'lucide-react';

export const GalleryDialog = ({ titleId, closeLabel, onClose, children }: { titleId: string; closeLabel: string; onClose: () => void; children: ReactNode }) => {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current!;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    element.showModal();
    return () => {
      element.close();
      document.body.style.overflow = previousOverflow;
      // Restore after React removes the dialog; restoring during unmount loses focus.
      window.setTimeout(() => { if (trigger?.isConnected) trigger.focus(); }, 0);
    };
  }, []);
  return <dialog ref={dialog} aria-labelledby={titleId} className="inspiration-dialog gallery-modal-enter" onCancel={(event) => { event.preventDefault(); onClose(); }} onClick={(event) => { if (event.target === event.currentTarget) { const bounds = event.currentTarget.getBoundingClientRect(); if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose(); } }}>
    <button type="button" onClick={onClose} aria-label={closeLabel} className="studio-icon-button absolute right-3 top-3 z-10 bg-white/80 dark:bg-[#151b2c]/90"><X size={16} /></button>
    {children}
  </dialog>;
};
