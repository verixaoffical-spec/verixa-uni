// Holds the Test Library on screen and every action the Library page can take on it.
// The rules themselves live in library.ts and editing.ts. This file adds React state, messages and Undo.

import { useRef, useState } from 'react';
import { ApiError, api, type Session } from './api';
import { plural } from './format';
import { useToast } from './Toast';
import { LIMITS } from './validation';
import { addRequest, appendTest, deleteRequest, deleteTest, editRequest, renameTest, setTestMode,
         type NewRequest, type RequestField } from './editing';
import * as L from './library';

// Reads a picked file as text. Too large, empty or binary files are not read, and get null.
async function readFile(file: File, limit: number): Promise<L.PickedFile> {
  let text: string | null = null;
  if (file.size && file.size <= limit) {
    try {
      text = await file.text();
      if (/\u0000|�/.test(text)) text = null;
    } catch {
      text = null;
    }
  }
  return { name: file.name, size: file.size, text };
}

export function useLibrary() {
  const toast = useToast();
  const [lib, setLib] = useState<L.Library>(L.emptyLibrary);
  const [busy, setBusy] = useState(false);          // saving right now
  const [conflict, setConflict] = useState(false);  // someone else changed the library first
  const latest = useRef(lib);

  // Applies a change to the library. If the change throws, nothing changes and its message is shown instead.
  function change(update: (current: L.Library) => L.Library): boolean {
    try {
      latest.current = update(latest.current);
      setLib(latest.current);
      return true;
    } catch (err) {
      toast((err as Error).message);
      return false;
    }
  }

  const specNamed = (name: string) => latest.current.specs.find(s => s.name === name)!;
  const undoable = (message: string, undo: () => void) => toast(message, { label: 'Undo', run: undo });
  const showError = (err: unknown) => {
    if (!(err instanceof ApiError && err.status === 401)) toast((err as Error).message);  // a 401 has its own message
  };

  function load(session: Session) {
    change(() => L.fromSaved(session.specs, session.collection));
    setConflict(false);
  }

  // ---- files ----

  async function addSpecs(files: File[], replacing?: string) {
    const picked = await Promise.all(files.map(f => readFile(f, LIMITS.specBytes)));
    change(l => L.addSpecFiles(l, picked, replacing));
  }

  async function addCollection(files: File[]) {
    const picked = await Promise.all(files.slice(0, 1).map(f => readFile(f, LIMITS.collectionBytes)));
    const extras = files.slice(1).map(f => ({ name: f.name, size: f.size, text: null }));
    change(l => L.addCollectionFile(l, [...picked, ...extras]));
  }

  function removeSpec(name: string) {
    const index = latest.current.specs.findIndex(s => s.name === name), spec = latest.current.specs[index];
    if (!spec) return;
    change(l => L.removeSpec(l, name));
    if (L.savedSpec(latest.current, name)) undoable(`${name} will be removed when you confirm`, () => change(l => L.restoreSpec(l, name)));
    else undoable(`Removed ${name}`, () => change(l => L.insertSpec(l, index, spec)));
  }

  function removeCollection() {
    const before = latest.current.collection;
    if (!before) return;
    change(L.removeCollection);
    if (latest.current.collection) undoable('The collection will be removed when you confirm', () => change(L.restoreCollection));
    else undoable('Removed the collection', () => change(l => ({ ...l, collection: before })));
  }

  // ---- cells in the tables ----
  // Each returns true when the edit was applied, so the cell knows whether to keep the new value.

  function editTest(specName: string, row: number, column: 'title' | 'mode', value: string): boolean {
    return change(l => {
      const spec = l.specs.find(s => s.name === specName)!, test = spec.tests[row];
      const text = column === 'title' ? renameTest(spec.text, test, value) : setTestMode(spec.text, test, value);
      return text === spec.text ? l : L.withSpecText(l, specName, text);
    });
  }

  function editRequestCell(row: number, field: RequestField, value: string): boolean {
    return change(l => {
      const col = l.collection!;
      const text = editRequest(col.text, col.requests[row].path, field, value);
      return text === col.text ? l : L.withCollectionText(l, text);
    });
  }

  function addTest(specName: string, title: string): boolean {
    const before = specNamed(specName).text;
    const added = change(l => L.withSpecText(l, specName, appendTest(before, title)));
    if (added) undoable('Test case added', () => change(l => L.withSpecText(l, specName, before)));
    return added;
  }

  function deleteTestRow(specName: string, row: number) {
    const spec = specNamed(specName), before = spec.text;
    if (change(l => L.withSpecText(l, specName, deleteTest(before, spec.tests[row])))) {
      undoable('Test case deleted', () => change(l => L.withSpecText(l, specName, before)));
    }
  }

  function addRequestRow(row: NewRequest): boolean {
    const before = latest.current.collection!.text;
    const added = change(l => L.withCollectionText(l, addRequest(before, row)));
    if (added) undoable('Test case added', () => change(l => L.withCollectionText(l, before)));
    return added;
  }

  function deleteRequestRow(row: number) {
    const col = latest.current.collection!, before = col.text;
    if (change(l => L.withCollectionText(l, deleteRequest(before, col.requests[row].path)))) {
      undoable('Test case deleted', () => change(l => L.withCollectionText(l, before)));
    }
  }

  // ---- the whole library ----

  function discard() {
    change(l => L.fromSaved(l.saved.specs, l.saved.collection));
    setConflict(false);
    toast('Changes discarded');
  }

  async function reloadLatest() {
    try {
      load(await api.session());
      toast('Loaded the latest library');
    } catch (err) {
      showError(err);
    }
  }

  // Sends every change in one request. The server applies all of it or none of it.
  async function confirm() {
    const current = latest.current, p = L.pendingChanges(current);
    if (!L.changeCount(current) || busy) return;
    setBusy(true);
    try {
      await api.applyLibrary(L.applyRequest(current));
      load(await api.session());
      const parts = [];
      if (p.upsert.length) parts.push(`${plural(p.upsert.length, 'spec')} saved`);
      if (p.collection) parts.push('collection saved');
      if (p.remove.length) parts.push(`${p.remove.length} removed`);
      if (p.removeCollection) parts.push('collection removed');
      toast(parts.join(', '));
    } catch (err) {
      const detail = err instanceof ApiError ? err.detail : null;
      if (err instanceof ApiError && err.status === 409 && detail?.conflicts) {
        setConflict(true);
        toast('Nothing was saved because the library changed elsewhere');
      } else if (detail?.files) {
        change(l => L.applyServerRejections(l, detail.files));
        toast('The server rejected some files');
      } else {
        showError(err);
      }
    }
    setBusy(false);
  }

  return {
    lib, busy, conflict,
    changes: L.changeCount(lib),
    load, addSpecs, addCollection, removeSpec, removeCollection,
    restoreSpec: (name: string) => change(l => L.restoreSpec(l, name)),
    restoreCollection: () => change(L.restoreCollection),
    dismiss: (id: number) => change(l => L.dismissRejected(l, id)),
    editTest, editRequestCell, addTest, deleteTestRow, addRequestRow, deleteRequestRow,
    discard, reloadLatest, confirm,
  };
}

export type LibraryActions = ReturnType<typeof useLibrary>;
