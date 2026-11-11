import { useEffect, useRef, useState, type CSSProperties } from 'react';
import Footer from '../landing/Footer';
import Navbar from '../landing/Navbar';
import Scene from './Scene';
import { send } from './api';
import { destination } from './rules';

// /verify-email#token=...   the link from the sign up email. The account is created only when Verify is pressed,
// so a mail scanner that opens the link on its own creates nothing.
type View = 'ask' | 'bad' | 'taken' | 'done';

function takeToken(): string {
  const token = new URLSearchParams(location.hash.slice(1)).get('token') ?? '';
  if (location.hash) history.replaceState(null, '', location.pathname + location.search);
  return /^[\w-]{20,200}$/.test(token) ? token : '';
}

export default function VerifyEmail() {
  const [token] = useState(takeToken);
  const [view, setView] = useState<View>(token ? 'ask' : 'bad');
  const [submit, setSubmit] = useState<'idle' | 'busy' | 'done'>('idle');
  const [problem, setProblem] = useState('');
  const [lockedFor, setLockedFor] = useState(0);
  const titleRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    document.title = 'Verify your email · Verixa';
    const fontsReady = Promise.race([document.fonts.ready, new Promise(r => setTimeout(r, 400))]);
    fontsReady.then(() => document.body.classList.add('ready'));
  }, []);

  useEffect(() => { setTimeout(() => titleRef.current?.focus({ preventScroll: true }), 350); }, [view]);

  useEffect(() => {
    if (lockedFor <= 0) return;
    const timer = setTimeout(() => setLockedFor(s => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [lockedFor]);

  async function verify() {
    if (submit !== 'idle' || lockedFor > 0) return;
    setProblem('');
    setSubmit('busy');
    const res = await send('/auth/verify-email', { token });
    if (res.status === 200) {
      setSubmit('done');
      setView('done');
      setTimeout(() => location.replace(destination()), 1200);
      return;
    }
    setSubmit('idle');
    if (res.status === 429) return setLockedFor(Math.max(1, Math.ceil(res.retryAfter || res.detail?.retry_after || 60)));
    if (res.status === 400) return setView('bad');
    if (res.status === 409) return setView('taken');
    setProblem(res.status === 0
      ? 'Cannot reach Verixa. Check your connection and try again.'
      : res.status === 403 && typeof res.detail === 'string' ? res.detail
      : 'Something went wrong on our side. Please try again in a moment.');
  }

  return (
    <>
      <Scene />
      <Navbar />

      <main className="stage" id="top">
        <section className="glass enter" aria-labelledby="title">
          <div className="enter" style={{ '--i': 2 } as CSSProperties}>
            <h1 id="title" tabIndex={-1} ref={titleRef}>
              {view === 'ask' && <>Verify your <em>email</em></>}
              {view === 'bad' && <>Link not <em>valid</em></>}
              {view === 'taken' && <>Already <em>registered</em></>}
              {view === 'done' && <>Email <em>verified</em></>}
            </h1>
            <p className="sub">
              {view === 'ask' && 'Press the button below to confirm this is your email and create your Verixa account.'}
              {view === 'bad' && 'This verification link is not valid, or it has expired. Sign up again to get a new one.'}
              {view === 'taken' && 'An account with this email already exists. Log in instead.'}
              {view === 'done' && 'Your account is ready. Taking you to Verixa…'}
            </p>
          </div>

          {lockedFor > 0 ? (
            <div className="banner" role="alert">
              <span>Too many attempts. Try again in <b>{Math.floor(lockedFor / 60)}:{String(lockedFor % 60).padStart(2, '0')}</b>.</span>
            </div>
          ) : problem && <div className="banner" role="alert"><span>{problem}</span></div>}

          {(view === 'ask' || view === 'done') && (
            <form noValidate className="enter" style={{ '--i': 3 } as CSSProperties} onSubmit={e => { e.preventDefault(); verify(); }}>
              <button className="submit" type="submit" data-state={submit} aria-busy={submit === 'busy'}
                      disabled={lockedFor > 0 || view === 'done'}>
                <span className="lbl">Verify my email</span>
                <span className="spin" aria-hidden="true"></span>
                <span className="ok" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg></span>
              </button>
            </form>
          )}

          {view === 'bad' && <a className="submit as-link" href="/signup">Sign up again</a>}
          {view === 'taken' && <a className="submit as-link" href="/login">Log in</a>}
        </section>
      </main>

      <Footer />
    </>
  );
}
