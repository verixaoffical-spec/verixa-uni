// The Test Library as the dashboard sees it: the files on screen, compared with what is saved in the database.
// Every function here takes a Library and returns a new one. Nothing is changed in place, and there is no React.

import { bytes, kb } from './format';
import { LIMITS, analyseCollection, analyseSpec, invalidName, type CollectionAnalysis, type SpecAnalysis } from './validation';

export type Kind = 'pw' | 'pm';  // Playwright specs or the Postman collection
export type Status = 'new' | 'updated' | 'saved' | 'removing';

export interface SavedFile {
  name: string;
  size: number;
  text: string;
  revision: number;  // goes up on every save, so the server can spot changes made elsewhere
}

export interface SpecItem extends SpecAnalysis {
  name: string;
  size: number;
  text: string;
  removed: boolean;  // still saved, but will be deleted on confirm
}

export interface CollectionItem extends CollectionAnalysis {
  name: string;
  size: number;
  text: string;
  removed: boolean;
  before?: CollectionItem;  // what was on screen before Delete, for Undo
}

export interface Rejected {
  id: number;
  kind: Kind;
  name: string;
  reasons: string[];
}

export interface Library {
  specs: SpecItem[];
  collection: CollectionItem | null;
  rejected: Rejected[];
  saved: { specs: SavedFile[]; collection: SavedFile | null };  // what the database holds right now
}

// A file the person picked. text is null when it was not read: too large, empty, or not plain text.
export interface PickedFile {
  name: string;
  size: number;
  text: string | null;
}

export const emptyLibrary: Library = { specs: [], collection: null, rejected: [], saved: { specs: [], collection: null } };

// ---- building items ----

const makeSpec = (f: SavedFile): SpecItem => ({ name: f.name, size: f.size, text: f.text, removed: false, ...analyseSpec(f.text) });

function makeCollection(f: SavedFile): CollectionItem | null {
  const result = analyseCollection(f.text);
  return result.errors.length ? null : { name: f.name, size: f.size, text: f.text, removed: false, ...result };
}

// The library exactly as saved, for a fresh page, Discard, or after saving
export function fromSaved(specs: SavedFile[], collection: SavedFile | null): Library {
  return {
    specs: specs.map(makeSpec),
    collection: collection ? makeCollection(collection) : null,
    rejected: [],
    saved: { specs, collection },
  };
}

export const savedSpec = (lib: Library, name: string) => lib.saved.specs.find(s => s.name === name);

// ---- what changed ----

export function specStatus(lib: Library, spec: SpecItem): Status {
  if (spec.removed) return 'removing';
  const saved = savedSpec(lib, spec.name);
  return !saved ? 'new' : saved.text === spec.text ? 'saved' : 'updated';
}

export function collectionStatus(lib: Library, col: CollectionItem): Status {
  if (col.removed) return 'removing';
  const saved = lib.saved.collection;
  return !saved ? 'new' : saved.name === col.name && saved.text === col.text ? 'saved' : 'updated';
}

const isChanged = (status: Status) => status === 'new' || status === 'updated';

export function pendingChanges(lib: Library) {
  const col = lib.collection;
  return {
    upsert: lib.specs.filter(s => isChanged(specStatus(lib, s))),
    remove: lib.specs.filter(s => s.removed && savedSpec(lib, s.name)),
    collection: col && isChanged(collectionStatus(lib, col)) ? col : null,
    removeCollection: !!(col?.removed && lib.saved.collection),
  };
}

export function changeCount(lib: Library): number {
  const p = pendingChanges(lib);
  return p.upsert.length + p.remove.length + (p.collection ? 1 : 0) + (p.removeCollection ? 1 : 0);
}

// The body for POST /api/library/apply. Each file carries the revision this page last saw.
export function applyRequest(lib: Library) {
  const p = pendingChanges(lib);
  const revisionOf = (name: string) => savedSpec(lib, name)?.revision ?? null;
  const savedCol = lib.saved.collection;
  return {
    specs: p.upsert.map(s => ({ name: s.name, text: s.text, revision: revisionOf(s.name) })),
    delete_specs: p.remove.map(s => ({ name: s.name, revision: revisionOf(s.name) })),
    collection: p.collection && { name: p.collection.name, text: p.collection.text, revision: savedCol?.revision ?? null },
    delete_collection: p.removeCollection ? { revision: savedCol!.revision } : null,
  };
}

// ---- rejected files ----

let lastRejectedId = 0;

// Adds a rejected file, replacing an older rejection of the same file
function reject(list: Rejected[], kind: Kind, name: string, reasons: string[]): Rejected[] {
  return [...list.filter(r => !(r.kind === kind && r.name === name)), { id: ++lastRejectedId, kind, name, reasons }];
}

export const dismissRejected = (lib: Library, id: number): Library =>
  ({ ...lib, rejected: lib.rejected.filter(r => r.id !== id) });

// ---- adding files ----

// Puts a checked spec into the list. It may replace a file, or take over a removed entry with the same name.
function putSpec(lib: Library, specs: SpecItem[], item: SpecItem, replacing?: SpecItem): SpecItem[] {
  const list = specs.filter(s => s.name !== item.name || s === replacing);
  if (!replacing) return [...list, item];
  const i = list.indexOf(replacing);
  if (replacing.name === item.name) list.splice(i, 1, item);
  else if (savedSpec(lib, replacing.name)) list.splice(i, 1, item, { ...replacing, removed: true });  // keep the old one, marked for removal
  else list.splice(i, 1, item);
  return list;
}

export function addSpecFiles(lib: Library, files: PickedFile[], replacingName?: string): Library {
  let specs = lib.specs, rejected = lib.rejected;
  for (const f of files) {
    const replacing = replacingName ? specs.find(s => s.name === replacingName) : undefined;
    const why: string[] = [];

    const badName = invalidName(f.name);
    if (badName) why.push(badName);
    else if (!f.name.endsWith('.spec.ts')) why.push(/\.(jsx?|mjs|cjs)$/.test(f.name) ? 'JavaScript specs are not accepted. Use TypeScript (.spec.ts)' : 'Only .spec.ts files are accepted');
    else if (f.name === '.spec.ts') why.push('File name needs a name before .spec.ts');

    if (!f.size) why.push('File is empty');
    else if (f.size > LIMITS.specBytes) why.push(`File is ${kb(f.size)}. The limit is ${kb(LIMITS.specBytes)}`);

    const others = specs.filter(s => s !== replacing);
    const clash = others.find(s => s.name === f.name);
    const lookalike = others.find(s => !s.removed && s.name !== f.name && s.name.toLowerCase() === f.name.toLowerCase());
    if (lookalike) why.push(`Differs only by letter case from "${lookalike.name}"`);
    else if (clash && !clash.removed) why.push('A spec with this name is already in the list. Use Replace file on it to update it');
    else if (!clash && !replacing && specs.filter(s => !s.removed).length >= LIMITS.maxSpecs) why.push(`Limit of ${LIMITS.maxSpecs} spec files reached`);

    let analysis: SpecAnalysis | null = null;
    if (!why.length) {
      if (f.text === null) why.push('Could not read this file as plain text');
      else {
        analysis = analyseSpec(f.text);
        why.push(...analysis.errors);
      }
    }

    if (why.length || !analysis) {
      rejected = reject(rejected, 'pw', f.name, why);
      continue;
    }
    rejected = rejected.filter(r => !(r.kind === 'pw' && r.name === f.name));
    specs = putSpec(lib, specs, { name: f.name, size: f.size, text: f.text!, removed: false, ...analysis }, replacing);
  }
  return { ...lib, specs, rejected };
}

export function addCollectionFile(lib: Library, files: PickedFile[]): Library {
  let rejected = lib.rejected;
  for (const extra of files.slice(1)) rejected = reject(rejected, 'pm', extra.name, ['Only one collection can be added at a time']);
  const f = files[0];
  if (!f) return { ...lib, rejected };

  const why: string[] = [];
  const badName = invalidName(f.name);
  if (badName) why.push(badName);
  else if (!f.name.endsWith('.json')) why.push('Only .json collection exports are accepted');
  if (!f.size) why.push('File is empty');
  else if (f.size > LIMITS.collectionBytes) why.push(`File is ${kb(f.size)}. The limit is ${kb(LIMITS.collectionBytes)}`);

  let analysis: CollectionAnalysis | null = null;
  if (!why.length) {
    if (f.text === null) why.push('Could not read this file as plain text');
    else {
      analysis = analyseCollection(f.text);
      why.push(...analysis.errors);
    }
  }

  if (why.length || !analysis) return { ...lib, rejected: reject(rejected, 'pm', f.name, why) };
  return {
    ...lib,
    rejected: rejected.filter(r => r.kind !== 'pm'),
    collection: { name: f.name, size: f.size, text: f.text!, removed: false, ...analysis },
  };
}

// ---- removing files ----

export function removeSpec(lib: Library, name: string): Library {
  // A saved spec stays on screen, marked for removal. A new one simply goes.
  if (savedSpec(lib, name)) return { ...lib, specs: lib.specs.map(s => (s.name === name ? { ...s, removed: true } : s)) };
  return { ...lib, specs: lib.specs.filter(s => s.name !== name) };
}

export const restoreSpec = (lib: Library, name: string): Library =>
  ({ ...lib, specs: lib.specs.map(s => (s.name === name ? { ...s, removed: false } : s)) });

export function insertSpec(lib: Library, index: number, spec: SpecItem): Library {
  const specs = [...lib.specs];
  specs.splice(index, 0, spec);
  return { ...lib, specs };
}

export function removeCollection(lib: Library): Library {
  const col = lib.collection;
  if (!col) return lib;
  // A saved collection shows as the saved copy, marked for removal
  const saved = lib.saved.collection && makeCollection(lib.saved.collection);
  return { ...lib, collection: saved ? { ...saved, removed: true, before: col } : null };
}

export function restoreCollection(lib: Library): Library {
  return lib.collection?.removed ? { ...lib, collection: lib.collection.before ?? null } : lib;
}

// ---- editing file text ----

// Replaces a spec's text. Throws if the new text would not pass the checks.
export function withSpecText(lib: Library, name: string, text: string): Library {
  if (bytes(text) > LIMITS.specBytes) throw new Error(`The file would be larger than ${kb(LIMITS.specBytes)}`);
  const result = analyseSpec(text);
  if (result.errors.length) {
    throw new Error(result.tests.length
      ? 'That change would break the file, so it was not applied'
      : 'A spec needs at least one test case. Delete the whole file instead');
  }
  return {
    ...lib,
    specs: lib.specs.map(s => (s.name === name ? { ...s, text, size: bytes(text), tests: result.tests, warnings: result.warnings } : s)),
  };
}

// Replaces the collection's text. Throws if the new text would not pass the checks.
export function withCollectionText(lib: Library, text: string): Library {
  if (!lib.collection) return lib;
  if (bytes(text) > LIMITS.collectionBytes) throw new Error(`The collection would be larger than ${kb(LIMITS.collectionBytes)}`);
  const result = analyseCollection(text);
  if (result.errors.length) {
    throw new Error(result.errors.includes('Collection has no requests')
      ? 'A collection needs at least one request. Delete the collection instead'
      : result.errors[0]);
  }
  return { ...lib, collection: { ...lib.collection, text, size: bytes(text), ...result } };
}

// ---- after the server refused some files ----

// The server runs the same checks again. Files it refused go back to their saved copy, or off the list if new.
export function applyServerRejections(lib: Library, files: Record<string, string[]>): Library {
  let next = lib;
  for (const [name, reasons] of Object.entries(files)) {
    const isCollection = next.collection?.name === name;
    next = { ...next, rejected: reject(next.rejected, isCollection ? 'pm' : 'pw', name, reasons) };
    if (isCollection) {
      next = { ...next, collection: next.saved.collection && makeCollection(next.saved.collection) };
    } else {
      const saved = savedSpec(next, name);
      next = { ...next, specs: saved ? next.specs.map(s => (s.name === name ? makeSpec(saved) : s)) : next.specs.filter(s => s.name !== name) };
    }
  }
  return next;
}
