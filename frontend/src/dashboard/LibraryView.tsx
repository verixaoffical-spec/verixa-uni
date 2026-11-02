import { useRef, useState } from 'react';
import { CollectionCard, RejectedCard, SpecCard } from './FileCards';
import ChangesPanel from './ChangesPanel';
import DropZone from './DropZone';
import { icons } from './icons';
import { Chip, hookLabel, type HookState, type Link } from './connection';
import { isMac, plural } from './format';
import { collectionStatus, specStatus, type Kind } from './library';
import type { LibraryActions } from './useLibrary';

interface Props {
  hidden: boolean;
  link: Link | null;
  hook: HookState;
  library: LibraryActions;
  onGoConnect: () => void;
}

const SPEC_ACCEPT = '.ts';
const COLLECTION_ACCEPT = '.json,application/json';

export default function LibraryView({ hidden, link, hook, library, onGoConnect }: Props) {
  const [tab, setTab] = useState<Kind>('pw');
  const [replacing, setReplacing] = useState<{ kind: Kind; name: string } | null>(null);
  const specInput = useRef<HTMLInputElement>(null);
  const collectionInput = useRef<HTMLInputElement>(null);
  const replaceInput = useRef<HTMLInputElement>(null);
  const { lib, busy, conflict, changes } = library;

  if (!link) {
    return (
      <section hidden={hidden} className="lock-wrap">
        <article className="lock">
          <span className="lock-ico">{icons.integrations}</span>
          <h2>Connect a repository first</h2>
          <p>Your Test Library belongs to a repository and a Jira project. Link GitHub and Jira once to set it up.</p>
          <div><button className="btn" onClick={onGoConnect}>Go to Integrations</button></div>
        </article>
      </section>
    );
  }

  function addSpecs(files: File[], replacingName?: string) {
    setTab('pw');
    library.addSpecs(files, replacingName);
  }

  function addCollection(files: File[]) {
    setTab('pm');
    library.addCollection(files);
  }

  // "Replace file" opens a file picker. The chosen file then takes the old one's place.
  function startReplace(kind: Kind, name: string) {
    setReplacing({ kind, name });
    const input = replaceInput.current!;
    input.accept = kind === 'pw' ? SPEC_ACCEPT : COLLECTION_ACCEPT;
    input.click();
  }

  function onReplaceFile(file: File | undefined) {
    if (!file || !replacing) return;
    if (replacing.kind === 'pw') addSpecs([file], replacing.name);
    else addCollection([file]);
    setReplacing(null);
  }

  const liveSpecs = lib.specs.filter(s => !s.removed);
  const testCount = liveSpecs.reduce((n, s) => n + s.tests.length, 0);
  const hasCollection = !!lib.collection && !lib.collection.removed;
  const rejected = (kind: Kind) => lib.rejected.filter(r => r.kind === kind);
  const rejectedCards = (kind: Kind) => rejected(kind).map(r => (
    <RejectedCard key={r.id} item={r} onDismiss={() => library.dismiss(r.id)}
                  onRetry={() => (kind === 'pw' ? specInput : collectionInput).current?.click()} />
  ));

  const tabButton = (kind: Kind, label: string, count: number) => {
    const bad = rejected(kind).length;
    return (
      <button className="tab" role="tab" aria-selected={tab === kind} onClick={() => setTab(kind)}>
        {label}<b>{count}</b>{bad > 0 && <b className="bad">{bad} rejected</b>}
      </button>
    );
  };

  const steps = (show: boolean, first: string) => (
    <div className={'how' + (show ? ' on' : '')}>
      <div><b>1</b>{first}</div><div><b>2</b>Review the checks</div><div><b>3</b>Confirm import</div>
    </div>
  );

  const saveState = busy ? 'busy' : changes ? 'dirty' : '';

  return (
    <section hidden={hidden}>
      <div className="workspace">
        <article className="card">
          <div className="head">
            <h1>Your Test <em>Library</em></h1>
            <p className="lead">Add your Playwright specs and Postman collection. Every file is checked first, and nothing is saved until you confirm.</p>
            <div className="chips">
              <Chip on={true}><span className="mono">{link.repo}</span></Chip>
              <Chip on={true}>{link.project}</Chip>
              <Chip on={hook === 'ok'}>{hookLabel(hook)}</Chip>
            </div>
          </div>

          {conflict && (
            <div className="banner" role="alert">
              <span>This library was changed somewhere else, in another tab or by a teammate. Your changes were not saved.</span>
              <button className="btn sm" onClick={library.reloadLatest}>Reload latest</button>
            </div>
          )}

          <div className="tabs" role="tablist">
            {tabButton('pw', 'Playwright specs', liveSpecs.length)}
            {tabButton('pm', 'Postman collection', hasCollection ? 1 : 0)}
          </div>

          <div className="pane" hidden={tab !== 'pw'}>
            <DropZone big={!lib.specs.length} multiple accept={SPEC_ACCEPT} inputRef={specInput} onFiles={files => addSpecs(files)}
                      title={['Drop your Playwright specs here', 'Add more specs']}
                      text={['or click to browse. Each file is checked the moment it lands.',
                             'Drop .spec.ts files or browse. TypeScript only, 500 KB each, up to 50 files.']}
                      rules={['.spec.ts only', '500 KB per file', 'Up to 50 files']} />
            {steps(!lib.specs.length, 'Add your files')}
            {rejectedCards('pw')}
            {lib.specs.length > 0 && <p className="sumline">{plural(liveSpecs.length, 'file')}, {plural(testCount, 'test')} found</p>}
            {lib.specs.map(s => (
              <SpecCard key={s.name} spec={s} status={specStatus(lib, s)} library={library} onReplace={() => startReplace('pw', s.name)} />
            ))}
          </div>

          <div className="pane" hidden={tab !== 'pm'}>
            <DropZone big={!lib.collection} accept={COLLECTION_ACCEPT} inputRef={collectionInput} onFiles={addCollection}
                      title={['Drop your Postman collection here', 'Add a different collection']}
                      text={['or click to browse. Export it from Postman as a collection .json file.',
                             'Drop a collection .json or browse. It will replace the current one.']}
                      rules={['Collection v2.0 or v2.1', '5 MB at most', 'One collection']} />
            {steps(!lib.collection, 'Add your file')}
            {rejectedCards('pm')}
            {lib.collection && (
              <CollectionCard collection={lib.collection} status={collectionStatus(lib, lib.collection)} library={library}
                              onReplace={() => startReplace('pm', 'col')} />
            )}
          </div>

          <input className="sr" type="file" ref={replaceInput} tabIndex={-1} aria-hidden="true"
                 onChange={e => { onReplaceFile(e.target.files?.[0]); e.target.value = ''; }} />

          <div className="bar">
            <span className={'state ' + saveState}>
              <i></i><span>{busy ? 'Saving…' : changes ? plural(changes, 'unsaved change') : 'All changes saved'}</span>
            </span>
            <div className="bar-actions">
              {changes > 0 && <button className="btn ghost" disabled={busy} onClick={library.discard}>Discard changes</button>}
              <button className="btn" disabled={!changes || busy} onClick={library.confirm}>
                <span>{busy ? 'Importing…' : 'Confirm import'}</span><kbd>{isMac ? '⌘ ↵' : 'Ctrl ↵'}</kbd>
              </button>
            </div>
          </div>
        </article>

        <ChangesPanel lib={lib} />
      </div>
    </section>
  );
}
