/* Test Runs (UC4, UC5, UC6, UC7, UC9, UC10): every run with its results, the proof of each failure, the ticket
 * drafts, suggested fixes, drafted tests, and a comparison of two runs. Values all come from the server. */
import { Fragment, useCallback, useEffect, useState } from 'react';
import { ApiError, qa, type Comparison, type Outcome, type Result, type Run, type RunDetail } from './api';
import { Chip, type Link } from './connection';
import { ConnectFirst, DraftCard, EvidencePanel, FixPanel, OUTCOME, RUN_STATUS, Tag, TicketEditor, message, took, when } from './qa';
import { useToast } from './Toast';

interface Props {
  hidden: boolean;
  link: Link | null;
  openRun: { id: number } | null;
  onGoConnect: () => void;
}

const FILTERS: (Outcome | 'all' | 'failed')[] = ['all', 'failed', 'real_bug', 'temporary_error', 'deployment_pending', 'passed', 'skipped'];
const COMPARE_TAG: Record<string, string> = {
  'new failure': 'bad', 'still failing': 'warn', fixed: 'ok', 'still passing': 'muted', 'new test': 'info',
  'removed test': 'muted', pending: 'info', skipped: 'muted',
};

function Counts({ run }: { run: Run }) {
  const tiles: [string, number, string][] = [
    ['Passed', run.counts.passed, 'ok'], ['Real bugs', run.counts.real_bug, 'bad'],
    ['Temporary errors', run.counts.temporary_error, 'warn'], ['Deployment pending', run.counts.deployment_pending, 'info'],
    ['Retried', run.counts.retried, 'muted'],
  ];
  return (
    <div className="qcounts">
      {tiles.map(([label, value, cls]) => <div key={label} className={'qcount ' + cls}><b>{value}</b><span>{label}</span></div>)}
    </div>
  );
}

function RunDetailView({ detail, onDetail }: { detail: RunDetail; onDetail: (d: RunDetail) => void }) {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all');
  const [open, setOpen] = useState<number | null>(null);
  const { run, results, tickets, fixes, drafts } = detail;
  const shown = results.filter(r => filter === 'all' || r.outcome === filter ||
    (filter === 'failed' && (r.outcome === 'real_bug' || r.outcome === 'temporary_error')));
  const count = (f: (typeof FILTERS)[number]) =>
    f === 'all' ? results.length : f === 'failed' ? run.counts.real_bug + run.counts.temporary_error : run.counts[f];

  return (
    <div className="qdetail">
      <div className="qsummary">
        <div>
          <h2>Run #{run.id} <span className="qmuted">for PR #{run.pr_number}</span></h2>
          <p className="qmuted">
            Started {when(run.started_at)}{run.started_by ? ` by ${run.started_by}` : ''}
            {run.ended_at ? `, took ${took(run.started_at, run.ended_at)}` : ''} · staging <span className="mono">{run.staging_url}</span>
          </p>
          {run.selection.reason && <p className="qmuted">Test Agent: {run.selection.reason}</p>}
        </div>
        <Tag cls={RUN_STATUS[run.status].cls}>{RUN_STATUS[run.status].text}</Tag>
      </div>
      {run.status === 'running' && <div className="qprogress"><i></i>{run.step || 'Working'}…</div>}
      {run.error && <div className="warnbox" role="alert">{run.error}</div>}
      {run.status === 'flagged' && <div className="warnbox">The Manager agent could not accept some agent output after every attempt. Check the flagged items below.</div>}
      <Counts run={run} />

      {!!results.length && (
        <>
          <div className="qfilters" role="tablist" aria-label="Filter results">
            {FILTERS.map(f => (
              <button key={f} role="tab" aria-selected={filter === f} className={'qfilter' + (filter === f ? ' on' : '')}
                      onClick={() => setFilter(f)} disabled={!count(f) && f !== 'all'}>
                {f === 'all' ? 'All' : f === 'failed' ? 'Failed' : OUTCOME[f].text} <b>{count(f)}</b>
              </button>
            ))}
          </div>
          <div className="tablewrap qtable">
            <table className="grid">
              <thead><tr><th>Test</th><th>Tool</th><th>Result</th><th className="num">Time</th></tr></thead>
              <tbody>
                {shown.map(r => {
                  const ticket = tickets.find(t => t.result_id === r.id);
                  return (
                    <Fragment key={r.id}>
                      <tr className={'qres' + (open === r.id ? ' open' : '')} tabIndex={0} aria-expanded={open === r.id}
                          onClick={() => setOpen(open === r.id ? null : r.id)}
                          onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(open === r.id ? null : r.id); } }}>
                        <td><div className="qtitle">{r.title}</div><div className="qmuted mono">{r.file}</div></td>
                        <td>{r.kind === 'playwright' ? 'UI' : 'API'}</td>
                        <td>
                          <Tag cls={OUTCOME[r.outcome].cls}>{OUTCOME[r.outcome].text}</Tag>
                          {r.retried && <span className="qmuted"> retried</span>}
                          {ticket && <span className="qmuted"> · ticket {ticket.status.toLowerCase()}</span>}
                        </td>
                        <td className="num">{r.ms ? `${(r.ms / 1000).toFixed(1)}s` : ''}</td>
                      </tr>
                      {open === r.id && (
                        <tr><td colSpan={4} className="qopen">
                          <EvidencePanel result={r} />
                          {ticket && <TicketEditor ticket={ticket}
                            onChange={t => onDetail({ ...detail, tickets: tickets.map(x => (x.id === t.id ? t : x)) })} />}
                          {r.outcome === 'real_bug' && (
                            <FixPanel result={r} fixes={fixes.filter(f => f.result_id === r.id)} ticketOpen={ticket?.status === 'Drafted'}
                              onFix={f => {
                                const others = fixes.filter(x => x.id !== f.id);
                                const next = { ...detail, fixes: [...others, f] };
                                if (f.status === 'Added' && ticket) {
                                  next.tickets = tickets.map(t => (t.id === ticket.id ? { ...t, fix_text: `${f.explanation}\n\n${f.diff}` } : t));
                                }
                                onDetail(next);
                              }} />
                          )}
                        </td></tr>
                      )}
                    </Fragment>
                  );
                })}
                {!shown.length && <tr><td colSpan={4} className="qmuted" style={{ padding: 16 }}>Nothing matches this filter.</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}

      {!!drafts.length && (
        <section className="qsection">
          <h3>Drafted tests for coverage gaps</h3>
          <p className="qmuted">The Test Agent wrote these for changed modules that no uploaded test covers. They are not used until you approve them.</p>
          {drafts.map(d => <DraftCard key={d.id} draft={d} onChange={n => onDetail({ ...detail, drafts: drafts.map(x => (x.id === n.id ? n : x)) })} />)}
        </section>
      )}
    </div>
  );
}

function CompareView({ runs }: { runs: Run[] }) {
  const toast = useToast();
  const done = runs.filter(r => r.status === 'finished' || r.status === 'flagged');
  const [a, setA] = useState<number>(done[1]?.id ?? 0);
  const [b, setB] = useState<number>(done[0]?.id ?? 0);
  const [result, setResult] = useState<Comparison | null>(null);
  const [details, setDetails] = useState<Record<number, Result>>({});
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function compare() {
    if (!a || !b || a === b) return toast('Pick two different runs');
    setBusy(true);
    try {
      const [cmp, da, db] = await Promise.all([qa.compare(a, b), qa.run(a), qa.run(b)]);
      setResult(cmp);
      setDetails(Object.fromEntries([...da.results, ...db.results].map(r => [r.id, r])));
      setOpen(null);
    } catch (err) {
      toast(message(err, 'The runs could not be compared'));
    } finally {
      setBusy(false);
    }
  }

  if (done.length < 2) {
    return <div className="empty"><b>Not enough runs yet</b>Run the tests at least twice before comparing.</div>;
  }
  const label = (r: Run) => `Run #${r.id} · PR #${r.pr_number} · ${when(r.started_at)}`;
  return (
    <div className="qdetail">
      <div className="qcompare-pick">
        <label className="field">Before<select value={a} onChange={e => setA(Number(e.target.value))}>{done.map(r => <option key={r.id} value={r.id}>{label(r)}</option>)}</select></label>
        <label className="field">After<select value={b} onChange={e => setB(Number(e.target.value))}>{done.map(r => <option key={r.id} value={r.id}>{label(r)}</option>)}</select></label>
        <button className="btn" onClick={compare} disabled={busy || a === b}>{busy ? 'Comparing…' : 'Compare'}</button>
      </div>
      {a === b && <p className="qmuted">Pick two different runs.</p>}
      {result && (
        <>
          <div className="chips">
            {Object.entries(result.summary).map(([tag, n]) => <Tag key={tag} cls={COMPARE_TAG[tag] || 'muted'}>{n} {tag}</Tag>)}
          </div>
          <div className="tablewrap qtable">
            <table className="grid">
              <thead><tr><th>Test</th><th>Before</th><th>After</th><th>Change</th></tr></thead>
              <tbody>
                {result.rows.map(row => {
                  const key = `${row.kind}|${row.file}|${row.title}`;
                  return (
                    <Fragment key={key}>
                      <tr className="qres" tabIndex={0} onClick={() => setOpen(open === key ? null : key)}
                          onKeyDown={e => { if (e.key === 'Enter') setOpen(open === key ? null : key); }}>
                        <td><div className="qtitle">{row.title}</div><div className="qmuted mono">{row.file}</div></td>
                        <td>{row.before ? <Tag cls={OUTCOME[row.before.outcome].cls}>{OUTCOME[row.before.outcome].text}</Tag> : '—'}</td>
                        <td>{row.after ? <Tag cls={OUTCOME[row.after.outcome].cls}>{OUTCOME[row.after.outcome].text}</Tag> : '—'}</td>
                        <td><Tag cls={COMPARE_TAG[row.tag] || 'muted'}>{row.tag}</Tag>
                          {row.tag === 'new failure' && row.after?.outcome === 'real_bug' && row.ticket_id && <span className="qmuted"> · ticket ready in the After run</span>}</td>
                      </tr>
                      {open === key && (
                        <tr><td colSpan={4} className="qopen qside">
                          <div><h4>Before</h4>{row.before && details[row.before.id] ? <EvidencePanel result={details[row.before.id]} /> : <p className="qmuted">Not in this run.</p>}</div>
                          <div><h4>After</h4>{row.after && details[row.after.id] ? <EvidencePanel result={details[row.after.id]} /> : <p className="qmuted">Not in this run.</p>}</div>
                        </td></tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

export default function RunsView({ hidden, link, openRun, onGoConnect }: Props) {
  const toast = useToast();
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [staging, setStaging] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [tab, setTab] = useState<'runs' | 'compare'>('runs');
  const [failed, setFailed] = useState(false);

  const loadRuns = useCallback(async () => {
    try {
      const res = await qa.runs();
      setRuns(res.items);
      setStaging(res.staging_url);
      setFailed(false);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 401)) setFailed(true);
    }
  }, []);

  const loadDetail = useCallback(async (id: number) => {
    try {
      setDetail(await qa.run(id));
    } catch (err) {
      toast(message(err, 'The run could not be loaded'));
    }
  }, [toast]);

  useEffect(() => { if (!hidden && link) loadRuns(); }, [hidden, link, loadRuns]);
  useEffect(() => { if (openRun) { setTab('runs'); setSelected(openRun.id); loadDetail(openRun.id); } }, [openRun, loadDetail]);
  useEffect(() => { if (selected) loadDetail(selected); else setDetail(null); }, [selected, loadDetail]);

  // Follow a run while it is going (Req 4.9): every 2.5 seconds, only while this screen is open
  const running = detail?.run.status === 'running';
  useEffect(() => {
    if (hidden || !running || !selected) return;
    const timer = setInterval(() => { loadDetail(selected); loadRuns(); }, 2500);
    return () => clearInterval(timer);
  }, [hidden, running, selected, loadDetail, loadRuns]);

  if (!link) return <ConnectFirst hidden={hidden} what="Test runs use the tests in your Test Library on your staging app." onGoConnect={onGoConnect} />;

  return (
    <section hidden={hidden} className="workspace qwide">
      <article className="card">
        <header className="head">
          <h1>Test <em>Runs</em></h1>
          <p className="lead">Start a run with Run Now on Risk Analysis. The Test Agent picks the tests, checks staging, runs
            Playwright and Newman together and sorts every failure. Nothing goes to Jira until you approve it.</p>
          <div className="chips">
            <Chip on={!!staging}>{staging ? `Staging ${staging}` : 'No staging address yet'}</Chip>
            <Chip on={false}>{runs ? `${runs.length} run${runs.length === 1 ? '' : 's'}` : 'Loading runs'}</Chip>
          </div>
        </header>
        <div className="tabs" role="tablist">
          <button className="tab" role="tab" aria-selected={tab === 'runs'} onClick={() => setTab('runs')}>Runs</button>
          <button className="tab" role="tab" aria-selected={tab === 'compare'} onClick={() => setTab('compare')}>Compare runs</button>
        </div>
        <div className="pane">
          {failed && <div className="warnbox">Could not reach the Verixa server. The list may be out of date.</div>}
          {tab === 'compare' ? (runs && <CompareView runs={runs} />) : !runs ? (
            <div className="empty"><b>Loading</b>Reading your runs.</div>
          ) : !runs.length ? (
            <div className="empty"><b>No runs yet</b>Open Risk Analysis, choose a pull request and press Run Now.</div>
          ) : (
            <>
              <div className="tablewrap qtable qruns">
                <table className="grid">
                  <thead><tr><th>Run</th><th>Pull request</th><th>Status</th><th>Results</th><th>Started</th></tr></thead>
                  <tbody>
                    {runs.map(r => (
                      <tr key={r.id} className={'qres' + (selected === r.id ? ' open' : '')} tabIndex={0}
                          onClick={() => setSelected(r.id)} onKeyDown={e => { if (e.key === 'Enter') setSelected(r.id); }}>
                        <td className="mono">#{r.id}</td>
                        <td>PR #{r.pr_number}{r.risk_label ? ` · ${r.risk_label} risk` : ''}</td>
                        <td><Tag cls={RUN_STATUS[r.status].cls}>{RUN_STATUS[r.status].text}</Tag></td>
                        <td className="qmuted">{r.counts.passed} passed · {r.counts.real_bug} bugs · {r.counts.deployment_pending} pending</td>
                        <td className="qmuted">{when(r.started_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {detail ? <RunDetailView detail={detail} onDetail={setDetail} />
                : <p className="qmuted" style={{ marginTop: 16 }}>Select a run to see its results and proof.</p>}
            </>
          )}
        </div>
      </article>
    </section>
  );
}
