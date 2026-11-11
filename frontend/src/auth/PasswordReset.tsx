import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type FormEvent } from 'react';
import Footer from '../landing/Footer';
import Navbar from '../landing/Navbar';
import Scene from './Scene';
import { send, type Reply } from './api';
import { hasLetterAndNumber, normEmail, problem, strength } from './rules';

// Two pages that share this card:
//   /forgot-password            asks for the email and sends a link
//   /reset-password#token=...   the link from the email, where the new password is chosen
type View = 'ask' | 'sent' | 'choose' | 'done';
interface Banner { message: string; kind: 'error' | 'info' }

const STRENGTH_LABEL = ['', 'Weak', 'Fair', 'Good', 'Strong'];
const finePointer = matchMedia('(pointer: fine)').matches;
const EMPTY = { name: '', email: '', password: '' };

// The token is after # so it never reaches the server's logs. It is read once, then removed from the address bar.
function takeToken(): string {
  const token = new URLSearchParams(location.hash.slice(1)).get('token') ?? '';
  if (location.hash) history.replaceState(null, '', location.pathname + location.search);
  return /^[\w-]{20,200}$/.test(token) ? token : '';
}

function problemFor(res: Reply): string {
  if (res.status === 0) return res.timeout
    ? 'Verixa is taking too long to answer. Check your connection and try again.'
    : 'Cannot reach Verixa. Check your connection and try again.';
  if (res.status === 400 && typeof res.detail === 'string') return res.detail;
  if (res.status === 403) return typeof res.detail === 'string' ? res.detail : 'This request was blocked. Reload the page and try again.';
  return 'Something went wrong on our side. Please try again in a moment.';
}

export default function PasswordReset() {
  const resetting = location.pathname.startsWith('/reset-password');
  const [token] = useState(() => (resetting ? takeToken() : ''));
  const [view, setView] = useState<View>(resetting ? 'choose' : 'ask');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [again, setAgain] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<{ field: 'email' | 'password' | 'again'; message: string } | null>(null);
  const [banner, setBanner] = useState<Banner | null>(
    resetting && !token ? { message: 'This reset link is not complete. Open the link from the email again, or ask for a new one.', kind: 'error' } : null);
  const [badLink, setBadLink] = useState(resetting && !token);
  const [lockedFor, setLockedFor] = useState(0);
  const [submit, setSubmit] = useState<'idle' | 'busy' | 'done'>('idle');
  const cardRef = useRef<HTMLElement>(null);
  const firstRef = useRef<HTMLInputElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    document.title = (resetting ? 'Choose a new password' : 'Forgot password') + ' · Verixa';
    const fontsReady = Promise.race([document.fonts.ready, new Promise(r => setTimeout(r, 400))]);
    fontsReady.then(() => document.body.classList.add('ready'));
  }, []);

  // Each new view moves focus, so keyboard and screen reader users follow along
  useLayoutEffect(() => {
    const target = view === 'sent' || view === 'done' || badLink ? titleRef.current : firstRef.current;
    if (finePointer || view === 'sent' || view === 'done') setTimeout(() => target?.focus({ preventScroll: true }), 350);
  }, [view, badLink]);

  useEffect(() => {
    if (lockedFor <= 0) return;
    const timer = setTimeout(() => setLockedFor(s => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [lockedFor]);

  function fail(res: Reply) {
    setSubmit('idle');
    if (res.status === 429) return setLockedFor(Math.max(1, Math.ceil(res.retryAfter || res.detail?.retry_after || 60)));
    const field = res.detail?.field;
    if (res.status === 422 && (field === 'email' || field === 'password')) {
      setError({ field, message: res.detail.message });
      return firstRef.current?.focus();
    }
    if (res.status === 400) setBadLink(true);
    setBanner({ message: problemFor(res), kind: 'error' });
  }

  async function askForLink(e: FormEvent) {
    e.preventDefault();
    if (submit !== 'idle' || lockedFor > 0) return;
    setBanner(null);
    const message = problem('email', { ...EMPTY, email }, 'login');
    if (message) {
      setError({ field: 'email', message });
      return firstRef.current?.focus();
    }
    setError(null);
    setSubmit('busy');
    const res = await send('/auth/forgot', { email: normEmail(email) });
    if (res.status === 202) {
      setSubmit('idle');
      setView('sent');
      return;
    }
    fail(res);
  }

  async function choosePassword(e: FormEvent) {
    e.preventDefault();
    if (submit !== 'idle' || lockedFor > 0 || badLink) return;
    setBanner(null);
    const message = problem('password', { ...EMPTY, password }, 'signup');
    if (message) {
      setError({ field: 'password', message });
      return firstRef.current?.focus();
    }
    if (again !== password) {
      setError({ field: 'again', message: 'The two passwords do not match' });
      return document.getElementById('again')?.focus();
    }
    setError(null);
    setSubmit('busy');
    const res = await send('/auth/reset', { token, password });
    if (res.status === 200) {
      setSubmit('done');
      setPassword('');
      setAgain('');
      setTimeout(() => { setSubmit('idle'); setView('done'); }, 500);
      return;
    }
    fail(res);
  }

  const errorFor = (field: 'email' | 'password' | 'again') =>
    error?.field === field ? <p className="err" id={field + 'Err'}>{error.message}</p> : null;
  const score = strength(password);

  return (
    <>
      <Scene />
      <Navbar />

      <main className="stage" id="top">
        <section className="glass enter" ref={cardRef} aria-labelledby="title">
          <div className="enter" style={{ '--i': 2 } as CSSProperties}>
            <h1 id="title" tabIndex={-1} ref={titleRef}>
              {view === 'ask' && <>Forgot your <em>password?</em></>}
              {view === 'sent' && <>Check your <em>inbox</em></>}
              {view === 'choose' && <>Choose a new <em>password</em></>}
              {view === 'done' && <>Password <em>changed</em></>}
            </h1>
            <p className="sub">
              {view === 'ask' && 'Enter the email you log in with. We will send you a link to choose a new password.'}
              {view === 'sent' && 'If an account uses that email, a reset link is on its way. It works once and expires in 30 minutes. Check your spam folder too.'}
              {view === 'choose' && 'Pick a password you have not used here before. This signs you out everywhere else.'}
              {view === 'done' && 'Your new password is ready. Every other session has been signed out.'}
            </p>
          </div>

          {lockedFor > 0 ? (
            <div className="banner" role="alert">
              <span>Too many attempts. Try again in <b>{Math.floor(lockedFor / 60)}:{String(lockedFor % 60).padStart(2, '0')}</b>.</span>
            </div>
          ) : banner && (
            <div className={'banner' + (banner.kind === 'info' ? ' info' : '')} role="alert"><span>{banner.message}</span></div>
          )}

          {view === 'ask' && (
            <form noValidate className="enter" style={{ '--i': 3 } as CSSProperties} onSubmit={askForLink}>
              <div className="field">
                <label htmlFor="email">Email</label>
                <div className="control">
                  <input id="email" ref={firstRef} type="email" inputMode="email" autoComplete="email" autoCapitalize="off"
                         spellCheck={false} maxLength={254} placeholder="you@company.com" value={email}
                         readOnly={submit !== 'idle'} aria-invalid={error?.field === 'email'} aria-describedby="emailErr"
                         onChange={e => { setEmail(e.target.value); setError(null); setBanner(null); }} />
                </div>
                {errorFor('email')}
              </div>
              <button className="submit" type="submit" data-state={submit} aria-busy={submit === 'busy'} disabled={lockedFor > 0}>
                <span className="lbl">Send reset link</span>
                <span className="spin" aria-hidden="true"></span>
                <span className="ok" aria-hidden="true"></span>
              </button>
            </form>
          )}

          {view === 'sent' && (
            <p className="switch">Did not get it? <a href="/forgot-password" onClick={e => { e.preventDefault(); setView('ask'); }}>Send it again</a></p>
          )}

          {/* An account made with GitHub has no Verixa password and no email here, so no link can ever reach it.
              The note is always shown, so it never reveals whether an email has an account. */}
          {(view === 'ask' || view === 'sent') && (
            <p className="switch alt">Signed up with GitHub? You have no Verixa password to reset. <a href="/auth/github">Continue with GitHub</a></p>
          )}

          {view === 'choose' && !badLink && (
            <form noValidate className="enter" style={{ '--i': 3 } as CSSProperties} onSubmit={choosePassword}>
              <div className="field">
                <label htmlFor="password">New password<small>8+ characters</small></label>
                <div className="control has-eye">
                  <input id="password" ref={firstRef} type={showPassword ? 'text' : 'password'} autoComplete="new-password"
                         maxLength={128} placeholder="••••••••" value={password} readOnly={submit !== 'idle'}
                         aria-invalid={error?.field === 'password'} aria-describedby="passwordErr rulesList"
                         onChange={e => { setPassword(e.target.value); setError(null); setBanner(null); }} />
                  <button type="button" className="eye" aria-label={showPassword ? 'Hide password' : 'Show password'}
                          aria-pressed={showPassword} aria-controls="password again" onClick={() => setShowPassword(s => !s)}>
                    <svg className="on" viewBox="0 0 24 24"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></svg>
                    <svg className="off" viewBox="0 0 24 24"><path d="M10.7 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-2.2 3.2M6.6 6.6C3.9 8.4 2 12 2 12s3.5 7 10 7a9.7 9.7 0 0 0 5.4-1.6" /><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2M2 2l20 20" /></svg>
                  </button>
                </div>
                {errorFor('password')}
                <div className="meter" data-score={score} aria-hidden="true"><i></i><i></i><i></i><i></i></div>
                <ul className="rules" id="rulesList">
                  <li className={password.length >= 8 ? 'ok' : ''}>8+ characters</li>
                  <li className={hasLetterAndNumber(password) ? 'ok' : ''}>A letter and a number</li>
                  <li className="strength" aria-live="polite">{STRENGTH_LABEL[score]}</li>
                </ul>
              </div>
              <div className="field">
                <label htmlFor="again">Type it again</label>
                <div className="control">
                  <input id="again" type={showPassword ? 'text' : 'password'} autoComplete="new-password" maxLength={128}
                         placeholder="••••••••" value={again} readOnly={submit !== 'idle'}
                         aria-invalid={error?.field === 'again'} aria-describedby="againErr"
                         onChange={e => { setAgain(e.target.value); if (error?.field === 'again') setError(null); }} />
                </div>
                {errorFor('again')}
              </div>
              <button className="submit" type="submit" data-state={submit} aria-busy={submit === 'busy'} disabled={lockedFor > 0}>
                <span className="lbl">Save new password</span>
                <span className="spin" aria-hidden="true"></span>
                <span className="ok" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg></span>
              </button>
            </form>
          )}

          {view === 'done' && <a className="submit as-link" href="/login">Log in</a>}

          <p className="switch">
            {badLink
              ? <><a href="/forgot-password">Ask for a new link</a> or go back to <a href="/login">Log in</a></>
              : view !== 'done' && <>Remembered it? <a href="/login">Back to log in</a></>}
          </p>
        </section>
      </main>

      <Footer />
    </>
  );
}
