import type { ReactNode } from 'react';
import AccountMenu from './AccountMenu';
import type { Account } from './api';
import { icons } from './icons';

export type View = 'connect' | 'library' | 'security' | 'risk' | 'profile' | 'runs' | 'tickets' | 'trends' | 'memory';

interface Props {
  view: View;
  onView: (view: View) => void;
  account: Account | null;
  unsavedChanges: number;
  onSignedOut: () => void;
}

// The narrow navigation bar on the left
export default function Rail({ view, onView, account, unsavedChanges, onSignedOut }: Props) {
  const item = (target: View, label: string, icon: ReactNode) => (
    <button className={'ri' + (view === target ? ' active' : '')} aria-label={label} data-tip={label} onClick={() => onView(target)}>
      {icon}
    </button>
  );

  return (
    <aside className="rail">
      <a className="logo" href="/" aria-label="Back to the Verixa website" data-tip="Back to website">
        <img src="/assets/verixa-logo.png" alt="Verixa" />
      </a>
      <nav className="rail-nav" aria-label="Main">
        {item('risk', 'Risk Analysis', icons.pullRequests)}
        {item('runs', 'Test Runs and Evidence', icons.testRuns)}
        {item('tickets', 'Jira Tickets', icons.jiraSync)}
        {item('trends', 'Risk Trends', icons.trends)}
        <span className="sep"></span>
        {item('library', 'Test Library', icons.library)}
        {item('memory', 'QA Memory', icons.memory)}
        {item('connect', 'Integrations', icons.integrations)}
      </nav>
      <AccountMenu account={account} unsavedChanges={unsavedChanges} onIntegrations={() => onView('connect')}
                   onSecurity={() => onView('security')} onProfile={() => onView('profile')} onSignedOut={onSignedOut} />
    </aside>
  );
}
