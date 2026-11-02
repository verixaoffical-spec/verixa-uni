// A static picture of the product, shown under the hero. Nothing here is live data.
import type { ReactNode } from 'react';

const ICONS: Record<string, ReactNode> = {
  pr: <><circle cx="6" cy="6" r="2.5" /><circle cx="6" cy="18" r="2.5" /><circle cx="18" cy="18" r="2.5" /><path d="M6 8.5v7M18 15.5V9a3 3 0 00-3-3h-4" /></>,
  runs: <path d="M7 4.5v15l13-7.5z" />,
  evidence: <><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.2-4.2" /></>,
  jira: <path d="M4 12a8 8 0 0114-5.3M20 12a8 8 0 01-14 5.3M18 3v4h-4M6 21v-4h4" />,
  library: <><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><path d="M14 2v6h6" /></>,
  logs: <path d="M4 17l6-5-6-5M12 19h8" />,
  plug: <><path d="M12 22v-5M9 8V2M15 8V2" /><path d="M18 8v5a4 4 0 01-4 4h-4a4 4 0 01-4-4V8z" /></>,
  search: <><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.2-4.2" /></>,
  bug: <><rect x="7" y="7" width="10" height="13" rx="5" /><path d="M12 7V4M4 13h3M17 13h3M5 7l2.5 2M19 7l-2.5 2M5 19l2.5-2M19 19l-2.5-2" /></>,
  ticket: <path d="M4 7a2 2 0 012-2h12a2 2 0 012 2v3a2 2 0 000 4v3a2 2 0 01-2 2H6a2 2 0 01-2-2v-3a2 2 0 000-4z" />,
  clock: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></>,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
};
const Icon = ({ name }: { name: string }) => <svg viewBox="0 0 24 24" aria-hidden="true">{ICONS[name]}</svg>;

const NAV = [
  { label: 'Pipeline' },
  { item: 'Pull Requests', icon: 'pr', active: true, count: 6 },
  { item: 'Test Runs', icon: 'runs' },
  { item: 'Evidence', icon: 'evidence' },
  { item: 'Jira Sync', icon: 'jira' },
  { label: 'System' },
  { item: 'Test Library', icon: 'library' },
  { item: 'Agent Logs', icon: 'logs' },
  { item: 'Integrations', icon: 'plug' },
];

// Each stat has a small trend line: values from 0 (bottom) to 10 (top)
const STATS = [
  { label: 'Tests run today', icon: 'runs', value: '312', delta: '+18% vs yesterday', trend: [3, 4, 3, 5, 6, 5, 7, 9] },
  { label: 'Bugs caught', icon: 'bug', value: '7', delta: 'before merge', trend: [2, 3, 2, 4, 3, 5, 6, 7], accent: true },
  { label: 'Tickets filed', icon: 'ticket', value: '5', delta: 'auto-drafted', trend: [1, 2, 2, 3, 3, 4, 4, 5] },
  { label: 'Avg. verify time', icon: 'clock', value: '2m 40s', delta: '−32s this week', trend: [9, 8, 8, 6, 7, 5, 4, 4] },
];

const PULL_REQUESTS = [
  { id: '#482', title: 'Refactor checkout session', meta: 'checkout · 3 files', by: 'JO', hue: 12, risk: 'high', status: 'Investigating', tests: 0.82 },
  { id: '#481', title: 'Update pricing tier copy', meta: 'billing · 1 file', by: 'SK', hue: 190, risk: 'low', status: 'Verified', tests: 1 },
  { id: '#479', title: 'Add SSO redirect handling', meta: 'auth · 6 files', by: 'MK', hue: 252, risk: 'med', status: 'Running tests', tests: 0.58 },
  { id: '#477', title: 'Fix cart total rounding', meta: 'checkout · 2 files', by: 'AL', hue: 150, risk: 'low', status: 'Verified', tests: 1 },
  { id: '#476', title: 'Retry failed webhook deliveries', meta: 'integrations · 4 files', by: 'RN', hue: 320, risk: 'med', status: 'Verified', tests: 1 },
  { id: '#474', title: 'Cache product search results', meta: 'search · 5 files', by: 'SK', hue: 190, risk: 'low', status: 'Running tests', tests: 0.31 },
];
const RISK_LABEL: Record<string, string> = { low: 'Low', med: 'Medium', high: 'High' };
const STATUS_CLASS: Record<string, string> = { Verified: 'done', 'Running tests': 'run', Investigating: 'look' };

const ACTIVITY = [
  { who: 'Test Agent', what: 'running 48 tests on #479', when: 'now', live: true },
  { who: 'Analysis Agent', what: 'flagged a risky change in checkout', when: '1m' },
  { who: 'Jira Agent', what: 'drafted CHK-112 for #482', when: '3m' },
  { who: 'Test Agent', what: 'verified #481, 22 of 22 passed', when: '6m', ok: true },
];

function Sparkline({ points }: { points: number[] }) {
  const line = points.map((v, i) => `${(i / (points.length - 1)) * 100},${30 - v * 2.6}`).join(' ');
  return (
    <svg className="mock-spark" viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true">
      <polygon points={`0,32 ${line} 100,32`} />
      <polyline points={line} />
    </svg>
  );
}

export default function MockDashboard() {
  return (
    <div className="mock-window">
      <div className="mock-chrome">
        <div className="mock-lights"><i></i><i></i><i></i></div>
        <div className="mock-search"><Icon name="search" />Search pull requests, runs, tickets<kbd>⌘K</kbd></div>
        <div className="mock-integ"><span className="mock-dot-live"></span>GitHub · Jira connected</div>
      </div>

      <div className="mock-app">
        <div className="mock-sidebar">
          <div className="mock-brand"><img className="logo-mark" src="/assets/verixa-logo.png" alt="" /><span>Verixa</span></div>
          {NAV.map((n, i) => n.label
            ? <div key={i} className="mock-nav-label">{n.label}</div>
            : <div key={i} className={'mock-nav-item' + (n.active ? ' active' : '')}>
                <Icon name={n.icon!} />{n.item}
                {n.count && <span className="mock-badge-count">{n.count}</span>}
              </div>)}
          <div className="mock-sidebar-footer">
            <div className="mock-avatar">MK</div>
            <div><div className="mock-fname">Maya Kessler</div><div className="mock-frole">Northlane</div></div>
          </div>
        </div>

        <div className="mock-main">
          <div className="mock-topline">
            <div>
              <div className="mock-title">Pull Requests</div>
              <div className="mock-sub"><span className="mock-dot-live pulse"></span>6 open · agents watching in real time</div>
            </div>
            <div className="mock-btn">Approve &amp; Run</div>
          </div>

          <div className="mock-stats">
            {STATS.map(s => (
              <div key={s.label} className={'mock-stat' + (s.accent ? ' accent' : '')}>
                <div className="mock-stat-label"><Icon name={s.icon} />{s.label}</div>
                <div className="mock-stat-value">{s.value}</div>
                <div className="mock-stat-delta">{s.delta}</div>
                <Sparkline points={s.trend} />
              </div>
            ))}
          </div>

          <div className="mock-split">
            <div className="mock-card">
              <table className="mock-table">
                <thead><tr><th>Pull request</th><th>Risk</th><th>Tests</th><th>Status</th></tr></thead>
                <tbody>
                  {PULL_REQUESTS.map(pr => (
                    <tr key={pr.id}>
                      <td>
                        <div className="mock-pr">
                          <span className="mock-pr-avatar" style={{ background: `hsl(${pr.hue} 55% 45%)` }}>{pr.by}</span>
                          <div><div className="mock-pr-title"><b>{pr.id}</b> {pr.title}</div><div className="mock-pr-meta">{pr.meta}</div></div>
                        </div>
                      </td>
                      <td><span className={'mock-badge ' + pr.risk}><i></i>{RISK_LABEL[pr.risk]}</span></td>
                      <td>
                        <div className={'mock-progress' + (pr.tests < 1 ? ' live' : '')}><span style={{ width: `${pr.tests * 100}%` }}></span></div>
                      </td>
                      <td><span className={'mock-status ' + STATUS_CLASS[pr.status]}>
                        {pr.status === 'Verified' && <Icon name="check" />}{pr.status}
                      </span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="mock-card mock-feed">
              <div className="mock-feed-head">Agent activity<span>Live</span></div>
              {ACTIVITY.map((a, i) => (
                <div key={i} className={'mock-event' + (a.live ? ' live' : '') + (a.ok ? ' ok' : '')}>
                  <i></i>
                  <div><b>{a.who}</b> {a.what}<small>{a.when}</small></div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
