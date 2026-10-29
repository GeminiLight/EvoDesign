import { Check, FilePlus2, FolderOpen, Loader2, Plus, Search, Shapes, Sparkles, X } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import type { RefObject } from 'react';
import { useAnchoredPopover } from '../../hooks/useAnchoredPopover';
import { useLanguage } from '../../i18n/LanguageProvider';
import type { WorkspaceDocument } from '../../utils/workspaceDocuments';

type Props = {
  documents: WorkspaceDocument[];
  recent: WorkspaceDocument[];
  activeKey: string;
  title: string;
  dirty: boolean;
  busy: boolean;
  saving: boolean;
  editingName: boolean;
  nameDraft: string;
  nameInputRef: RefObject<HTMLInputElement | null>;
  onNameChange: (value: string) => void;
  onRename: () => void;
  onSaveName: () => void;
  onCancelName: () => void;
  onActivate: (document: WorkspaceDocument) => void;
  onClose: (document: WorkspaceDocument) => void;
  onNew: () => void;
  onCreateBlank: () => void;
};

export function WorkspaceTabs({ documents, recent, activeKey, title, dirty, busy, saving,
  editingName, nameDraft, nameInputRef, onNameChange, onRename, onSaveName, onCancelName,
  onActivate, onClose, onNew, onCreateBlank }: Props) {
  const { language, t } = useLanguage();
  const zh = language === 'zh';
  const draftTitle = zh ? '新画布' : 'New canvas';
  const id = useId();
  const [open, setOpen] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [query, setQuery] = useState('');
  const rootRef = useRef<HTMLDivElement>(null);
  const pickerRef = useRef<HTMLDivElement>(null);
  const pickerButtonRef = useRef<HTMLButtonElement>(null);
  const newButtonRef = useRef<HTMLButtonElement>(null);
  const newPanelRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const tabRefs = useRef(new Map<string, HTMLButtonElement>());
  const tabListRef = useRef<HTMLDivElement>(null);
  const focusAfterCloseRef = useRef(false);
  const visible = activeKey === 'draft' ? [...documents, { key: 'draft', diagramId: '', title: draftTitle }] : documents;
  const cancelledRenameRef = useRef(false);
  const all = [...new Map([...documents, ...recent].map(document => [document.key, document])).values()];
  const filtered = all.filter(document => document.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  useAnchoredPopover(open, rootRef, pickerRef, 328, 'below', 'end');
  useAnchoredPopover(newOpen, newButtonRef, newPanelRef, 260, 'below', 'start');

  useEffect(() => {
    const active = tabRefs.current.get(activeKey);
    active?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    if (focusAfterCloseRef.current) { active?.focus(); focusAfterCloseRef.current = false; }
    const observer = new ResizeObserver(() => active?.scrollIntoView({ block: 'nearest', inline: 'nearest' }));
    if (tabListRef.current) observer.observe(tabListRef.current);
    return () => observer.disconnect();
  }, [activeKey, documents]);
  useEffect(() => {
    if (!open && !newOpen) return;
    const frame = requestAnimationFrame(() => {
      if (open) searchRef.current?.focus();
      else newPanelRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
    });
    const dismiss = (event: Event) => {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) { setOpen(false); setNewOpen(false); }
    };
    document.addEventListener('pointerdown', dismiss);
    document.addEventListener('focusin', dismiss);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener('pointerdown', dismiss);
      document.removeEventListener('focusin', dismiss);
    };
  }, [open, newOpen]);
  useEffect(() => { if (busy) { setOpen(false); setNewOpen(false); } }, [busy]);

  return <div className="workspace-documents" ref={rootRef} onKeyDown={event => {
    if (event.nativeEvent.isComposing) return;
    if (event.key === 'Escape' && (open || newOpen)) {
      event.preventDefault(); event.stopPropagation();
      (newOpen ? newButtonRef : pickerButtonRef).current?.focus(); setOpen(false); setNewOpen(false);
    }
  }}>
    <div ref={tabListRef} role="tablist" aria-label={zh ? '已打开的画布' : 'Open canvases'} className="workspace-tabs">
      {visible.map((document, index) => {
        const active = document.key === activeKey;
        return <div key={document.key} role="presentation" className="workspace-tab" data-active={active}>
          {active && editingName ? <input ref={nameInputRef} className="workspace-tab-name-input"
            aria-label={t('workspace.projectName')} value={nameDraft}
            onChange={event => onNameChange(event.target.value)} onBlur={() => {
              if (cancelledRenameRef.current) { cancelledRenameRef.current = false; return; }
              onSaveName();
            }}
            onKeyDown={event => {
              event.stopPropagation();
              if (event.key === 'Enter') { event.preventDefault(); event.currentTarget.blur(); }
              if (event.key === 'Escape') { event.preventDefault(); cancelledRenameRef.current = true; event.currentTarget.blur(); onCancelName();
                requestAnimationFrame(() => tabRefs.current.get(activeKey)?.focus()); }
            }} /> : <button type="button" role="tab" id={`${id}-${index}`}
            ref={element => { if (element) tabRefs.current.set(document.key, element); else tabRefs.current.delete(document.key); }}
            aria-selected={active} aria-controls="workspace-pane-canvas" tabIndex={active ? 0 : -1}
            title={document.key === 'draft' ? draftTitle : document.title || title} disabled={busy}
            onClick={() => onActivate(document)} onDoubleClick={() => { if (active) onRename(); }}
            onKeyDown={event => {
              let next = index;
              if (event.key === 'ArrowLeft') next = (index + visible.length - 1) % visible.length;
              else if (event.key === 'ArrowRight') next = (index + 1) % visible.length;
              else if (event.key === 'Home') next = 0;
              else if (event.key === 'End') next = visible.length - 1;
              else if (event.key === 'Delete' && document.key !== 'draft') {
                event.preventDefault(); focusAfterCloseRef.current = true; onClose(document); return;
              } else return;
              event.preventDefault(); tabRefs.current.get(visible[next].key)?.focus();
            }}>
            {active && saving ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <Shapes size={14} aria-hidden="true" />}
            <span>{document.key === 'draft' ? draftTitle : active ? title : document.title}</span>
            {active && dirty && <i className="workspace-tab-dirty" aria-label={zh ? '未保存' : 'Unsaved changes'} />}
          </button>}
          {document.key !== 'draft' && <button type="button" className="workspace-tab-close" disabled={busy}
            aria-label={`${zh ? '关闭画布' : 'Close canvas'}: ${document.title}`} title={zh ? '关闭标签，保留画布' : 'Close tab; keep canvas'}
            tabIndex={active ? 0 : -1} onClick={() => { focusAfterCloseRef.current = true; onClose(document); }}><X size={13} aria-hidden="true" /></button>}
        </div>;
      })}
    </div>
    <button ref={newButtonRef} type="button" className="workspace-tab-action" disabled={busy}
      aria-haspopup="menu" aria-expanded={newOpen} aria-controls={`${id}-new`}
      onClick={() => { setOpen(false); setNewOpen(value => !value); }}
      aria-label={zh ? '新建画布' : 'New canvas'} title={zh ? '新建画布' : 'New canvas'}><Plus size={18} aria-hidden="true" /></button>
    {newOpen && <div ref={newPanelRef} id={`${id}-new`} popover="manual" role="menu" aria-label={zh ? '新建画布' : 'New canvas'} className="workspace-new-menu"
      onKeyDown={event => {
        const buttons = [...(newPanelRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [])];
        const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
        const next = event.key === 'ArrowDown' ? (current + 1) % buttons.length : event.key === 'ArrowUp' ? (current + buttons.length - 1) % buttons.length
          : event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : null;
        if (next === null) return;
        event.preventDefault(); buttons[next]?.focus();
      }}>
      <button type="button" role="menuitem" onClick={() => { setNewOpen(false); newButtonRef.current?.focus(); onCreateBlank(); }}>
        <FilePlus2 size={19} aria-hidden="true" /><span><strong>{zh ? '空白画布' : 'Blank canvas'}</strong><small>{zh ? '直接绘制与编辑' : 'Start drawing and editing'}</small></span>
      </button>
      <button type="button" role="menuitem" onClick={() => { setNewOpen(false); newButtonRef.current?.focus(); onNew(); }}>
        <Sparkles size={19} aria-hidden="true" /><span><strong>{zh ? 'AI 生成' : 'Generate with AI'}</strong><small>{zh ? '描述想法，生成图表' : 'Turn a description into a diagram'}</small></span>
      </button>
    </div>}
    <button ref={pickerButtonRef} type="button" className="workspace-tab-action" disabled={busy}
      aria-label={zh ? '打开画布' : 'Open a canvas'} title={zh ? '打开已有画布' : 'Open an existing canvas'}
      aria-haspopup="dialog" aria-expanded={open} aria-controls={`${id}-picker`}
      onClick={() => { setNewOpen(false); setQuery(''); setOpen(value => !value); }}><FolderOpen size={18} aria-hidden="true" /></button>
    {open && <div id={`${id}-picker`} ref={pickerRef} popover="manual" role="dialog"
      aria-label={zh ? '打开画布' : 'Open a canvas'} className="workspace-canvas-picker"
      onKeyDown={event => {
        if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
        const buttons = [...(pickerRef.current?.querySelectorAll<HTMLButtonElement>('[data-document-option]') ?? [])];
        if (!buttons.length) return;
        const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
        const next = event.key === 'ArrowDown' ? (current + 1) % buttons.length : (current + buttons.length - 1) % buttons.length;
        event.preventDefault(); buttons[next]?.focus();
      }}>
      <label className="workspace-picker-search"><Search size={15} aria-hidden="true" /><input ref={searchRef}
        aria-label={zh ? '搜索画布' : 'Search canvases'} placeholder={zh ? '搜索画布…' : 'Search canvases…'}
        value={query} onChange={event => setQuery(event.target.value)} /></label>
      <div className="workspace-picker-list">
        {filtered.map(document => <button key={document.key} type="button" data-document-option
          title={document.title} onClick={() => { setOpen(false); pickerButtonRef.current?.focus(); onActivate(document); }}>
          <Shapes size={15} aria-hidden="true" /><span>{document.title}</span>
          {document.key === activeKey ? <Check size={14} aria-hidden="true" /> : documents.some(item => item.key === document.key) && <small>{zh ? '已打开' : 'Open'}</small>}
        </button>)}
        {!filtered.length && <p>{zh ? '没有找到画布' : 'No canvases found'}</p>}
      </div>
      <button type="button" className="workspace-picker-new" onClick={() => { setOpen(false); setNewOpen(true); newButtonRef.current?.focus(); }}><FilePlus2 size={15} aria-hidden="true" />{zh ? '新建画布' : 'New canvas'}</button>
    </div>}
  </div>;
}
