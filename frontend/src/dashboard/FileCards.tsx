import type { ReactNode } from 'react';
import { icons } from './icons';
import { kb, plural } from './format';
import SpecTable from './SpecTable';
import CollectionTable from './CollectionTable';
import type { CollectionItem, Rejected, SpecItem, Status } from './library';
import type { LibraryActions } from './useLibrary';

export const BADGE: Record<Status | 'rejected', string> = {
  new: 'New', updated: 'Updated', saved: 'In library', removing: 'Removing', rejected: 'Rejected',
};

const MAX_SOURCE_LINES = 300;

function Badge({ status }: { status: Status | 'rejected' }) {
  return <span className={'badge ' + status}>{BADGE[status]}</span>;
}

// The file's text with line numbers, folded away until opened
function Source({ text }: { text: string }) {
  const lines = text.split('\n'), shown = lines.slice(0, MAX_SOURCE_LINES);
  return (
    <details>
      <summary>View source</summary>
      <div className="code">
        <pre aria-hidden="true">{shown.map((_, i) => i + 1).join('\n')}</pre>
        <pre>{shown.join('\n')}</pre>
      </div>
      {lines.length > MAX_SOURCE_LINES && <p className="more">Showing the first {MAX_SOURCE_LINES} of {lines.length} lines</p>}
    </details>
  );
}

function Warnings({ list }: { list: string[] }) {
  return <>{list.map(w => <p key={w} className="warn">{w}</p>)}</>;
}

interface FileCardProps {
  icon: ReactNode;
  title: string;
  meta: string;
  status: Status;
  onReplace: () => void;
  onDelete: () => void;
  children: ReactNode;
}

function FileCard({ icon, title, meta, status, onReplace, onDelete, children }: FileCardProps) {
  return (
    <article className={'file st-' + status}>
      <header>
        <span className="fi">{icon}</span>
        <div className="fmeta"><b className="fname">{title}</b><small>{meta}</small></div>
        <Badge status={status} />
        <div className="acts">
          <button className="btn ghost sm" title="Upload a corrected file in its place" onClick={onReplace}>{icons.replace}Replace file</button>
          <button className="btn ghost sm danger" onClick={onDelete}>{icons.trash}Delete file</button>
        </div>
      </header>
      {children}
    </article>
  );
}

// A saved file that will be deleted when the person confirms
export function RemovedCard({ name, icon, onUndo }: { name: string; icon: ReactNode; onUndo: () => void }) {
  return (
    <article className="file removed">
      <header>
        <span className="fi">{icon}</span>
        <div className="fmeta"><b className="fname struck">{name}</b><small>Will be removed when you confirm</small></div>
        <Badge status="removing" />
        <div className="acts"><button className="btn ghost sm" onClick={onUndo}>{icons.undo}Undo</button></div>
      </header>
    </article>
  );
}

interface SpecCardProps {
  spec: SpecItem;
  status: Status;
  library: LibraryActions;
  onReplace: () => void;
}

export function SpecCard({ spec, status, library, onReplace }: SpecCardProps) {
  if (spec.removed) return <RemovedCard name={spec.name} icon={icons.file} onUndo={() => library.restoreSpec(spec.name)} />;
  return (
    <FileCard icon={icons.file} title={spec.name} meta={`${plural(spec.tests.length, 'test case')}, ${kb(spec.size)}`}
              status={status} onReplace={onReplace} onDelete={() => library.removeSpec(spec.name)}>
      <SpecTable spec={spec} library={library} />
      <Warnings list={spec.warnings} />
      <Source text={spec.text} />
    </FileCard>
  );
}

interface CollectionCardProps {
  collection: CollectionItem;
  status: Status;
  library: LibraryActions;
  onReplace: () => void;
}

export function CollectionCard({ collection: c, status, library, onReplace }: CollectionCardProps) {
  if (c.removed) return <RemovedCard name={c.name} icon={icons.braces} onUndo={library.restoreCollection} />;
  const meta = `${c.name}, ${c.schema}, ${plural(c.requests.length, 'request')}, ${plural(c.folders, 'folder')}, ${kb(c.size)}`;
  return (
    <FileCard icon={icons.braces} title={c.json.info.name} meta={meta}
              status={status} onReplace={onReplace} onDelete={library.removeCollection}>
      <CollectionTable collection={c} library={library} />
      <Warnings list={c.warnings} />
      <Source text={c.text} />
    </FileCard>
  );
}

// A file that did not pass the checks, with the reasons
export function RejectedCard({ item, onRetry, onDismiss }: { item: Rejected; onRetry: () => void; onDismiss: () => void }) {
  return (
    <article className="rejcard">
      <header>
        <span className="fi">{icons.alert}</span>
        <div className="fmeta"><b className="fname">{item.name}</b><small>Not added. Fix the file and try again.</small></div>
        <Badge status="rejected" />
        <div className="acts">
          <button className="btn ghost sm" onClick={onRetry}>Choose another file</button>
          <button className="btn ghost sm" onClick={onDismiss}>Dismiss</button>
        </div>
      </header>
      <ul className="why">{item.reasons.map(r => <li key={r}>{r}</li>)}</ul>
    </article>
  );
}
