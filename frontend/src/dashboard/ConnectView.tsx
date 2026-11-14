import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { ApiError, api, linkAgain, qa, type Account, type Session, type Targets } from './api';
import { Chip, hookLabel, type HookState, type Link } from './connection';
import { icons } from './icons';
import { useToast } from './Toast';
import { loader } from '../shared/loader';

interface Props {
  hidden: boolean;
  account: Account | null;
  github: Session['github'];
  atlassian: Session['atlassian'];
  link: Link | null;
  hook: HookState;
  staging: string | null;
  onStaging: (url: string) => void;
  onConnected: (link: Link, hook: HookState) => void;
  onChangeRepo: () => void;
  onOpenLibrary: () => void;
}

interface Line {
  text: string;
  kind?: 'fin' | 'warnline';  // the last line: success, or a warning
}

type StepState = 'done' | 'active' | 'wait';
const STEP_LABEL: Record<StepState, string> = { done: 'Done', active: 'In progress', wait: 'Waiting' };

// One setup step. Steps that are not reached yet are dimmed and cannot be used.
function Step({ state, icon, title, hint, children }: { state: StepState; icon: ReactNode; title: string; hint: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => { if (ref.current) ref.current.inert = state === 'wait'; }, [state]);
  const cls = state === 'done' ? 'is-done' : state === 'active' ? 'is-active' : 'is-locked';
  return (
    <div className={'sec ' + cls} ref={ref}>
      <div className="lab"><span className="lic">{icon}</span><div><b>{title}</b><small>{hint}</small></div></div>
      <div>{children}</div>
    </div>
  );
}

function TimelineNode({ state, title, sub }: { state: StepState; title: string; sub: string }) {
  return (
    <li className={'node ' + state}>
      <i className="dot"></i>
      <div className="nbody"><span className="nst">{STEP_LABEL[state]}</span><b>{title}</b><small>{sub}</small></div>
    </li>
  );
}

export default function ConnectView({ hidden, account, github, atlassian, link, hook, staging, onStaging, onConnected, onChangeRepo, onOpenLibrary }: Props) {
  const toast = useToast();
  const [targets, setTargets] = useState<Targets>({ repos: [], projects: [] });
  const [targetsProblem, setTargetsProblem] = useState<{ message: string; relink: boolean } | null>(null);  // why the lists are empty
  const [repo, setRepo] = useState('');
  const [projectKey, setProjectKey] = useState('');
  const [lines, setLines] = useState<Line[]>([]);  // the terminal output of the last connect
  const [connecting, setConnecting] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const linked = !!(github && atlassian);
  const [stagingDraft, setStagingDraft] = useState(staging ?? '');
  const [stagingBusy, setStagingBusy] = useState(false);
  const [stagingNote, setStagingNote] = useState<{ text: string; bad: boolean } | null>(null);
  // Fill the box once the saved address arrives, but never overwrite what the tester already typed
  useEffect(() => { setStagingDraft(typed => typed || staging || ''); }, [staging]);

  async function saveStaging() {
    const url = stagingDraft.trim();
    if (!/^https?:\/\/[^\s]+$/i.test(url)) return setStagingNote({ text: 'Enter an http:// or https:// address, for example https://staging.example.com', bad: true });
    setStagingBusy(true);
    try {
      const res = await qa.saveStaging(url);
      onStaging(res.staging_url);
      setStagingDraft(res.staging_url);  // show exactly what was saved, without the trailing slash
      setStagingNote(res.reachable ? { text: `Saved. ${res.staging_url} answered`, bad: false }
                                   : { text: `Saved, but ${res.staging_url} did not answer. Start it before you run tests`, bad: true });
    } catch (err) {
      setStagingNote({ text: err instanceof ApiError ? err.message : 'The address could not be saved', bad: true });
    } finally {
      setStagingBusy(false);
    }
  }

  // Once both services are linked, load the repositories and Jira projects to choose from
  useEffect(() => {
    if (!linked) return;
    api.targets().then(t => {
      setTargets(t);
      setRepo(link?.repo ?? t.repos[0] ?? '');
      setProjectKey(link?.jiraKey ?? t.projects[0]?.key ?? '');
      if (!t.repos.length) setTargetsProblem({ message: 'No repository found. You need admin access to a repository to add a webhook', relink: false });
      else if (!t.projects.length) setTargetsProblem({ message: 'No Jira project found on this Atlassian site. Create one in Jira, then reload this page', relink: false });
    }).catch(err => {
      if (!(err instanceof ApiError && err.status === 401)) setTargetsProblem({ message: err.message, relink: err instanceof ApiError && err.status === 409 });
    });
  }, [linked]);

  // Step 1: link GitHub, step 2: choose a repository, step 3: create the webhook, then done
  const step = connecting ? 3 : link ? 4 : linked ? 2 : 1;
  const stateOf = (n: number): StepState => (n < step ? 'done' : n === step ? 'active' : 'wait');

  function signIn() {
    setLeaving(true);
    loader.show('Opening GitHub');
    location.href = '/auth/start';
  }

  async function connect() {
    if (!repo || !projectKey) return toast('Choose a repository and a Jira project');
    const start = [{ text: `Connecting to ${repo}` }];
    setLines(start);
    setConnecting(true);
    try {
      const res = await api.connect(repo, projectKey);
      const last: Line = res.warning
        ? { text: res.warning, kind: 'warnline' }
        : { text: 'Verixa is listening. Every new pull request is analysed automatically.', kind: 'fin' };
      setLines([...start, ...res.steps.map(text => ({ text })), last]);
      onConnected({ repo, jiraKey: projectKey, project: res.jira }, res.delivered ? 'ok' : 'wait');
      toast(res.warning ? 'Connected, but webhook delivery is not confirmed' : 'GitHub and Jira are connected');
    } catch (err) {
      const message = err instanceof ApiError && err.status === 401 ? 'Your session ended. Log in again to connect.' : (err as Error).message;
      setLines([...start, { text: message, kind: 'warnline' }]);
    }
    setConnecting(false);
  }

  function changeRepo() {
    setLines([]);
    onChangeRepo();
  }

  // What the first step says, depending on what is linked so far
  let signInLabel = 'Continue with GitHub and Atlassian', signedAs = '';
  if (linked) {
    signInLabel = 'GitHub and Jira linked';
    signedAs = `Linked as @${github!.login} with Jira site ${atlassian!.site}`;
  } else if (github) {
    signInLabel = 'Continue with Atlassian';
    signedAs = `GitHub is linked as @${github.login}. Approve Atlassian to finish.`;
  } else if (account) {
    signInLabel = 'Connect GitHub and Atlassian';
    signedAs = `Signed in as ${account.name}. Approve GitHub and Atlassian to link your workspace.`;
  }

  const hookHint = hook === 'ok' ? 'The webhook is active and verified.'
    : hook === 'wait' ? 'The webhook exists. Waiting for the first delivery from GitHub.'
    : 'Verixa creates it automatically once you connect.';

  return (
    <section className="workspace connect" hidden={hidden}>
      <article className="card">
        <div className="head">
          <h1>Connect your <em>workspace</em></h1>
          <p className="lead">Link GitHub and Jira once. Verixa connects your repository and Jira project, then sets up the webhook for you.</p>
          <div className="chips">
            <Chip on={!!github}>{github ? 'GitHub connected' : 'GitHub not connected'}</Chip>
            <Chip on={!!atlassian}>{atlassian ? 'Jira connected' : 'Jira not connected'}</Chip>
            <Chip on={hook === 'ok'}>{hookLabel(hook)}</Chip>
          </div>
        </div>

        <Step state={stateOf(1)} icon={icons.user} title="GitHub and Jira" hint="One approval covers both">
          <button className="btn act" disabled={linked || leaving} onClick={signIn}>{signInLabel}</button>
          {signedAs && <div className="note">{signedAs}</div>}
        </Step>

        <Step state={stateOf(2)} icon={icons.folder} title="Repository and project" hint="What Verixa watches, and where tickets go">
          {targetsProblem && (
            <div className="warnbox" role="alert" style={{ marginBottom: 12 }}>
              {targetsProblem.message}
              {targetsProblem.relink && <> <button type="button" className="btn sm ghost" onClick={linkAgain}>Link again</button></>}
            </div>
          )}
          <div className="formgrid act">
            <label className="field">Repository
              <select value={repo} onChange={e => setRepo(e.target.value)}>
                {targets.repos.map(r => <option key={r}>{r}</option>)}
              </select>
            </label>
            <label className="field">Jira project
              <select value={projectKey} onChange={e => setProjectKey(e.target.value)}>
                {targets.projects.map(p => <option key={p.key} value={p.key}>{p.name} ({p.key})</option>)}
              </select>
            </label>
            <button className="btn" disabled={connecting} onClick={connect}>Connect and create webhook</button>
          </div>
          {link && <div className="note">{link.repo} is linked to {link.project}</div>}
        </Step>

        <Step state={stateOf(3)} icon={icons.bolt} title="Webhook" hint="Created for you, never configured by hand">
          {lines.length ? (
            <div className="term">
              {lines.map((line, i) => (
                <div key={i} className={line.kind}>{line.kind ? '' : <><span className="p">$</span> </>}{line.text}</div>
              ))}
              {connecting && <span className="caret"></span>}
            </div>
          ) : (
            <p className="hintline">{hookHint}</p>
          )}
        </Step>

        <Step state={link ? (staging ? 'done' : 'active') : 'wait'} icon={icons.play} title="Staging app"
              hint="Where your tests run. Never the live system">
          <div className="formgrid">
            <label className="field" style={{ gridColumn: '1 / -1' }}>Staging address
              <input value={stagingDraft} onChange={e => { setStagingDraft(e.target.value); setStagingNote(null); }}
                     onKeyDown={e => { if (e.key === 'Enter' && !stagingBusy) saveStaging(); }}
                     placeholder="https://staging.example.com" maxLength={500} spellCheck={false} disabled={stagingBusy} />
            </label>
            <button className="btn" disabled={stagingBusy || !stagingDraft.trim() || stagingDraft.trim() === staging} onClick={saveStaging}>
              {stagingBusy ? 'Checking…' : staging ? 'Update staging address' : 'Save staging address'}
            </button>
          </div>
          {stagingNote ? <div className={stagingNote.bad ? 'warnbox' : 'note'} role="status">{stagingNote.text}</div>
            : <p className="hintline">Playwright opens it as baseURL and Newman gets it as {'{{baseUrl}}'}.</p>}
        </Step>

        <div className="bar">
          <span className={'state' + (link ? '' : ' idle')}>
            <i></i><span>{link ? 'Connected' : linked ? 'Choose a repository' : 'Waiting for GitHub and Jira'}</span>
          </span>
          <div className="bar-actions">
            {link && <button className="btn ghost" onClick={changeRepo}>Change repository</button>}
            <button className="btn" disabled={!link} onClick={onOpenLibrary}>Open Test Library</button>
          </div>
        </div>
      </article>

      <aside className="side">
        <div className="panel">
          <div className="ph">Setup progress</div>
          <p className="phint">Set up once, then upload tests and run them on staging.</p>
          <ol className="timeline">
            <TimelineNode state={stateOf(1)} title="Link GitHub and Jira" sub={linked ? `Linked as @${github!.login}` : 'GitHub and Atlassian'} />
            <TimelineNode state={stateOf(2)} title="Choose repository" sub={link ? `${link.repo}, ${link.project}` : 'Repository and Jira project'} />
            <TimelineNode state={stateOf(3)} title="Create webhook"
                          sub={hook === 'ok' ? 'Active and verified' : hook === 'wait' ? 'Created, waiting for GitHub' : 'Pull request events'} />
            <TimelineNode state={link ? (staging ? 'done' : 'active') : 'wait'} title="Staging app"
                          sub={staging ?? 'Where your tests run'} />
            <li className={'node base' + (step > 3 ? ' done' : '')}>
              <i className="dot"></i>
              <div className="nbody"><b>Test Library</b><small>{step > 3 ? 'Ready for your tests' : 'Opens when setup is done'}</small></div>
            </li>
          </ol>
        </div>
      </aside>
    </section>
  );
}
