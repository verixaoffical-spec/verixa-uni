import type { ReactNode } from 'react';
import AccountMenu from './AccountMenu';
import type { Account } from './api';
import { icons } from './icons';

export type View = 'connect' | 'library' | 'security' | 'risk';

interface Props {
  view: View;
  onView: (view: View) => void;
  account: Account | null;
  unsavedChanges: number;
  onSignedOut: () => void;
}

// A page that is planned but not built yet
function ComingSoon({ label, icon }: { label: string; icon: ReactNode }) {
  return <button className="ri" disabled aria-label={label} data-tip={`${label}, coming soon`}>{icon}</button>;
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
        <ComingSoon label="Test Runs" icon={icons.testRuns} />
        <ComingSoon label="Evidence" icon={icons.evidence} />
        <ComingSoon label="Jira Sync" icon={icons.jiraSync} />
        <span className="sep"></span>
        {item('library', 'Test Library', icons.library)}
        <ComingSoon label="Agent Logs" icon={icons.agentLogs} />
        {item('connect', 'Integrations', icons.integrations)}
      </nav>
      <AccountMenu account={account} unsavedChanges={unsavedChanges} onIntegrations={() => onView('connect')}
                   onSecurity={() => onView('security')} onSignedOut={onSignedOut} />
    </aside>
  );
}
