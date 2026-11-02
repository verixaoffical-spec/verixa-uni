import { useRef, useState, type KeyboardEvent } from 'react';
import Cell from './Cell';
import { icons } from './icons';
import { METHODS } from './validation';
import type { NewRequest } from './editing';
import type { CollectionItem } from './library';
import type { LibraryActions } from './useLibrary';

const EMPTY_ROW: NewRequest = { folder: '', method: 'GET', name: '', url: '', status: '200' };

// The requests of the Postman collection, as an editable table. Every edit rewrites the collection JSON.
export default function CollectionTable({ collection, library }: { collection: CollectionItem; library: LibraryActions }) {
  const [draft, setDraft] = useState<NewRequest>(EMPTY_ROW);
  const nameRef = useRef<HTMLInputElement>(null);
  const setField = (field: keyof NewRequest, value: string) => setDraft(d => ({ ...d, [field]: value }));

  function add() {
    if (library.addRequestRow(draft)) {
      setDraft(EMPTY_ROW);
      nameRef.current?.focus();
    }
  }

  const addOnEnter = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); add(); }
  };

  return (
    <>
      <div className="tablewrap">
        <table className="grid cols-pm">
          <thead>
            <tr>
              <th className="num">#</th><th>Folder</th><th>Method</th><th>Test case</th><th>URL</th>
              <th title="Status code the response must return">Status</th><th></th>
            </tr>
          </thead>
          <tbody>
            {collection.requests.map((r, i) => (
              <tr key={i}>
                <td className="num">{i + 1}</td>
                <td className="fold">
                  {r.folder ? <span className="foldertag" title={r.folder}>{r.folder}</span> : <span className="muted">Top level</span>}
                </td>
                <td>
                  <select className={'cell sel method m-' + r.method} value={r.method} aria-label="Method"
                          onChange={e => library.editRequestCell(i, 'method', e.target.value)}>
                    {METHODS.map(m => <option key={m}>{m}</option>)}
                  </select>
                </td>
                <td>
                  <Cell id={`pm|col|${i}|name`} value={r.name} maxLength={200} label="Request name"
                        onCommit={v => library.editRequestCell(i, 'name', v)} />
                </td>
                <td>
                  <Cell id={`pm|col|${i}|url`} className="mono" value={r.url} maxLength={2000} label="URL"
                        onCommit={v => library.editRequestCell(i, 'url', v)} />
                </td>
                <td>
                  {r.check.kind === 'custom'
                    ? <span className="tag" title="This request has its own test script. Edit it in Postman.">Custom script</span>
                    : <Cell id={`pm|col|${i}|status`} className="narrow" value={r.check.kind === 'status' ? r.check.code : ''}
                            maxLength={3} numeric placeholder="None" label="Expected status code"
                            onCommit={v => library.editRequestCell(i, 'status', v)} />}
                </td>
                <td className="rowact">
                  <button className="icon-btn" aria-label={`Delete test case ${i + 1}`} title="Delete this test case"
                          onClick={() => library.deleteRequestRow(i)}>{icons.trash}</button>
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="draft">
              <td className="num">{icons.plus}</td>
              <td>
                <select className="cell sel" value={draft.folder} aria-label="Folder" onChange={e => setField('folder', e.target.value)}>
                  <option value="">Top level</option>
                  {collection.folderList.map(f => <option key={f.idx.join('.')} value={f.idx.join('.')}>{f.label}</option>)}
                </select>
              </td>
              <td>
                <select className={'cell sel method m-' + draft.method} value={draft.method} aria-label="Method"
                        onChange={e => setField('method', e.target.value)}>
                  {METHODS.map(m => <option key={m}>{m}</option>)}
                </select>
              </td>
              <td>
                <input className="cell" ref={nameRef} value={draft.name} maxLength={200} placeholder="Test case name"
                       aria-label="New test case name" onChange={e => setField('name', e.target.value)} onKeyDown={addOnEnter} />
              </td>
              <td>
                <input className="cell mono" value={draft.url} maxLength={2000} placeholder="{{baseUrl}}/path"
                       aria-label="New test case URL" onChange={e => setField('url', e.target.value)} onKeyDown={addOnEnter} />
              </td>
              <td>
                <input className="cell narrow" value={draft.status} maxLength={3} placeholder="None" inputMode="numeric"
                       aria-label="Expected status code" onChange={e => setField('status', e.target.value)} onKeyDown={addOnEnter} />
              </td>
              <td className="rowact"><button className="btn sm" onClick={add}>Add</button></td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="tablehint">Edit any cell and it updates straight away. A status code adds a check that the response returns that code. Leave it empty to add the request without a test.</p>
    </>
  );
}
