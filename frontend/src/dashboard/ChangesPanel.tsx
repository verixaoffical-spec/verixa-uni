import { BADGE } from './FileCards';
import { plural } from './format';
import { collectionStatus, specStatus, type Library, type Status } from './library';

const ORDER: Record<Status, number> = { removing: 0, updated: 1, new: 2, saved: 3 };

// The side panel listing every unsaved change, most important first
export default function ChangesPanel({ lib }: { lib: Library }) {
  const changes: { status: Status; title: string; sub: string }[] = [];
  for (const s of lib.specs) {
    const status = specStatus(lib, s);
    if (status !== 'saved') changes.push({ status, title: s.name, sub: plural(s.tests.length, 'test') });
  }
  if (lib.collection) {
    const status = collectionStatus(lib, lib.collection);
    if (status !== 'saved') changes.push({ status, title: lib.collection.name, sub: plural(lib.collection.requests.length, 'request') });
  }
  changes.sort((a, b) => ORDER[a.status] - ORDER[b.status]);

  const saved = `${plural(lib.saved.specs.length, 'spec')} and ${lib.saved.collection ? '1 collection' : 'no collection'} saved`;

  return (
    <aside className="side">
      <div className="panel">
        <div className="ph">Changes<b>{changes.length}</b></div>
        {!changes.length && <p className="phint">Add, replace or delete files. Each change appears here and is saved when you confirm.</p>}
        <ol className="timeline">
          {changes.map(c => (
            <li key={c.status + c.title} className={'node ' + c.status}>
              <i className="dot"></i>
              <div className="nbody"><span className="nst">{BADGE[c.status]}</span><b>{c.title}</b><small>{c.sub}</small></div>
            </li>
          ))}
          <li className="node base">
            <i className="dot"></i>
            <div className="nbody"><b>Test Library</b><small>{saved}</small></div>
          </li>
        </ol>
      </div>
    </aside>
  );
}
