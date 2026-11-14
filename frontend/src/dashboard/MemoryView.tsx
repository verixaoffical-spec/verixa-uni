/* QA Memory (UC8): what Verixa learned from earlier runs and decisions. The agents search it for similar failures and
 * for a module's bug history. A wrong entry can be removed, and is then never used again. */
import { useCallback, useEffect, useState } from 'react';
import { ApiError, qa, type MemoryItem } from './api';
import type { Link } from './connection';
import { ConnectFirst, Tag, message, when } from './qa';
import { useToast } from './Toast';

interface Props {
  hidden: boolean;
  link: Link | null;
  onGoConnect: () => void;
}

const KIND: Record<string, { text: string; cls: string }> = {
  real_bug: { text: 'Real bug', cls: 'bad' },
  temporary_error: { text: 'Temporary error', cls: 'warn' },
  test_draft: { text: 'Drafted test decision', cls: 'info' },
  ticket: { text: 'Ticket decision', cls: 'ok' },
};

export default function MemoryView({ hidden, link, onGoConnect }: Props) {
  const toast = useToast();
  const [items, setItems] = useState<MemoryItem[] | null>(null);
  const [kind, setKind] = useState('');
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setItems((await qa.memory()).items);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 401)) toast(message(err, 'QA Memory could not be loaded'));
    }
  }, [toast]);
  useEffect(() => { if (!hidden && link) load(); }, [hidden, link, load]);

  async function forget(item: MemoryItem) {
    if (!confirm('Remove this memory entry? The agents will not use it again.')) return;
    setBusy(item.id);
    try {
      await qa.forget(item.id);
      setItems(all => (all ?? []).filter(i => i.id !== item.id));
      toast('Memory entry removed');
    } catch (err) {
      toast(message(err, 'The entry could not be removed'));
    } finally {
      setBusy(null);
    }
  }

  if (!link) return <ConnectFirst hidden={hidden} what="QA Memory fills up as your test runs finish." onGoConnect={onGoConnect} />;
  const shown = (items ?? []).filter(i => !kind || i.kind === kind);

  return (
    <section hidden={hidden} className="workspace qwide">
      <article className="card">
        <header className="head">
          <h1>QA <em>Memory</em></h1>
          <p className="lead">Past failures and your decisions. The Analysis Agent counts real bugs here in a module's bug history,
            the Test Agent reruns specs that failed in a module before, and the Report Agent reads similar past failures.
            Secrets are removed before anything is saved.</p>
          <div className="qcompare-pick" style={{ marginTop: 16 }}>
            <label className="field">Show
              <select value={kind} onChange={e => setKind(e.target.value)}>
                <option value="">Everything</option>
                {Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v.text}</option>)}
              </select>
            </label>
          </div>
        </header>
        <div className="pane">
          {!items ? <div className="empty"><b>Loading</b></div> : !shown.length ? (
            <div className="empty"><b>Nothing remembered yet</b>Entries appear when runs find failures and when you decide on tickets and drafted tests.</div>
          ) : shown.map(i => (
            <div key={i.id} className="qmemrow">
              <div>
                <div className="qmemhead">
                  <Tag cls={(KIND[i.kind] || { cls: 'muted' }).cls}>{(KIND[i.kind] || { text: i.kind }).text}</Tag>
                  {i.module && <span className="mono">{i.module}</span>}
                  {i.pr_number && <span className="qmuted">PR #{i.pr_number}</span>}
                  {i.decision && <span className="qmuted">{i.decision}</span>}
                  <span className="qmuted">{when(i.created_at)}</span>
                </div>
                <pre>{i.text}</pre>
              </div>
              <button className="btn ghost sm danger" disabled={busy === i.id} onClick={() => forget(i)} aria-label={`Remove memory entry ${i.id}`}>Remove</button>
            </div>
          ))}
        </div>
      </article>
    </section>
  );
}
