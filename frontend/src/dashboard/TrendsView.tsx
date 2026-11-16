/* Cross PR Risk Trends (UC11): how risk labels and failures move across pull requests and modules over time. */
import { useEffect, useState } from 'react';
import { ApiError, qa, type RiskLabel, type Trends } from './api';
import type { Link } from './connection';
import { ConnectFirst, RUN_STATUS, Tag, message } from './qa';

interface Props {
  hidden: boolean;
  link: Link | null;
  onGoConnect: () => void;
  onOpenRisk: () => void;
}

const LABELS: RiskLabel[] = ['High', 'Medium', 'Low'];
const PERIODS = [7, 30, 90, 365];

export default function TrendsView({ hidden, link, onGoConnect, onOpenRisk }: Props) {
  const [days, setDays] = useState(30);
  const [module, setModule] = useState('');
  const [data, setData] = useState<Trends | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (hidden || !link) return;
    let live = true;
    qa.trends(days, module)
      .then(d => { if (live) { setData(d); setError(''); } })
      .catch(err => { if (live && !(err instanceof ApiError && err.status === 401)) setError(message(err, 'The report could not be loaded')); });
    return () => { live = false; };
  }, [hidden, link, days, module]);

  if (!link) return <ConnectFirst hidden={hidden} what="Trends read the risk labels and runs of your repository." onGoConnect={onGoConnect} />;
  const top = Math.max(1, ...(data?.periods ?? []).map(p => p.High + p.Medium + p.Low));
  const worst = Math.max(1, ...(data?.modules ?? []).map(m => m.failures));

  return (
    <section hidden={hidden} className="workspace qwide">
      <article className="card">
        <header className="head">
          <h1>Risk <em>Trends</em></h1>
          <p className="lead">How risk and failures change across pull requests. Each pull request counts once, at its newest score.</p>
          <div className="qcompare-pick" style={{ marginTop: 16 }}>
            <label className="field">Period
              <select value={days} onChange={e => setDays(Number(e.target.value))}>
                {PERIODS.map(p => <option key={p} value={p}>Last {p} days</option>)}
              </select>
            </label>
            <label className="field">Module
              <select value={module} onChange={e => setModule(e.target.value)}>
                <option value="">All modules</option>
                {(data?.all_modules ?? []).map(m => <option key={m}>{m}</option>)}
              </select>
            </label>
          </div>
        </header>
        <div className="pane">
          {error && <div className="warnbox" role="alert">{error}</div>}
          {!data ? <div className="empty"><b>Loading</b></div> : (
            <>
              {!data.enough && (
                <div className="warnbox">Not enough data yet: {data.total} scored pull request{data.total === 1 ? '' : 's'} in this
                  period, and a trend needs at least {data.minimum}.</div>
              )}
              <div className="risk-stats">
                {LABELS.map(l => (
                  <div key={l} className={'risk-stat ' + (l === 'High' ? 'high' : l === 'Medium' ? 'med' : 'low')}>
                    <div className="risk-stat-label">{l} risk</div>
                    <div className="risk-stat-value">{data.share[l]}</div>
                    <div className="risk-stat-sub">{data.total ? Math.round((data.share[l] / data.total) * 100) : 0}% of {data.total}</div>
                  </div>
                ))}
              </div>

              <section className="qsection">
                <h3>Pull requests by risk over time</h3>
                {!data.periods.length ? <p className="qmuted">No scored pull requests in this period.</p> : (
                  <div className="qbars" role="img" aria-label="Pull requests per period by risk label">
                    {data.periods.map(p => (
                      <div key={p.period} className="qbar" title={`${p.period}: ${p.High} High, ${p.Medium} Medium, ${p.Low} Low`}>
                        <div className="qbar-stack" style={{ height: `${((p.High + p.Medium + p.Low) / top) * 100}%` }}>
                          {LABELS.map(l => p[l] ? <span key={l} className={l.toLowerCase()} style={{ flexGrow: p[l] }}></span> : null)}
                        </div>
                        <small>{p.period.slice(5)}</small>
                      </div>
                    ))}
                  </div>
                )}
                <div className="qlegend">{LABELS.map(l => <span key={l}><i className={l.toLowerCase()}></i>{l}</span>)}</div>
              </section>

              <section className="qsection">
                <h3>Modules with the most failures</h3>
                {!data.modules.length ? <p className="qmuted">No test runs in this period.</p> : data.modules.map(m => (
                  <button key={m.module} className={'qhbar' + (module === m.module ? ' on' : '')}
                          onClick={() => setModule(module === m.module ? '' : m.module)} title="Show the pull requests of this module">
                    <span className="mono">{m.module}</span>
                    <span className="qhbar-track"><i style={{ width: `${(m.failures / worst) * 100}%` }}></i></span>
                    <span className="qmuted">{m.failures} failures · {m.real_bugs} real bugs</span>
                  </button>
                ))}
              </section>

              <section className="qsection">
                <h3>Pull requests{module ? ` touching ${module}` : ''}</h3>
                {!data.pull_requests.length ? <p className="qmuted">None in this period.</p> : (
                  <div className="tablewrap qtable">
                    <table className="grid">
                      <thead><tr><th>Pull request</th><th>Risk</th><th>Last run</th><th>Tickets</th></tr></thead>
                      <tbody>
                        {data.pull_requests.map(pr => (
                          <tr key={pr.pr_number} className="qres" tabIndex={0} onClick={onOpenRisk} onKeyDown={e => { if (e.key === 'Enter') onOpenRisk(); }}>
                            <td><b>#{pr.pr_number}</b> {pr.title || 'Untitled'}<div className="qmuted">{pr.module}</div></td>
                            <td><span className={'rbadge ' + (pr.risk_label === 'High' ? 'high' : pr.risk_label === 'Medium' ? 'med' : 'low')}><i></i>{pr.risk_label}</span></td>
                            <td>{pr.last_run ? <><Tag cls={RUN_STATUS[pr.last_run.status].cls}>{RUN_STATUS[pr.last_run.status].text}</Tag>
                              <span className="qmuted"> {pr.last_run.passed} passed · {pr.last_run.real_bug} bugs</span></> : <span className="qmuted">not run</span>}</td>
                            <td>{pr.tickets.length ? pr.tickets.map(t => t.url
                              ? <a key={t.key} href={t.url} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}>{t.key} </a>
                              : <span key={t.key}>{t.key} </span>) : <span className="qmuted">none</span>}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      </article>
    </section>
  );
}
