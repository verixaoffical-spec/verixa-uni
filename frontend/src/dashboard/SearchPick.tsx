/* A searchable picker for long lists, such as a GitHub account with many repositories.
 * Type to filter, use the arrow keys or the mouse to choose, Enter to pick and Escape to close.
 * It follows the ARIA combobox pattern, so screen readers announce the list and the highlighted option. */
import { useEffect, useId, useMemo, useRef, useState } from 'react';

export interface PickOption { value: string; label: string }

interface Props {
  label: string;
  options: PickOption[];
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  noun: string;  // "repository", used in "No repository matches ..."
}

export default function SearchPick({ label, options, value, onChange, placeholder, noun }: Props) {
  const id = useId();
  const box = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const chosen = options.find(o => o.value === value);

  const shown = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    return options.filter(o => words.every(w => o.label.toLowerCase().includes(w)));
  }, [options, query]);

  // Close when the user clicks anywhere else
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) { setOpen(false); setQuery(''); } };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, [open]);

  // Keep the highlighted option in view while moving with the keyboard
  useEffect(() => {
    list.current?.querySelector<HTMLElement>(`[data-i="${active}"]`)?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  function pick(option: PickOption) {
    onChange(option.value);
    setOpen(false);
    setQuery('');
  }

  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!open) { setOpen(true); return; }
      const step = e.key === 'ArrowDown' ? 1 : -1;
      setActive(i => Math.min(Math.max(i + step, 0), Math.max(shown.length - 1, 0)));
    } else if (e.key === 'Enter' && open) {
      e.preventDefault();
      if (shown[active]) pick(shown[active]);
    } else if (e.key === 'Escape' && open) {
      e.preventDefault();
      setOpen(false);
      setQuery('');
    }
  }

  return (
    <div className="field pick" ref={box}>
      <label htmlFor={id}>{label}</label>
      <div className="pick-control">
        <input
          id={id}
          role="combobox"
          aria-expanded={open}
          aria-controls={`${id}-list`}
          aria-autocomplete="list"
          aria-activedescendant={open && shown[active] ? `${id}-${active}` : undefined}
          autoComplete="off"
          spellCheck={false}
          placeholder={chosen ? chosen.label : placeholder}
          value={open ? query : chosen?.label ?? ''}
          onFocus={() => { setOpen(true); setActive(0); }}
          onClick={() => setOpen(true)}
          onChange={e => { setQuery(e.target.value); setOpen(true); setActive(0); }}
          onKeyDown={onKey}
        />
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
      </div>
      {open && (
        <div className="pick-pop">
          <p className="pick-count" aria-live="polite">
            {query ? `${shown.length} of ${options.length} match` : `${options.length} to choose from. Type to search`}
          </p>
          {shown.length ? (
            <ul id={`${id}-list`} role="listbox" ref={list} aria-label={label}>
              {shown.map((o, i) => (
                <li key={o.value} id={`${id}-${i}`} data-i={i} role="option" aria-selected={o.value === value}
                    className={(i === active ? 'on' : '') + (o.value === value ? ' picked' : '')}
                    onMouseEnter={() => setActive(i)} onMouseDown={e => { e.preventDefault(); pick(o); }}>
                  {o.label}
                </li>
              ))}
            </ul>
          ) : (
            <p className="pick-none">No {noun} matches "{query}"</p>
          )}
        </div>
      )}
    </div>
  );
}
