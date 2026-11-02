import type { ReactNode } from 'react';

// The repository and Jira project this account is connected to
export interface Link {
  repo: string;
  jiraKey: string;
  project: string;  // "Project name (KEY)"
}

// off: no webhook. wait: created, no delivery from GitHub yet. ok: GitHub's test delivery arrived.
export type HookState = 'off' | 'wait' | 'ok';

export const hookLabel = (hook: HookState) =>
  hook === 'ok' ? 'Webhook verified' : hook === 'wait' ? 'Webhook waiting' : 'No webhook';

// A small status pill with a green dot when on
export function Chip({ on, children }: { on: boolean; children: ReactNode }) {
  return <span className={'chip' + (on ? ' on' : '')}><i></i><span>{children}</span></span>;
}
