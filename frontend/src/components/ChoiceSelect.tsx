import { Check, ChevronDown } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useAnchoredPopover } from '../hooks/useAnchoredPopover';
import { useCallback, useEffect, useId, useRef, useState } from 'react';

type Choice = { value: string; label: string; Icon?: LucideIcon; lang?: string; description?: string; featured?: boolean };
type Props = {
  id?: string;
  label: string;
  value: string;
  options: Choice[];
  onChange: (value: string) => void;
  className?: string;
  menuWidth?: number | 'anchor';
  placement?: 'auto' | 'below';
  align?: 'start' | 'end';
  disabled?: boolean;
};

/** A small select with native button focus order and a styled listbox. */
export function ChoiceSelect({ id, label, value, options, onChange, className = '', menuWidth = 232, placement = 'below', align = 'start', disabled = false }: Props) {
  const generatedId = useId();
  const controlId = id ?? generatedId;
  const listId = `${controlId}-choices`;
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const typeaheadRef = useRef({ text: '', at: 0 });
  const selectedIndex = Math.max(0, options.findIndex(option => option.value === value));
  const selected = options[selectedIndex];
  const SelectedIcon = selected?.Icon;
  const accessibleLabel = label.replace(/[:：]\s*$/u, '');
  const focusOption = useCallback((index: number) => {
    const option = optionRefs.current[index];
    const list = listRef.current;
    option?.focus({ preventScroll: true });
    if (!option || !list) return;
    const item = option.getBoundingClientRect();
    const box = list.getBoundingClientRect();
    if (item.top < box.top + 6) list.scrollTop -= box.top + 6 - item.top;
    else if (item.bottom > box.bottom - 6) list.scrollTop += item.bottom - box.bottom + 6;
  }, []);

  useAnchoredPopover(open, rootRef, listRef, menuWidth, placement, align);

  useEffect(() => {
    if (!open) return;
    focusOption(selectedIndex);
    const dismiss = (event: Event) => {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener('pointerdown', dismiss);
    document.addEventListener('focusin', dismiss);
    return () => {
      document.removeEventListener('pointerdown', dismiss);
      document.removeEventListener('focusin', dismiss);
    };
  }, [open, selectedIndex, focusOption]);

  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);

  const choose = (next: string) => {
    onChange(next);
    setOpen(false);
    triggerRef.current?.focus({ preventScroll: true });
  };

  return (
    <div ref={rootRef} className={`choice-select ${className}`} onKeyDown={event => {
      if (event.key === 'Escape' && open) {
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
        triggerRef.current?.focus({ preventScroll: true });
      }
    }}>
      <button ref={triggerRef} id={controlId} type="button" className="choice-select-trigger" disabled={disabled}
        aria-label={`${accessibleLabel}: ${selected?.label ?? ''}`} aria-haspopup="listbox" aria-expanded={open}
        aria-controls={open ? listId : undefined} onClick={() => setOpen(previous => !previous)}
        onKeyDown={event => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); event.stopPropagation(); setOpen(true); }
        }}>
        {SelectedIcon && <SelectedIcon size={16} strokeWidth={1.6} aria-hidden="true" />}
        <span>{selected?.label}</span><ChevronDown size={12} aria-hidden="true" />
      </button>
      {open && !disabled && <div ref={listRef} id={listId} className="choice-select-list" popover="manual" role="listbox" aria-label={accessibleLabel}
        onKeyDown={event => {
          const index = optionRefs.current.indexOf(document.activeElement as HTMLButtonElement);
          const last = options.length - 1;
          if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
            event.preventDefault();
            event.stopPropagation();
            const next = event.key === 'Home' ? 0 : event.key === 'End' ? last
              : (index + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
            focusOption(next);
          } else if (event.key.length === 1 && event.key !== ' ' && !event.ctrlKey && !event.metaKey && !event.altKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            event.stopPropagation();
            const now = Date.now();
            const text = (now - typeaheadRef.current.at < 700 ? typeaheadRef.current.text : '') + event.key.toLocaleLowerCase();
            typeaheadRef.current = { text, at: now };
            const search = [...text].every(character => character === text[0]) ? text[0] : text;
            for (let step = 1; step <= options.length; step += 1) {
              const next = (index + step) % options.length;
              if (options[next].label.toLocaleLowerCase().startsWith(search)) { focusOption(next); break; }
            }
          }
        }}>
        {options.map(({ value: optionValue, label: optionLabel, Icon, lang, description, featured }, index) => (
          <button key={optionValue} ref={element => { optionRefs.current[index] = element; }} type="button" role="option"
            aria-selected={optionValue === value} tabIndex={-1} lang={lang} data-featured={featured || undefined} onClick={() => choose(optionValue)}>
            {Icon && <Icon size={16} strokeWidth={1.6} aria-hidden="true" />}<span>{optionLabel}{description && <small>{description}</small>}</span>
            {optionValue === value && <Check size={14} aria-hidden="true" />}
          </button>
        ))}
      </div>}
    </div>
  );
}
