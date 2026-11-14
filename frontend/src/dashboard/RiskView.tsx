/* Risk Analysis — Deliverable 2.
 *
 * Shows what the Analysis Agent produced for every pull request on the connected repository:
 * the rule-based risk label and score, the rule trace that justifies it, the agent's reasoning
 * and its suggested test areas.
 *
 * Nothing on this screen is invented. Every value is read from /api/analysis/pull-requests, which
 * reads the risk_assessments rows the agent wrote. A pull request that has not been scored yet
 * shows its real state (queued, running, needs review, failed), never a placeholder label.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, api, openLive, qa, type Assessment, type LiveEvent, type RiskFeed, type RiskLabel } from './api';
import { icons } from './icons';
import { Chip, hookLabel, type HookState, type Link } from './connection';
import { useToast } from './Toast';

interface Props {
  hidden: boolean;
  link: Link | null;
  hook: HookState;
  staging: string | null;
  onGoConnect: () => void;
  onRunStarted: (runId: number) => void;
}

// The mock-up used low / med / high as class names. Map the agent's labels onto them.
const BADGE: Record<RiskLabel, string> = { Low: 'low', Medium: 'med', High: 'high' };
const STATE_TEXT: Record<Assessment['state'], string> = {
  queued: 'Queued',
  running: 'Analysing',
  scored: 'Scored',
  needs_human_review: 'Needs review',
  failed: 'Failed',
};
const POLL_MS = 4000;
const LIVE_KEEP_MS = 2 * 60 * 1000;  // a finished run stays on screen this long

// The live messages of one pull request's current run
interface LiveRun {
  pr: number;
  messages: LiveEvent[];
  done: boolean;
  finishedAt: number;
}

function addLive(runs: LiveRun[], event: LiveEvent): LiveRun[] {
  const current = runs.find(r => r.pr === event.pr);
  const startsNew = event.event === 'service.delivery' || event.event === 'run.start' || event.event === 'qa.start';
  // A message after a finished run starts a new one, unless it is a replay of what is already shown
  if (!current || (current.done && startsNew && !current.messages.some(m => m.at === event.at && m.event === event.event))) {
    const fresh = { pr: event.pr, messages: [event], done: event.done, finishedAt: event.done ? Date.now() : 0 };
    return [fresh, ...runs.filter(r => r.pr !== event.pr)];
  }
  if (current.messages.some(m => m.at === event.at && m.event === event.event)) return runs;  // already shown
  const next = { ...current, messages: [...current.messages, event].slice(-30),
                 done: current.done || event.done, finishedAt: event.done ? Date.now() : current.finishedAt };
  return runs.map(r => (r === current ? next : r));
}

function LivePanel({ runs, onClose }: { runs: LiveRun[]; onClose: (pr: number) => void }) {
  if (!runs.length) return null;
  return (
    <div className="live" aria-live="polite">
      {runs.map(run => {
        const last = run.messages[run.messages.length - 1];
        return (
          <section key={run.pr} className={'live-run' + (run.done ? ' done ' + last.level : '')}
                   aria-label={`Agents working on pull request ${run.pr}`}>
            <header className="live-head">
              <b>PR #{run.pr}</b>
              <span className="live-status">
                {!run.done && <i className="live-dot" aria-hidden="true"></i>}
                {run.done ? (last.level === 'ok' ? 'Finished' : last.level === 'error' ? 'Stopped' : 'Finished, check the result') : 'Agents are analysing'}
              </span>
              {run.done && <button className="live-close" onClick={() => onClose(run.pr)} aria-label={`Hide PR #${run.pr}`}>×</button>}
            </header>
            <ol className="live-steps">
              {run.messages.map((m, i) => (
                <li key={m.at + m.event + i} className={m.level + (!run.done && i === run.messages.length - 1 ? ' current' : '')}>
                  {m.text}
                </li>
              ))}
            </ol>
          </section>
        );
      })}
    </div>
  );
}

const initials = (who: string | null) =>
  (who || '??').replace(/[^a-zA-Z0-9]/g, '').slice(0, 2).toUpperCase() || '??';

// A stable colour per author, so the same person keeps the same avatar between loads
function hue(who: string | null): number {
  let h = 0;
  for (const ch of who || 'anon') h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

function ago(iso: string | null): string {
  if (!iso) return '';
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (!isFinite(seconds) || seconds < 0) return '';
  if (seconds < 60) return 'just now';
  const mins = Math.round(seconds / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function RiskBadge({ label }: { label: RiskLabel | null }) {
  if (!label) return <span className="rbadge none"><i></i>Not scored</span>;
  return <span className={'rbadge ' + BADGE[label]}><i></i>{label}</span>;
}

function StateBadge({ state }: { state: Assessment['state'] }) {
  const busy = state === 'queued' || state === 'running';
  return (
    <span className={'rstate ' + state}>
      {busy && <i></i>}
      {state === 'scored' && <svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>}
      {STATE_TEXT[state]}
    </span>
  );
}

function Detail({ row }: { row: Assessment }) {
  const raised = row.base_label && row.risk_label && row.base_label !== row.risk_label;
  return (
    <tr>
      <td className="rdetail" colSpan={6}>
        <div className="rdetail-in">
          {!!row.errors.length && (
            <div className="rerr">
              <b>{row.state === 'failed' ? 'The analysis could not finish' : 'The Manager did not accept the output'}</b>
              {row.errors.join(' · ')}
              {row.attempts > 0 && ` (after ${row.attempts} attempt${row.attempts === 1 ? '' : 's'})`}
            </div>
          )}

          {!!row.risk_factors.length && (
            <div>
              <h4>Why this label</h4>
              <ul className="rfactors">
                {row.risk_factors.map((factor, i) => <li key={i}>{factor}</li>)}
              </ul>
            </div>
          )}

          {row.reasoning && (
            <div>
              <h4>Agent reasoning</h4>
              <p className="rreason">{row.reasoning}</p>
            </div>
          )}

          {row.concern && (
            <div className="rconcern" role="note">
              <h4>The agent questions this label</h4>
              <p>{row.concern}</p>
              <p className="rconcern-note">The label comes from the rules and has not been changed. Check this before relying on it.</p>
            </div>
          )}

          {!!row.test_areas.length && (
            <div>
              <h4>Suggested test areas</h4>
              <ul className="rareas">
                {row.test_areas.map((area, i) => <li key={i}><span>{i + 1}</span>{area}</li>)}
              </ul>
            </div>
          )}

          <div className="rmeta">
            {row.module && <Chip on={false}>module {row.module}</Chip>}
            {row.files_changed !== null && (
              <Chip on={false}>{row.files_changed} file{row.files_changed === 1 ? '' : 's'}, {row.lines_changed ?? 0} lines</Chip>
            )}
            {row.past_defects !== null && <Chip on={false}>{row.past_defects} past fix{row.past_defects === 1 ? '' : 'es'} here</Chip>}
            {row.sensitivity && <Chip on={false}>sensitivity {row.sensitivity}</Chip>}
            {raised && <Chip on={false}>raised from {row.base_label} by a minimum label</Chip>}
            {row.model_used && <Chip on={false}>explained by {row.model_used}</Chip>}
            {row.attempts > 1 && <Chip on={false}>{row.attempts} manager attempts</Chip>}
            {row.pr_url?.startsWith('https://github.com/') && (
              <a className="btn ghost sm" href={row.pr_url} target="_blank" rel="noopener noreferrer">
                Open on GitHub
              </a>
            )}
          </div>
        </div>
      </td>
    </tr>
  );
}

export default function RiskView({ hidden, link, hook, staging, onGoConnect, onRunStarted }: Props) {
  const toast = useToast();
  const [feed, setFeed] = useState<RiskFeed | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [prNumber, setPrNumber] = useState('');
  const [busy, setBusy] = useState(false);
  const [starting, setStarting] = useState<number | null>(null);

  // Run Now (Req 4.1): the only way tests start. The run goes on in the background and opens on Test Runs.
  async function runNow(row: Assessment) {
    if (!staging) {
      toast('Add the staging address on Integrations first. Tests never run on the live system', { label: 'Open Integrations', run: onGoConnect });
      return;
    }
    setStarting(row.id);
    try {
      const run = await qa.runNow(row.id);
      toast(`Run #${run.id} started for PR #${row.pr_number}`);
      onRunStarted(run.id);
    } catch (err) {
      toast((err instanceof ApiError ? err.message : 'The run could not be started').slice(0, 200));
    } finally {
      setStarting(null);
    }
  }

  const load = useCallback(async (): Promise<RiskFeed | null> => {
    try {
      const next = await api.riskFeed();
      setFeed(next);
      setFailed(false);
      return next;
    } catch (err) {
      // A 401 is handled globally by App.tsx. Anything else leaves the last good data on screen.
      if (!(err instanceof ApiError) || err.status !== 401) setFailed(true);
      return null;
    }
  }, []);

  // Load once when the screen is first opened, not while it is hidden behind another view
  const loaded = useRef(false);
  useEffect(() => {
    if (hidden || loaded.current || !link) return;
    loaded.current = true;
    load();
  }, [hidden, link, load]);

  // Live status over the WebSocket: each agent step arrives as it happens, for the connected repository
  const [liveRuns, setLiveRuns] = useState<LiveRun[]>([]);
  const [liveOn, setLiveOn] = useState(false);
  const repo = link?.repo;
  useEffect(() => {
    if (!repo) return;
    setLiveRuns([]);
    return openLive(event => {
      if (event.repo !== repo) return;
      setLiveRuns(runs => addLive(runs, event));
      if (event.done && !event.replay) load();  // the saved result is in the list now
    }, setLiveOn);
  }, [repo, load]);

  // Finished runs fade out of the panel after a while
  useEffect(() => {
    if (!liveRuns.some(r => r.done)) return;
    const timer = setInterval(() => {
      setLiveRuns(runs => runs.filter(r => !r.done || Date.now() - r.finishedAt < LIVE_KEEP_MS));
    }, 10000);
    return () => clearInterval(timer);
  }, [liveRuns]);

  // Poll only while something is actually being scored, and only while this screen is visible
  const pending = (feed?.counts.pending ?? 0) > 0;
  useEffect(() => {
    if (hidden || !pending) return;
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [hidden, pending, load]);

  if (!link) {
    return (
      <section hidden={hidden} className="lock-wrap">
        <article className="lock">
          <span className="lock-ico">{icons.integrations}</span>
          <h2>Connect a repository first</h2>
          <p>Risk Analysis reads the pull requests of a connected repository. Link GitHub and Jira once to set it up.</p>
          <div><button className="btn" onClick={onGoConnect}>Go to Integrations</button></div>
        </article>
      </section>
    );
  }

  async function analyse() {
    const number = Number(prNumber.trim());
    if (!Number.isInteger(number) || number < 1) {
      toast('Enter the pull request number, for example 4');
      return;
    }
    setBusy(true);
    try {
      const row = await api.analysePr(number);
      await load();
      setOpen(row.id);
      toast(
        row.state === 'scored'
          ? `#${row.pr_number} scored ${row.risk_label}`
          : `#${row.pr_number}: ${STATE_TEXT[row.state].toLowerCase()}`,
      );
      setPrNumber('');
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'The analysis could not be started';
      toast(message.slice(0, 200));
    } finally {
      setBusy(false);
    }
  }

  // High risk first, then newest (Req 3.7). The server sends newest first, and sort keeps that order within a label.
  const RANK: Record<string, number> = { High: 0, Medium: 1, Low: 2 };
  const items = [...(feed?.items ?? [])].sort((a, b) => (RANK[a.risk_label ?? ''] ?? 3) - (RANK[b.risk_label ?? ''] ?? 3));
  const counts = feed?.counts ?? {};
  const tiles: { key: RiskLabel | 'total'; cls: string; label: string; icon: typeof icons.bolt; sub: string }[] = [
    { key: 'total', cls: '', label: 'Pull requests', icon: icons.pullRequests, sub: 'seen by the agent' },
    { key: 'High', cls: 'high', label: 'High risk', icon: icons.alert, sub: 'test these first' },
    { key: 'Medium', cls: 'med', label: 'Medium risk', icon: icons.bolt, sub: 'worth a look' },
    { key: 'Low', cls: 'low', label: 'Low risk', icon: icons.library, sub: 'routine change' },
  ];

  return (
    <section hidden={hidden} className="workspace risk">
      <article className="card">
        <header className="head">
          <h1>Risk Analysis</h1>
          <p className="lead">
            Every pull request on <b className="mono">{link.repo}</b> is scored automatically when GitHub
            delivers it. The label comes from rules in code; the agent writes the reasoning and the
            test areas.
          </p>
          <div className="chips" style={{ marginTop: 14 }}>
            <Chip on={hook === 'ok'}>{hookLabel(hook)}</Chip>
            <Chip on={liveOn}>{liveOn ? 'Live updates on' : 'Live updates connecting'}</Chip>
            {feed && <Chip on={false}>Jira {link.jiraKey}</Chip>}
            {(counts.needs_review ?? 0) > 0 && <Chip on={false}>{counts.needs_review} need review</Chip>}
            {(counts.failed ?? 0) > 0 && <Chip on={false}>{counts.failed} failed</Chip>}
          </div>
        </header>

        <div className="pane">
          {hook !== 'ok' && (
            <div className="warnbox" style={{ marginBottom: 18 }}>
              GitHub has not delivered anything to this webhook yet, so nothing will arrive on its own.
              Check Integrations, or score a pull request by number below.
            </div>
          )}

          <div className="risk-stats">
            {tiles.map(tile => (
              <div key={tile.key} className={'risk-stat ' + tile.cls}>
                <div className="risk-stat-label">{tile.icon}{tile.label}</div>
                <div className="risk-stat-value">{counts[tile.key] ?? 0}</div>
                <div className="risk-stat-sub">{tile.sub}</div>
              </div>
            ))}
          </div>

          <div className="risk-ask">
            <input value={prNumber} onChange={e => setPrNumber(e.target.value.replace(/\D/g, '').slice(0, 7))}
                   onKeyDown={e => { if (e.key === 'Enter' && !busy) analyse(); }}
                   placeholder="PR #" aria-label="Pull request number" inputMode="numeric" disabled={busy} />
            <button className="btn" onClick={analyse} disabled={busy || !prNumber.trim()}>
              {busy ? 'Analysing…' : 'Analyse now'}
            </button>
            <span className="hint">
              {busy ? 'The agent is reading the diff and scoring it. This takes a few seconds.'
                    : 'Scores a pull request without waiting for a webhook delivery.'}
            </span>
          </div>

          {failed && (
            <div className="warnbox" style={{ marginTop: 18 }}>
              Could not reach the Verixa server. The list below may be out of date.
            </div>
          )}

          <LivePanel runs={liveRuns} onClose={pr => setLiveRuns(runs => runs.filter(r => r.pr !== pr))} />
        </div>

        {!feed ? (
          <div className="empty"><b>Loading</b>Reading the agent's assessments.</div>
        ) : !items.length ? (
          <div className="empty">
            <b>No pull requests analysed yet</b>
            Open or push to a pull request on {link.repo}, or enter its number above and press Analyse now.
          </div>
        ) : (
          <div className="tablewrap">
            <table className="grid risk-grid">
              <thead>
                <tr>
                  <th>Pull request</th>
                  <th>Risk</th>
                  <th className="rscore">Score</th>
                  <th>State</th>
                  <th className="ract">Analysed</th>
                  <th className="ract">Tests</th>
                </tr>
              </thead>
              {items.map(row => (
                <tbody key={row.id}>
                  <tr className={'risk-row' + (open === row.id ? ' open' : '')}
                      onClick={() => setOpen(open === row.id ? null : row.id)}
                      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(open === row.id ? null : row.id); } }}
                      tabIndex={0} aria-expanded={open === row.id}>
                    <td>
                      <div className="rpr">
                        <span className="rpr-avatar" style={{ background: `hsl(${hue(row.author)} 55% 45%)` }}>
                          {initials(row.author)}
                        </span>
                        <div style={{ minWidth: 0 }}>
                          <div className="rpr-title"><b>#{row.pr_number}</b>{row.title || 'Untitled pull request'}</div>
                          <div className="rpr-meta">
                            {row.module ? `${row.module} · ` : ''}
                            {row.files_changed !== null ? `${row.files_changed} file${row.files_changed === 1 ? '' : 's'} · ` : ''}
                            <code>{row.head_sha.slice(0, 7)}</code>
                          </div>
                        </div>
                      </div>
                    </td>
                    <td><RiskBadge label={row.risk_label} /></td>
                    <td className="rscore">{row.score ?? '—'}</td>
                    <td><StateBadge state={row.state} /></td>
                    <td className="ract"><span className="muted">{ago(row.updated_at)}</span></td>
                    <td className="ract">
                      <button className="btn sm" disabled={starting !== null || row.state === 'queued' || row.state === 'running'}
                              onClick={e => { e.stopPropagation(); runNow(row); }} onKeyDown={e => e.stopPropagation()}
                              title={row.state === 'queued' || row.state === 'running' ? 'Wait until it is scored' : `Run the tests for PR #${row.pr_number} on staging`}>
                        {starting === row.id ? 'Starting…' : <>{icons.play} Run Now</>}
                      </button>
                    </td>
                  </tr>
                  {open === row.id && <Detail row={row} />}
                </tbody>
              ))}
            </table>
          </div>
        )}
      </article>
    </section>
  );
}
