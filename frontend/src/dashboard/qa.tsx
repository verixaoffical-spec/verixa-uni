/* Shared pieces of the Test Runs, Tickets, Trends and QA Memory screens (UC4 to UC11). */
import { useEffect, useState, type ReactNode } from 'react';
import { ApiError, qa, type Draft, type Fix, type Outcome, type Result, type RunStatus, type Ticket } from './api';
import { icons } from './icons';
import { useToast } from './Toast';

export const OUTCOME: Record<Outcome, { text: string; cls: string }> = {
  passed: { text: 'Passed', cls: 'ok' },
  real_bug: { text: 'Real bug', cls: 'bad' },
  temporary_error: { text: 'Temporary error', cls: 'warn' },
  deployment_pending: { text: 'Deployment pending', cls: 'info' },
  skipped: { text: 'Skipped', cls: 'muted' },
};

export const RUN_STATUS: Record<RunStatus, { text: string; cls: string }> = {
  running: { text: 'Running', cls: 'info' },
  finished: { text: 'Finished', cls: 'ok' },
  flagged: { text: 'Needs review', cls: 'warn' },
  failed: { text: 'Failed', cls: 'bad' },
};

export function Tag({ cls, children }: { cls: string; children: ReactNode }) {
  return <span className={'qtag ' + cls}><i></i>{children}</span>;
}

export const message = (err: unknown, fallback: string) =>
  (err instanceof ApiError ? err.message : fallback).slice(0, 240);

export function when(iso: string | null): string {
  if (!iso) return '';
  const at = new Date(iso);
  return isNaN(at.getTime()) ? '' : at.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export function took(start: string | null, end: string | null): string {
  if (!start || !end) return '';
  const s = Math.max(0, Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

// The screen for a feature that needs a connected repository first
export function ConnectFirst({ hidden, what, onGoConnect }: { hidden: boolean; what: string; onGoConnect: () => void }) {
  return (
    <section hidden={hidden} className="lock-wrap">
      <article className="lock">
        <span className="lock-ico">{icons.integrations}</span>
        <h2>Connect a repository first</h2>
        <p>{what} Link GitHub and Jira once on Integrations to set it up.</p>
        <div><button className="btn" onClick={onGoConnect}>Go to Integrations</button></div>
      </article>
    </section>
  );
}

// ---------- evidence of one failed test (UC6) ----------

function TextLog({ id, label }: { id: number; label: string }) {
  const [text, setText] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    fetch(qa.evidenceUrl(id), { credentials: 'same-origin' })
      .then(r => (r.ok ? r.text() : Promise.reject()))
      .then(t => live && setText(t))
      .catch(() => live && setFailed(true));
    return () => { live = false; };
  }, [id]);
  return (
    <details className="qlog" open={label === 'Console log'}>
      <summary>{label}</summary>
      {failed ? <p className="qmuted">This proof is not available.</p>
        : text === null ? <p className="qmuted">Loading…</p>
        : <pre>{text || '(empty)'}</pre>}
    </details>
  );
}

export function EvidencePanel({ result }: { result: Result }) {
  const byType = Object.fromEntries(result.evidence.map(e => [e.type, e.id]));
  const [shotBroken, setShotBroken] = useState(false);
  if (result.outcome === 'passed' || result.outcome === 'skipped' || result.outcome === 'deployment_pending') {
    return <p className="qmuted">{result.outcome === 'deployment_pending'
      ? `Not run: ${result.error || 'this is not on staging yet'}. A pending test is never counted as failed.`
      : 'No proof is kept for tests that did not fail.'}</p>;
  }
  return (
    <div className="qevidence">
      {result.error && <pre className="qerror">{result.error}</pre>}
      {!result.evidence.length && <p className="qmuted">No proof files were captured for this failure.</p>}
      {byType.screenshot && !shotBroken && (
        <a href={qa.evidenceUrl(byType.screenshot)} target="_blank" rel="noopener" className="qshot">
          <img src={qa.evidenceUrl(byType.screenshot)} alt={`Screenshot when "${result.title}" failed`} loading="lazy"
               onError={() => setShotBroken(true)} />
        </a>
      )}
      {shotBroken && <p className="qmuted">The screenshot is not available.</p>}
      {byType.trace && (
        <div className="qtrace">
          <a className="btn ghost sm" href={qa.evidenceUrl(byType.trace)} download>{icons.download} Download trace</a>
          <a className="btn ghost sm" href="https://trace.playwright.dev/" target="_blank" rel="noopener noreferrer">
            Open Playwright Trace Viewer
          </a>
          <span className="qmuted">Download the trace, then drop it into the Trace Viewer.</span>
        </div>
      )}
      {byType.console_log && <TextLog id={byType.console_log} label="Console log" />}
      {byType.network_log && <TextLog id={byType.network_log} label="Network log" />}
      {result.evidence.some(e => e.type.endsWith('_log')) && <p className="qmuted">Keys, tokens and passwords were removed from these logs.</p>}
    </div>
  );
}

// ---------- the ticket review (UC7) ----------

export function TicketEditor({ ticket, onChange }: { ticket: Ticket; onChange: (t: Ticket) => void }) {
  const toast = useToast();
  const [title, setTitle] = useState(ticket.title);
  const [cause, setCause] = useState(ticket.root_cause);
  const [steps, setSteps] = useState(ticket.steps.join('\n'));
  const [priority, setPriority] = useState(ticket.priority);
  const [busy, setBusy] = useState<'' | 'save' | 'file' | 'reject'>('');
  const open = ticket.status === 'Drafted';
  const dirty = title !== ticket.title || cause !== ticket.root_cause || steps !== ticket.steps.join('\n') || priority !== ticket.priority;
  const stepList = steps.split('\n').map(s => s.trim()).filter(Boolean);
  const problem = title.trim().length < 5 ? 'The title needs at least 5 characters'
    : cause.trim().length < 10 ? 'Describe the likely cause in at least 10 characters'
    : !stepList.length ? 'Add at least one step to reproduce'
    : stepList.length > 20 ? 'Use at most 20 steps' : '';

  async function act(kind: 'save' | 'file' | 'reject') {
    if (kind !== 'reject' && problem) return toast(problem);
    if (kind === 'reject' && !confirm('Reject this ticket? Nothing will be sent to Jira.')) return;
    setBusy(kind);
    try {
      let next = ticket;
      if (kind !== 'reject' && dirty) next = await qa.editTicket(ticket.id, { title: title.trim(), root_cause: cause.trim(), steps: stepList, priority });
      if (kind === 'file') next = await qa.fileTicket(ticket.id);
      if (kind === 'reject') next = await qa.rejectTicket(ticket.id);
      onChange(next);
      toast(kind === 'file' ? `Filed in Jira as ${next.jira_key}` : kind === 'reject' ? 'Rejected. Nothing was sent to Jira' : 'Draft saved');
    } catch (err) {
      toast(message(err, 'The ticket could not be updated'));
    } finally {
      setBusy('');
    }
  }

  return (
    <div className={'qticket' + (open ? '' : ' closed')}>
      <header>
        <b>Jira ticket</b>
        <Tag cls={ticket.status === 'Filed' ? 'ok' : ticket.status === 'Rejected' ? 'muted' : 'info'}>{ticket.status}</Tag>
        {ticket.flagged && <Tag cls="warn">Agent output needs review</Tag>}
        {ticket.jira_url
          ? <a className="btn ghost sm" href={ticket.jira_url} target="_blank" rel="noopener noreferrer">Open {ticket.jira_key} in Jira</a>
          : ticket.jira_key && <span className="mono">{ticket.jira_key}</span>}
      </header>
      {ticket.error && <div className="warnbox">{ticket.error}</div>}
      <label className="field">Title
        <input value={title} onChange={e => setTitle(e.target.value)} maxLength={250} disabled={!open || !!busy} />
      </label>
      <label className="field">Likely cause
        <textarea value={cause} onChange={e => setCause(e.target.value)} rows={3} maxLength={5000} disabled={!open || !!busy} />
      </label>
      <label className="field">Steps to reproduce, one per line
        <textarea value={steps} onChange={e => setSteps(e.target.value)} rows={4} disabled={!open || !!busy} />
      </label>
      <div className="qrow">
        <label className="field">Priority
          <select value={priority} onChange={e => setPriority(e.target.value as Ticket['priority'])} disabled={!open || !!busy}>
            <option>High</option><option>Medium</option><option>Low</option>
          </select>
        </label>
        <div className="field">Suggested assignee<div className="qvalue">{ticket.assignee || 'none'}</div></div>
      </div>
      {ticket.fix_text && <details className="qlog"><summary>Suggested fix in this ticket</summary><pre>{ticket.fix_text}</pre></details>}
      {!!ticket.memory_used.length && (
        <details className="qlog"><summary>QA Memory used ({ticket.memory_used.length})</summary>
          <ul className="qmem">{ticket.memory_used.map(m => <li key={m.id}>{m.pr_number ? `PR #${m.pr_number}: ` : ''}{m.text}</li>)}</ul>
        </details>
      )}
      {open && (
        <div className="qactions">
          {problem && <span className="qmuted">{problem}</span>}
          <button className="btn ghost sm danger" disabled={!!busy} onClick={() => act('reject')}>Reject</button>
          {dirty && <button className="btn ghost sm" disabled={!!busy || !!problem} onClick={() => act('save')}>{busy === 'save' ? 'Saving…' : 'Save draft'}</button>}
          <button className="btn sm" disabled={!!busy || !!problem} onClick={() => act('file')}>{busy === 'file' ? 'Filing…' : 'Approve and file in Jira'}</button>
        </div>
      )}
      <p className="qmuted">Nothing is sent to Jira until you approve it. Secrets are removed from attached logs.</p>
    </div>
  );
}

// ---------- Suggest a Fix (UC9) ----------

export function FixPanel({ result, fixes, ticketOpen, onFix }: { result: Result; fixes: Fix[]; ticketOpen: boolean; onFix: (f: Fix) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const latest = fixes[fixes.length - 1];

  async function suggest() {
    setBusy(true);
    try {
      onFix(await qa.suggestFix(result.id));
    } catch (err) {
      toast(message(err, 'No fix could be suggested'));
    } finally {
      setBusy(false);
    }
  }

  async function decide(approve: boolean) {
    setBusy(true);
    try {
      onFix(await qa.decideFix(latest.id, approve));
      toast(approve ? 'Added to the ticket draft' : 'Suggestion discarded');
    } catch (err) {
      toast(message(err, 'The decision could not be saved'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="qfix">
      <header>
        <b>Suggested fix</b>
        <span className="qmuted">Text only. Verixa never changes your repository.</span>
        <button className="btn ghost sm" disabled={busy} onClick={suggest}>
          {busy && (!latest || latest.status !== 'Suggested') ? 'Thinking…' : latest ? 'Suggest another' : 'Suggest a fix'}
        </button>
      </header>
      {latest && (
        <>
          <p>{latest.explanation}</p>
          <pre className="qdiff">{latest.diff.split('\n').map((line, i) => (
            <span key={i} className={line.startsWith('+') && !line.startsWith('+++') ? 'add' : line.startsWith('-') && !line.startsWith('---') ? 'del' : ''}>{line}{'\n'}</span>
          ))}</pre>
          {latest.status === 'Suggested' ? (
            <div className="qactions">
              <button className="btn ghost sm" disabled={busy} onClick={() => decide(false)}>Discard</button>
              <button className="btn sm" disabled={busy || !ticketOpen} onClick={() => decide(true)}
                      title={ticketOpen ? '' : 'There is no open ticket draft for this failure'}>Add to ticket draft</button>
            </div>
          ) : <Tag cls={latest.status === 'Added' ? 'ok' : 'muted'}>{latest.status}</Tag>}
        </>
      )}
    </div>
  );
}

// ---------- a drafted test for a coverage gap (UC5) ----------

export function DraftCard({ draft, onChange }: { draft: Draft; onChange: (d: Draft) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  async function decide(approve: boolean) {
    setBusy(true);
    try {
      onChange(await qa.decideDraft(draft.id, approve));
      if (approve) dispatchEvent(new Event('verixa:library-changed'));  // the Test Library screen reloads its files
      toast(approve ? `${draft.file_name} was added to the Test Library. It runs on the next Run Now` : 'Draft rejected');
    } catch (err) {
      toast(message(err, 'The decision could not be saved'));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="qdraft">
      <header>
        <span className="mono">{draft.file_name}</span>
        <span className="qmuted">no test covered <b>{draft.module}</b></span>
        <Tag cls={draft.status === 'Approved' ? 'ok' : draft.status === 'Rejected' ? 'muted' : 'info'}>{draft.status}</Tag>
      </header>
      <pre>{draft.code}</pre>
      {draft.status === 'Drafted' && (
        <div className="qactions">
          <button className="btn ghost sm" disabled={busy} onClick={() => decide(false)}>Reject</button>
          <button className="btn sm" disabled={busy} onClick={() => decide(true)}>Approve and add to library</button>
        </div>
      )}
    </div>
  );
}
