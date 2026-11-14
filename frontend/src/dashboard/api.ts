// Talks to the FastAPI backend. Same origin, so the session cookie travels with every call.

import type { SavedFile, applyRequest } from './library';

export interface Account {
  name: string;
  email: string | null;
  github_login: string | null;
  two_factor: boolean;
}

export interface TwoFactorStatus {
  enabled: boolean;
  has_password: boolean;          // accounts made with GitHub have none, and must have signed in recently instead
  recovery_codes_left: number;
}

export interface Session {
  account: Account | null;
  github: { login: string; name: string } | null;
  atlassian: { site: string } | null;
  project: { repo: string; jira_key: string; jira_name: string; webhook_verified: boolean; staging_url: string | null } | null;
  specs: SavedFile[];
  collection: SavedFile | null;
}

export interface Targets {
  repos: string[];
  projects: { key: string; name: string }[];
}

export interface ConnectResult {
  jira: string;            // "Project name (KEY)"
  delivered: boolean;      // GitHub's test delivery arrived
  steps: string[];
  warning: string | null;
}

// ---- Risk Analysis (Deliverable 2) ----
// One assessment, exactly as backend/agent_db.py writes it. Every field comes from the Analysis
// Agent: the label and score from its rules, the reasoning and test areas from its model call.
export type RiskLabel = 'Low' | 'Medium' | 'High';
export type RiskState = 'queued' | 'running' | 'scored' | 'needs_human_review' | 'failed';

export interface Assessment {
  id: number;
  repo: string;
  pr_number: number;
  head_sha: string;
  title: string | null;
  pr_url: string | null;
  author: string | null;
  state: RiskState;
  risk_label: RiskLabel | null;
  base_label: RiskLabel | null;     // before the minimum-label floors were applied
  score: number | null;
  module: string | null;
  modules_touched: string[];
  files_changed: number | null;
  lines_changed: number | null;
  past_defects: number | null;
  sensitivity: string | null;
  scoring_basis: string | null;
  risk_factors: string[];           // the rule trace, one line per factor
  reasoning: string | null;
  test_areas: string[];
  model_used: string | null;
  concern: string | null;           // the model's doubt about the rule label. The label itself never changes
  attempts: number;                 // how many tries the Manager needed (retry cap is 3)
  errors: string[];
  created_at: string | null;
  updated_at: string | null;
}

export interface RiskFeed {
  project: { repo: string; jira_key: string; webhook_verified: boolean } | null;
  items: Assessment[];
  counts: Partial<Record<RiskLabel | 'total' | 'pending' | 'needs_review' | 'failed', number>>;
  agent_available: boolean;
}

export class ApiError extends Error {
  constructor(message: string, public status: number, public detail: any) {
    super(message);
  }
}

// Called on a 401, which only ever means the session is gone. App.tsx decides what to do.
let onSessionLost = () => {};
export function whenSessionLost(handler: () => void) {
  onSessionLost = handler;
}

async function request<T>(path: string, body?: object): Promise<T> {
  const res = await fetch(path, {
    method: body ? 'POST' : 'GET',
    credentials: 'same-origin',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401) onSessionLost();
    throw new ApiError(typeof data.detail === 'string' ? data.detail : 'Something went wrong', res.status, data.detail);
  }
  return data;
}

export const api = {
  session: () => request<Session>('/api/session'),
  targets: () => request<Targets>('/api/targets'),
  connect: (repo: string, projectKey: string) => request<ConnectResult>('/api/connect', { repo, project_key: projectKey }),
  // Saves, updates and deletes together. The server applies all of it or none of it.
  applyLibrary: (body: ReturnType<typeof applyRequest>) => request<unknown>('/api/library/apply', body),

  // Risk Analysis. The feed is polled while anything is still being scored.
  riskFeed: () => request<RiskFeed>('/api/analysis/pull-requests'),
  // Scores a pull request now instead of waiting for GitHub. Runs the agent and answers when done,
  // so it can take as long as the model chain takes.
  analysePr: (prNumber: number) => request<Assessment>('/api/analysis/analyse', { pr_number: prNumber }),

  // Two-step verification. Changing it asks for the password again, and turning it off also asks for a code.
  twoFactor: () => request<TwoFactorStatus>('/auth/2fa'),
  setupTwoFactor: (password: string) => request<{ qr: string; secret: string }>('/auth/2fa/setup', { password }),
  enableTwoFactor: (code: string) => request<{ account: Account; recovery_codes: string[] }>('/auth/2fa/enable', { code }),
  disableTwoFactor: (password: string, code: string) => request<{ account: Account }>('/auth/2fa/disable', { password, code }),
  newRecoveryCodes: (password: string, code: string) => request<{ recovery_codes: string[] }>('/auth/2fa/recovery-codes', { password, code }),

  // Profile. Deleting asks for the password again, and a code when two-step verification is on.
  renameAccount: (name: string) => request<{ account: Account }>('/api/account/name', { name }),
  deleteAccount: (password: string, code: string) => request<null>('/api/account/delete', { password, code }),
};

// One step of an agent run, pushed by the server over the WebSocket at /api/live
export interface LiveEvent {
  type: 'agent';
  repo: string;
  pr: number;
  run_id: string | null;
  at: string;
  event: string;
  text: string;
  level: 'info' | 'ok' | 'warn' | 'error';
  done: boolean;     // the last message of a run: the result is saved, or it stopped
  replay?: boolean;  // sent again because the page connected while the run was going on
}

// Opens the live status connection and keeps it open: it reconnects with a growing delay after a drop,
// and pings every 25 seconds so tunnels such as ngrok do not close it while the screen is idle.
export function openLive(onEvent: (event: LiveEvent) => void, onStatus: (connected: boolean) => void): () => void {
  let socket: WebSocket | null = null;
  let stopped = false, delay = 1000, retry = 0, ping = 0;

  const connect = () => {
    socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/live`);
    socket.onopen = () => {
      delay = 1000;
      onStatus(true);
      ping = window.setInterval(() => { if (socket?.readyState === WebSocket.OPEN) socket.send('ping'); }, 25000);
    };
    socket.onmessage = message => {
      try {
        const data = JSON.parse(message.data);
        if (data?.type === 'agent') onEvent(data as LiveEvent);
      } catch { /* not a message for this page */ }
    };
    socket.onclose = event => {
      clearInterval(ping);
      onStatus(false);
      if (stopped) return;
      if (event.code === 4401) return onSessionLost();  // signed out in another tab
      retry = window.setTimeout(connect, delay);
      delay = Math.min(delay * 2, 30000);
    };
  };

  connect();
  return () => {
    stopped = true;
    clearTimeout(retry);
    clearInterval(ping);
    socket?.close();
  };
}

// Forgets saved GitHub and Atlassian sign ins that stopped working, then asks for them again.
export async function linkAgain(): Promise<void> {
  await fetch('/auth/relink', { method: 'POST', credentials: 'same-origin' });
  location.href = '/auth/start';
}

export async function signOut(): Promise<boolean> {
  try {
    const res = await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' });
    return res.ok || res.status === 401;  // 401: already signed out
  } catch {
    return false;
  }
}


// ---- Test runs, tickets, fixes, comparison, trends and QA Memory (UC4 to UC11) ----
export type Outcome = 'passed' | 'real_bug' | 'temporary_error' | 'deployment_pending' | 'skipped';
export type RunStatus = 'running' | 'finished' | 'flagged' | 'failed';

export interface Run {
  id: number;
  pr_number: number;
  head_sha: string | null;
  risk_label: RiskLabel | null;
  module: string | null;
  status: RunStatus;
  step: string | null;
  error: string | null;
  staging_url: string;
  selection: { specs?: string[]; reason?: string; collection?: string | null; modules?: string[] };
  started_by: string | null;
  started_at: string | null;
  ended_at: string | null;
  counts: Record<Outcome | 'total' | 'retried', number>;
}

export interface Result {
  id: number;
  kind: 'playwright' | 'newman';
  file: string;
  title: string;
  outcome: Outcome;
  retried: boolean;
  error: string | null;
  ms: number;
  evidence: { id: number; type: 'screenshot' | 'trace' | 'console_log' | 'network_log' }[];
}

export interface Ticket {
  id: number;
  result_id: number;
  run_id: number | null;
  test: string | null;
  title: string;
  steps: string[];
  root_cause: string;
  priority: 'High' | 'Medium' | 'Low';
  assignee: string | null;
  fix_text: string | null;
  status: 'Drafted' | 'Filed' | 'Rejected';
  flagged: boolean;
  jira_key: string | null;
  jira_url: string | null;
  error: string | null;
  model_used: string | null;
  created_at: string | null;
  filed_at: string | null;
  memory_used: { id: number; text: string; pr_number: number | null }[];
}

export interface Fix { id: number; result_id: number; diff: string; explanation: string; status: 'Suggested' | 'Added' | 'Discarded'; model_used: string | null }
export interface Draft { id: number; run_id: number; module: string; file_name: string; code: string; status: 'Drafted' | 'Approved' | 'Rejected'; model_used: string | null; created_at: string | null }
export interface RunDetail { run: Run; results: Result[]; tickets: Ticket[]; fixes: Fix[]; drafts: Draft[] }

export interface Comparison {
  a: Run;
  b: Run;
  summary: Record<string, number>;
  rows: { kind: string; file: string; title: string; tag: string; before: { id: number; outcome: Outcome } | null;
          after: { id: number; outcome: Outcome } | null; ticket_id: number | null }[];
}

export interface Trends {
  enough: boolean;
  minimum: number;
  days: number;
  module: string | null;
  total: number;
  share: Record<RiskLabel, number>;
  periods: ({ period: string } & Record<RiskLabel, number>)[];
  modules: { module: string; failures: number; real_bugs: number }[];
  all_modules: string[];
  pull_requests: { pr_number: number; title: string | null; risk_label: RiskLabel; module: string | null; created_at: string;
                   last_run: { passed: number; real_bug: number; status: RunStatus } | null; tickets: { key: string; url: string | null }[] }[];
}

export interface MemoryItem { id: number; kind: string; module: string | null; pr_number: number | null; text: string; decision: string | null; created_at: string | null }

export const qa = {
  saveStaging: (url: string) => request<{ staging_url: string; reachable: boolean }>('/api/project/staging', { url }),
  runNow: (assessmentId: number) => request<Run>('/api/runs', { assessment_id: assessmentId }),
  runs: () => request<{ items: Run[]; staging_url: string | null }>('/api/runs'),
  run: (id: number) => request<RunDetail>(`/api/runs/${id}`),
  evidenceUrl: (id: number) => `/api/evidence/${id}`,
  decideDraft: (id: number, approve: boolean) => request<Draft>(`/api/drafts/${id}/decision`, { approve }),
  tickets: () => request<{ items: Ticket[] }>('/api/tickets'),
  editTicket: (id: number, body: Pick<Ticket, 'title' | 'root_cause' | 'steps' | 'priority'>) => request<Ticket>(`/api/tickets/${id}`, body),
  fileTicket: (id: number) => request<Ticket>(`/api/tickets/${id}/file`, {}),
  rejectTicket: (id: number) => request<Ticket>(`/api/tickets/${id}/reject`, {}),
  suggestFix: (resultId: number) => request<Fix>(`/api/results/${resultId}/fix`, {}),
  decideFix: (id: number, approve: boolean) => request<Fix>(`/api/fixes/${id}/decision`, { approve }),
  compare: (a?: number, b?: number) => request<Comparison>('/api/compare' + (a && b ? `?a=${a}&b=${b}` : '')),
  trends: (days: number, module: string) =>
    request<Trends>(`/api/trends?days=${days}${module ? '&module=' + encodeURIComponent(module) : ''}`),
  memory: () => request<{ items: MemoryItem[] }>('/api/memory'),
  forget: (id: number) => request<null>(`/api/memory/${id}/delete`, {}),
};
