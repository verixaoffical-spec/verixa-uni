import { useState, type DragEvent, type RefObject } from 'react';
import { icons } from './icons';

interface Props {
  big: boolean;              // large and centred while the list is empty
  title: [string, string];   // [big, compact]
  text: [string, string];
  rules: string[];
  accept: string;
  multiple?: boolean;
  inputRef: RefObject<HTMLInputElement>;
  onFiles: (files: File[]) => void;
}

// Drop files here, or click to browse
export default function DropZone({ big, title, text, rules, accept, multiple, inputRef, onFiles }: Props) {
  const [over, setOver] = useState(false);

  function onDragOver(e: DragEvent) {
    e.preventDefault();
    setOver(true);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    onFiles([...e.dataTransfer.files]);
  }

  return (
    <label className={'drop' + (big ? ' hero' : '') + (over ? ' over' : '')}
           onDragEnter={onDragOver} onDragOver={onDragOver} onDragLeave={() => setOver(false)} onDrop={onDrop}>
      <input className="sr" type="file" ref={inputRef} accept={accept} multiple={multiple}
             onChange={e => { onFiles([...(e.target.files ?? [])]); e.target.value = ''; }} />
      <span className="ico">{icons.upload}</span>
      <span className="dt">
        <strong>{big ? title[0] : title[1]}</strong>
        <small>{big ? text[0] : text[1]}</small>
      </span>
      {big
        ? <span className="rules hero-only">{rules.map(r => <span key={r}>{r}</span>)}</span>
        : <span className="btn ghost sm browse">Browse</span>}
    </label>
  );
}
