import { Check, ChevronDown, Loader2, RefreshCw } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import type { RefObject } from 'react';
import { useAnchoredPopover } from '../hooks/useAnchoredPopover';
import type { BrowserModelChoice } from '../services/browser/modelConfig';

type Props = {
  inputRef: RefObject<HTMLInputElement | null>;
  value: string;
  onChange: (value: string) => void;
  onBlur: () => void;
  onLoad: () => void;
  models: BrowserModelChoice[];
  loading: boolean;
  loaded: boolean;
  invalid: boolean;
  zh: boolean;
};

export function ModelIdPicker({ inputRef, value, onChange, onBlur, onLoad, models, loading, loaded, invalid, zh }: Props) {
  const id = useId();
  const listId = `${id}-models`;
  const rootRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(-1);
  const matches = models.filter(model => `${model.id} ${model.name ?? ''}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const visible = matches.slice(0, 80);
  useAnchoredPopover(open, rootRef, panelRef, 'anchor', 'below');
  useEffect(() => {
    if (!open) return;
    const dismiss = (event: Event) => { if (event.target instanceof Node && !rootRef.current?.contains(event.target)) setOpen(false); };
    document.addEventListener('pointerdown', dismiss);
    document.addEventListener('focusin', dismiss);
    return () => { document.removeEventListener('pointerdown', dismiss); document.removeEventListener('focusin', dismiss); };
  }, [open]);
  useEffect(() => {
    if (!open || active < 0) return;
    const item = panelRef.current?.querySelector(`[data-index="${active}"]`)?.getBoundingClientRect();
    const panel = panelRef.current;
    if (!item || !panel) return;
    const box = panel.getBoundingClientRect();
    if (item.top < box.top + 40) panel.scrollTop -= box.top + 40 - item.top;
    else if (item.bottom > box.bottom - 6) panel.scrollTop += item.bottom - box.bottom + 6;
  }, [active, open]);
  const choose = (model: BrowserModelChoice) => { onChange(model.id); setOpen(false); setActive(-1); inputRef.current?.focus({ preventScroll: true }); };
  const expand = () => { setOpen(true); setQuery(''); setActive(-1); if (!loaded && !loading) onLoad(); };
  return <div ref={rootRef} className="model-id-picker" onKeyDown={event => {
    if (event.key === 'Escape' && open) { event.preventDefault(); event.stopPropagation(); setOpen(false); inputRef.current?.focus({ preventScroll: true }); }
  }}>
    <div className="relative">
      <input id="browser-model-id" ref={inputRef} className="studio-form-input pr-12" role="combobox" required
        value={value} placeholder={zh ? '输入或搜索模型 ID' : 'Enter or search model ID'} spellCheck={false} autoComplete="off" autoCapitalize="none"
        aria-autocomplete="list" aria-expanded={open} aria-controls={open ? listId : undefined}
        aria-activedescendant={open && active >= 0 && visible[active] ? `${id}-option-${active}` : undefined}
        aria-invalid={invalid} aria-describedby={invalid ? 'browser-model-id-error' : undefined}
        onBlur={event => { if (!rootRef.current?.contains(event.relatedTarget)) onBlur(); }}
        onChange={event => { onChange(event.target.value); setQuery(event.target.value); setActive(-1); if (loaded) setOpen(true); }}
        onKeyDown={event => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            if (!open) expand();
            else setActive(current => visible.length ? (current + (event.key === 'ArrowDown' ? 1 : -1) + visible.length) % visible.length : -1);
          } else if (event.key === 'Enter' && open && active >= 0 && visible[active] && !event.nativeEvent.isComposing) {
            event.preventDefault(); choose(visible[active]);
          } else if (event.key === 'Tab') setOpen(false);
        }} />
      <button type="button" className="studio-icon-button absolute right-0 top-0" aria-label={zh ? '浏览服务商模型' : 'Browse provider models'}
        aria-expanded={open} aria-controls={open ? listId : undefined} onClick={() => { if (open) setOpen(false); else expand(); }}>
        {loading ? <Loader2 size={15} className="animate-spin" /> : <ChevronDown size={15} />}
      </button>
    </div>
    {open && <div ref={panelRef} popover="manual" className="choice-select-list model-id-list">
      <div className="model-id-list-heading"><span>{zh ? '服务商模型' : 'Provider models'}{loaded && models.length > 0 ? ` · ${models.length}` : ''}</span>
        <button type="button" aria-label={zh ? '刷新模型列表' : 'Refresh models'} disabled={loading} onClick={onLoad}><RefreshCw size={13} /></button></div>
      <div role="listbox" id={listId} aria-label={zh ? '模型列表' : 'Models'} className="model-id-results">
        {visible.map((model, index) => <button key={model.id} id={`${id}-option-${index}`} type="button" role="option" tabIndex={-1}
          aria-selected={model.id === value} data-active={active === index} data-index={index}
          onMouseDown={event => event.preventDefault()} onClick={() => choose(model)}>
          <span>{model.id}{model.name && model.name !== model.id && <small>{model.name}</small>}</span>{model.id === value && <Check size={14} aria-hidden="true" />}
        </button>)}
      </div>
      {loading && <p role="status">{zh ? '正在读取模型目录…' : 'Reading model catalog…'}</p>}
      {!loading && visible.length === 0 && <p>{models.length ? (zh ? '没有匹配项，可继续手动输入。' : 'No match. You can enter an ID manually.') : (zh ? '暂未取得模型列表，可手动输入 ID。' : 'No catalog available. Enter a model ID manually.')}</p>}
      {matches.length > visible.length && <p>{zh ? '输入更多关键词缩小范围。' : 'Type more to narrow the list.'}</p>}
    </div>}
  </div>;
}
