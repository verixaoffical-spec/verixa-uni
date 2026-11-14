import { useEffect, useRef, useState } from 'react';
import { api, signOut, whenSessionLost, type Account, type Session } from './api';
import ConnectView from './ConnectView';
import LibraryView from './LibraryView';
import Rail, { type View } from './Rail';
import RiskView from './RiskView';
import RunsView from './RunsView';
import TicketsView from './TicketsView';
import TrendsView from './TrendsView';
import MemoryView from './MemoryView';
import ProfileView from './ProfileView';
import SecurityView from './SecurityView';
import type { HookState, Link } from './connection';
import { useLibrary } from './useLibrary';
import { useToast } from './Toast';
import { loader } from '../shared/loader';
import { urlError } from '../shared/urlError';

// Set when this page leaves on purpose, so the "unsaved changes" prompt stays quiet
let leaving = false;
function leave(url: string) {
  leaving = true;
  location.replace(url);
}
const goLogin = (flag: string) => leave(`/login?${flag}&next=${encodeURIComponent(location.pathname)}${location.hash}`);

const wait = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
const VIEWS: View[] = ['connect', 'library', 'security', 'risk', 'profile', 'runs', 'tickets', 'trends', 'memory'];
// Screens that need a connected project. Opened before connecting, they show their own "connect first" screen.
const PROJECT_VIEWS: View[] = ['library', 'risk', 'runs', 'tickets', 'trends', 'memory'];
const viewFromHash = (): View => {
  const wanted = location.hash.slice(1) as View;
  return VIEWS.includes(wanted) ? wanted : 'connect';
};

export default function App() {
  const toast = useToast();
  const library = useLibrary();
  const [view, setView] = useState<View>(viewFromHash);
  const [account, setAccount] = useState<Account | null>(null);
  const [github, setGithub] = useState<Session['github']>(null);
  const [atlassian, setAtlassian] = useState<Session['atlassian']>(null);
  const [link, setLink] = useState<Link | null>(null);
  const [hook, setHook] = useState<HookState>('off');
  const [staging, setStaging] = useState<string | null>(null);
  const [openRun, setOpenRun] = useState<{ id: number } | null>(null);  // a new object each time, so opening the same run again still works

  // The view is kept in the address (#connect or #library), so a refresh or a shared link reopens it
  function show(next: View) {
    if (location.hash !== '#' + next) history.replaceState(null, '', '#' + next);
    setView(next);
    scrollTo(0, 0);
  }

  // ---- loading the session on start ----
  const booted = useRef(false);
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    boot();
  }, []);

  async function boot() {
    const error = new URLSearchParams(location.search).get('error');  // from a failed GitHub or Atlassian sign in
    if (error) history.replaceState(null, '', location.pathname + location.hash);

    // Try three times, in case the server is restarting
    let s: Session | null = null;
    for (let attempt = 0; attempt < 3 && !s; attempt++) {
      try {
        s = await api.session();
      } catch {
        if (attempt < 2) await wait(800 * (attempt + 1));
      }
    }
    if (!s) {
      await loader.hide();
      toast('Cannot reach the Verixa server. Check your connection and reload', { label: 'Reload', run: () => location.reload() });
      return;
    }
    // The server already guards this page. This catches a session that ended between the page and this call.
    if (!s.account) return goLogin('expired');

    setAccount(s.account);
    setGithub(s.github);
    setAtlassian(s.atlassian);
    await loader.hide();
    if (error) toast(urlError(error));

    // Security settings and the profile open whatever is linked. The address is read now: it may have changed while loading.
    const wanted = location.hash.slice(1);
    const open = (next: View) => show(location.hash === '#security' ? 'security' : location.hash === '#profile' ? 'profile' : next);
    const p = s.project;
    if (!s.github || !s.atlassian) {
      // Asking for the Test Library or Risk Analysis before linking shows their "connect first" screen
      open(PROJECT_VIEWS.includes(wanted as View) ? wanted as View : 'connect');
      return;
    }
    if (!p) return open('connect');
    setLink({ repo: p.repo, jiraKey: p.jira_key, project: `${p.jira_name} (${p.jira_key})` });
    setHook(p.webhook_verified ? 'ok' : 'wait');
    setStaging(p.staging_url);
    library.load(s);
    open(wanted === 'connect' || PROJECT_VIEWS.includes(wanted as View) ? wanted as View : 'library');
  }

  // ---- the session ending while the page is open ----
  const unsaved = useRef(0);
  unsaved.current = library.changes;
  const lostShown = useRef(false);
  useEffect(() => {
    whenSessionLost(() => {
      // Unsaved library work is never thrown away without asking
      if (!unsaved.current) return goLogin('expired');
      if (lostShown.current) return;
      lostShown.current = true;
      toast('Your session ended. Log in again in a new tab, then confirm here. Your changes are kept', {
        label: 'Log in',
        run: () => { lostShown.current = false; window.open('/login', '_blank', 'noopener'); },
      });
    });
  }, []);

  // An approved drafted test was added to the library on the server. Reload it, unless there is unsaved work there:
  // that is never thrown away, and saving it later shows the Reload latest banner instead.
  useEffect(() => {
    const refresh = async () => {
      if (unsaved.current) return;
      try { library.load(await api.session()); } catch { /* the next page load reads it */ }
    };
    addEventListener('verixa:library-changed', refresh);
    return () => removeEventListener('verixa:library-changed', refresh);
  }, []);

  // ---- browser events ----
  useEffect(() => {
    const onHashChange = () => setView(viewFromHash());
    // Back after signing out can restore a frozen copy of this page. Check with the server again.
    const onPageShow = (e: PageTransitionEvent) => { if (e.persisted) location.reload(); };
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (unsaved.current && !leaving) { e.preventDefault(); e.returnValue = ''; }
    };
    // A file dropped outside the drop zones must not open in the browser and lose the page
    const stopDrop = (e: DragEvent) => e.preventDefault();

    addEventListener('hashchange', onHashChange);
    addEventListener('pageshow', onPageShow);
    addEventListener('beforeunload', onBeforeUnload);
    addEventListener('dragover', stopDrop);
    addEventListener('drop', stopDrop);
    return () => {
      removeEventListener('hashchange', onHashChange);
      removeEventListener('pageshow', onPageShow);
      removeEventListener('beforeunload', onBeforeUnload);
      removeEventListener('dragover', stopDrop);
      removeEventListener('drop', stopDrop);
    };
  }, []);

  // Ctrl+Enter (Cmd+Enter on a Mac) confirms the import
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && view === 'library') {
        e.preventDefault();
        library.confirm();
      }
    };
    addEventListener('keydown', onKeyDown);
    return () => removeEventListener('keydown', onKeyDown);
  });

  function onSignedOut() {
    loader.show('Signing you out');
    leave('/login?signed_out');
  }

  return (
    <div className="app">
      <Rail view={view} onView={show} account={account} unsavedChanges={library.changes} onSignedOut={onSignedOut} />
      <main>
        <ConnectView hidden={view !== 'connect'} account={account} github={github} atlassian={atlassian} link={link} hook={hook}
                     staging={staging} onStaging={setStaging}
                     onConnected={(newLink, newHook) => { setLink(newLink); setHook(newHook); }}
                     onChangeRepo={() => { setLink(null); setHook('off'); }}
                     onOpenLibrary={() => show('library')} />
        <LibraryView hidden={view !== 'library'} link={link} hook={hook} library={library} onGoConnect={() => show('connect')} />
        <RiskView hidden={view !== 'risk'} link={link} hook={hook} staging={staging} onGoConnect={() => show('connect')}
                  onRunStarted={id => { setOpenRun({ id }); show('runs'); }} />
        <RunsView hidden={view !== 'runs'} link={link} openRun={openRun} onGoConnect={() => show('connect')} />
        <TicketsView hidden={view !== 'tickets'} link={link} onGoConnect={() => show('connect')}
                     onOpenRun={id => { setOpenRun({ id }); show('runs'); }} />
        <TrendsView hidden={view !== 'trends'} link={link} onGoConnect={() => show('connect')} onOpenRisk={() => show('risk')} />
        <MemoryView hidden={view !== 'memory'} link={link} onGoConnect={() => show('connect')} />
        <ProfileView hidden={view !== 'profile'} account={account} onAccount={setAccount}
                     onDeleted={() => { loader.show('Signing you out'); leave('/login?deleted'); }}
                     onSignInAgain={() => signOut().then(() => goLogin('reauth'))} />
        <SecurityView hidden={view !== 'security'} onAccount={setAccount} onSignInAgain={() => signOut().then(() => goLogin('reauth'))} />
      </main>
    </div>
  );
}
