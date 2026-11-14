/* Jira tickets (UC7): every draft the Report Agent wrote, waiting for the tester's decision, and every filed one. */
import { useCallback, useEffect, useState } from 'react';
import { ApiError, qa, type Ticket } from './api';
import { Chip, type Link } from './connection';
import { ConnectFirst, Tag, TicketEditor, when } from './qa';

interface Props {
  hidden: boolean;
  link: Link | null;
  onGoConnect: () => void;
  onOpenRun: (runId: number) => void;
}

const FILTERS = ['Drafted', 'Filed', 'Rejected'] as const;

export default function TicketsView({ hidden, link, onGoConnect, onOpenRun }: Props) {
  const [items, setItems] = useState<Ticket[] | null>(null);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('Drafted');
  const [open, setOpen] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      setItems((await qa.tickets()).items);
      setFailed(false);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 401)) setFailed(true);
    }
  }, []);
  useEffect(() => { if (!hidden && link) load(); }, [hidden, link, load]);

  if (!link) return <ConnectFirst hidden={hidden} what="Tickets are drafted from real bugs found by test runs." onGoConnect={onGoConnect} />;
  const shown = (items ?? []).filter(t => t.status === filter);
  const count = (s: string) => (items ?? []).filter(t => t.status === s).length;

  return (
    <section hidden={hidden} className="workspace qwide">
      <article className="card">
        <header className="head">
          <h1>Jira <em>Tickets</em></h1>
          <p className="lead">The Report Agent drafts a ticket with proof for every real bug. Review it, correct it if needed,
            and approve it. Jira gets nothing until you do.</p>
          <div className="chips"><Chip on>Jira {link.project}</Chip></div>
        </header>
        <div className="tabs" role="tablist">
          {FILTERS.map(f => (
            <button key={f} className="tab" role="tab" aria-selected={filter === f} onClick={() => { setFilter(f); setOpen(null); }}>
              {f === 'Drafted' ? 'Waiting for you' : f}<b>{count(f)}</b>
            </button>
          ))}
        </div>
        <div className="pane">
          {failed && <div className="warnbox">Could not reach the Verixa server.</div>}
          {!items ? <div className="empty"><b>Loading</b></div>
            : !shown.length ? (
              <div className="empty"><b>{filter === 'Drafted' ? 'No tickets waiting' : `No ${filter.toLowerCase()} tickets`}</b>
                {filter === 'Drafted' ? 'Drafts appear here when a run finds a real bug.' : ''}</div>
            ) : shown.map(t => (
              <div key={t.id} className={'qcard' + (open === t.id ? ' open' : '')}>
                <button className="qcard-head" onClick={() => setOpen(open === t.id ? null : t.id)} aria-expanded={open === t.id}>
                  <span className="qtitle">{t.title}</span>
                  <span className="qmuted">{t.priority} priority · {when(t.filed_at || t.created_at)}</span>
                  {t.flagged && <Tag cls="warn">needs review</Tag>}
                  {t.jira_key && <Tag cls="ok">{t.jira_key}</Tag>}
                </button>
                {open === t.id && (
                  <div className="qcard-body">
                    {t.run_id && <button className="btn ghost sm" onClick={() => onOpenRun(t.run_id!)}>See the failure and its proof in run #{t.run_id}</button>}
                    <TicketEditor ticket={t} onChange={n => setItems(all => (all ?? []).map(x => (x.id === n.id ? n : x)))} />
                  </div>
                )}
              </div>
            ))}
        </div>
      </article>
    </section>
  );
}
