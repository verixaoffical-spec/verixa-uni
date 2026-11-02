import { useEffect, useRef, useState } from 'react';
import { api, signOut, whenSessionLost, type Account, type Session } from './api';
import ConnectView from './ConnectView';
import LibraryView from './LibraryView';
import Rail, { type View } from './Rail';
import RiskView from './RiskView';
import SecurityView from './SecurityView';
import type { HookState, Link } from './connection';
import { useLibrary } from './useLibrary';
import { useToast } from './Toast';
import { loader } from '../shared/loader';

// Set when this page leaves on purpose, so the "unsaved changes" prompt stays quiet
let leaving = false;
function leave(url: string) {
  leaving = true;
  location.replace(url);
}
const goLogin = (flag: string) => leave(`/login?${flag}&next=${encodeURIComponent(location.pathname)}${location.hash}`);

const wait = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
const VIEWS: View[] = ['connect', 'library', 'security', 'risk'];
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
    const wanted = location.hash.slice(1);
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
    if (error) toast(error.slice(0, 200));

    // Security settings open whatever is linked. Read the address again: it may have changed while loading.
    const open = (next: View) => show(location.hash === '#security' ? 'security' : next);
    const p = s.project;
    if (!s.github || !s.atlassian) {
      // Asking for the Test Library or Risk Analysis before linking shows their "connect first" screen
      open(wanted === 'library' || wanted === 'risk' ? wanted : 'connect');
      return;
    }
    if (!p) return open('connect');
    setLink({ repo: p.repo, jiraKey: p.jira_key, project: `${p.jira_name} (${p.jira_key})` });
    setHook(p.webhook_verified ? 'ok' : 'wait');
    library.load(s);
    open(wanted === 'connect' ? 'connect' : wanted === 'risk' ? 'risk' : 'library');
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
                     onConnected={(newLink, newHook) => { setLink(newLink); setHook(newHook); }}
                     onChangeRepo={() => { setLink(null); setHook('off'); }}
                     onOpenLibrary={() => show('library')} />
        <LibraryView hidden={view !== 'library'} link={link} hook={hook} library={library} onGoConnect={() => show('connect')} />
        <RiskView hidden={view !== 'risk'} link={link} hook={hook} onGoConnect={() => show('connect')} />
        <SecurityView hidden={view !== 'security'} onAccount={setAccount} onSignInAgain={() => signOut().then(() => goLogin('reauth'))} />
      </main>
    </div>
  );
}
