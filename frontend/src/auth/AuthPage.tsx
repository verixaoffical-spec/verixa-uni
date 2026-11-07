import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type FormEvent, type MouseEvent, type PointerEvent } from 'react';
import Footer from '../landing/Footer';
import Navbar from '../landing/Navbar';
import Scene from './Scene';
import TwoFactorStep from './TwoFactorStep';
import { urlError } from '../shared/urlError';
import { send, type Reply } from './api';
import { destination, hasLetterAndNumber, normEmail, normName, problem, strength,
         type Field, type Mode, type Values } from './rules';

interface FieldError {
  message: string;
  serverValue?: string;                          // a server answer stays until the value changes
  action?: { label: string; run: () => void };   // a button shown after the message
}
type Errors = Partial<Record<Field, FieldError>>;
type Step = 'password' | 'code';  // code: the password was right and two-step verification is on
interface Banner { message: string; kind: 'error' | 'info' }

const FIELDS: Record<Mode, Field[]> = { signup: ['name', 'email', 'password'], login: ['email', 'password'] };
const STRENGTH_LABEL = ['', 'Weak', 'Fair', 'Good', 'Strong'];
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const finePointer = matchMedia('(pointer: fine)').matches;  // on phones, focusing a field opens the keyboard over the form

const modeFromPath = (): Mode => (location.pathname.startsWith('/signup') ? 'signup' : 'login');
const URL_FLAGS = ['error', 'signed_out', 'expired', 'reauth', 'verify'];  // verify: GitHub sign in needs the code step
const order = (i: number) => ({ '--i': i }) as CSSProperties;  // staggers the entrance animation

// A message carried in the URL, for example after signing out.
function bannerFromUrl(): Banner | null {
  const params = new URLSearchParams(location.search);
  const error = params.get('error');
  if (error) return { message: urlError(error), kind: 'error' };
  if (params.has('signed_out')) return { message: 'You have been signed out. See you soon.', kind: 'info' };
  if (params.has('expired')) return { message: 'Your session ended. Log in again to pick up where you left off.', kind: 'info' };
  if (params.has('reauth')) return { message: 'For your security, log in again to change your security settings.', kind: 'info' };
  return null;
}

// Turns a failed sign in or sign up into a message for the banner.
function bannerFor(res: Reply): string {
  if (res.status === 0) return res.timeout
    ? 'Verixa is taking too long to answer. Check your connection and try again.'
    : 'Cannot reach Verixa. Check your connection and try again.';
  if (res.status === 403) return typeof res.detail === 'string' ? res.detail : 'This request was blocked. Reload the page and try again.';
  if (res.status === 413) return 'That request was too large.';
  if (res.status === 422) return 'Some details could not be read. Check the form and try again.';
  return 'Something went wrong on our side. Please try again in a moment.';
}

export default function AuthPage() {
  const [mode, setMode] = useState<Mode>(modeFromPath);
  const [step, setStep] = useState<Step>(() => (new URLSearchParams(location.search).has('verify') ? 'code' : 'password'));
  const [values, setValues] = useState<Values>({ name: '', email: '', password: '' });
  const [errors, setErrors] = useState<Errors>({});
  const [banner, setBanner] = useState<Banner | null>(bannerFromUrl);
  const [lockedFor, setLockedFor] = useState(0);  // seconds left after too many attempts
  const [submit, setSubmit] = useState<'idle' | 'busy' | 'done'>('idle');
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [githubBusy, setGithubBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [switched, setSwitched] = useState(false);  // plays a short animation after switching mode

  const touched = useRef(new Set<Field>());  // fields the person has typed in, so empty ones are not flagged too early
  const cardRef = useRef<HTMLElement>(null);
  const heightBefore = useRef(0);
  const nameRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const inputs = { name: nameRef, email: emailRef, password: passwordRef };
  const busy = submit !== 'idle';

  function focusFirst() {
    if (step === 'code') {
      // On phones the heading takes focus instead, so screen readers announce the new step without opening the keyboard
      return document.getElementById(finePointer ? 'code' : 'title')?.focus({ preventScroll: true });
    }
    if (!finePointer) return;
    const order = FIELDS[mode].map(f => inputs[f].current);
    (order.find(el => el && !el.value) ?? order[order.length - 1])?.focus({ preventScroll: true });
  }

  // ---- page setup ----
  useEffect(() => {
    // Remove the one-time message from the address bar, so a refresh does not show it again
    const params = new URLSearchParams(location.search);
    if (URL_FLAGS.some(k => params.has(k))) {
      URL_FLAGS.forEach(k => params.delete(k));
      const query = params.toString();
      history.replaceState(null, '', location.pathname + (query ? '?' + query : '') + location.hash);
    }

    // Coming back with the Back button restores a frozen copy of the page. Ask the server again instead.
    const onPageShow = (e: PageTransitionEvent) => { if (e.persisted) location.reload(); };
    addEventListener('pageshow', onPageShow);

    // A brief wait for the web fonts avoids the headings jumping when they swap in.
    const fontsReady = Promise.race([document.fonts.ready, new Promise(r => setTimeout(r, 400))]);
    fontsReady.then(() => {
      setReady(true);
      document.body.classList.add('ready');
    });
    return () => removeEventListener('pageshow', onPageShow);
  }, []);

  useLayoutEffect(() => {
    if (cardRef.current) cardRef.current.inert = !ready;
    if (ready) setTimeout(focusFirst, reduced ? 0 : 350);
  }, [ready]);

  useEffect(() => {
    document.title = (step === 'code' ? 'Two-step verification' : mode === 'login' ? 'Log in' : 'Sign up') + ' · Verixa';
    const onPopState = () => switchMode(modeFromPath(), false);
    addEventListener('popstate', onPopState);
    return () => removeEventListener('popstate', onPopState);
  }, [mode, step]);

  // After switching mode or step, smoothly resize the card from its old height and focus the first empty field.
  useLayoutEffect(() => {
    const card = cardRef.current, before = heightBefore.current;
    heightBefore.current = 0;
    if (!card || !before) return;
    if (!reduced && card.offsetHeight !== before) {
      card.animate([{ height: before + 'px' }, { height: card.offsetHeight + 'px' }], { duration: 380, easing: 'cubic-bezier(.22,1,.36,1)' });
    }
    focusFirst();
  }, [mode, step]);

  // Count down the lockout one second at a time
  useEffect(() => {
    if (lockedFor <= 0) return;
    const timer = setTimeout(() => setLockedFor(s => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [lockedFor]);

  // ---- switching between log in and sign up ----
  function switchMode(next: Mode, push: boolean) {
    if (next === mode) return;
    heightBefore.current = cardRef.current?.offsetHeight ?? 0;
    setMode(next);
    setErrors({});
    touched.current.clear();
    setBanner(null);
    setSwitched(true);
    if (push) history.pushState(null, '', `/${next}${location.search}${location.hash}`);
  }

  // ---- the two-step verification code ----
  function changeStep(next: Step, message: Banner | null = null) {
    heightBefore.current = cardRef.current?.offsetHeight ?? 0;
    setStep(next);
    setBanner(message);
    setLockedFor(0);
    setErrors({});
    setValues(v => ({ ...v, password: '' }));  // the password is never kept around once it has been checked
    setSwitched(true);
  }

  // The navbar's Log in and Sign up switch the form in place. During the code step they load the page fresh.
  function onNavLink(e: MouseEvent<HTMLAnchorElement>, next: Mode) {
    if (step === 'code') return;
    onModeLink(e, next);
  }

  function onModeLink(e: MouseEvent<HTMLAnchorElement>, next: Mode) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;  // let "open in new tab" work
    e.preventDefault();
    if (!busy) switchMode(next, true);
  }

  // ---- fields ----
  function setError(field: Field, error: FieldError | undefined) {
    setErrors(all => ({ ...all, [field]: error }));
  }

  function onChange(field: Field, value: string) {
    const next = { ...values, [field]: value };
    setValues(next);
    const error = errors[field];
    if (error && error.serverValue !== value && !problem(field, next, mode)) setError(field, undefined);
    setBanner(null);
  }

  // Check a field when the person leaves it, but only once they have typed something in it.
  function onBlur(field: Field) {
    const value = field === 'email' ? values.email.trim() : values[field];
    if (value !== values[field]) setValues(v => ({ ...v, [field]: value }));
    if (value) touched.current.add(field);
    if (!touched.current.has(field) || errors[field]?.serverValue === value) return;
    const message = problem(field, { ...values, [field]: value }, mode);
    setError(field, message ? { message } : undefined);
  }

  function togglePassword() {
    const input = passwordRef.current!, start = input.selectionStart, end = input.selectionEnd;
    setShowPassword(show => !show);
    requestAnimationFrame(() => {  // keep the cursor where it was
      input.focus();
      try { input.setSelectionRange(start, end); } catch { /* some input types do not allow it */ }
    });
  }

  // ---- sending the form ----
  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (busy || lockedFor > 0) return;
    setBanner(null);

    const found: Errors = {};
    for (const field of FIELDS[mode]) {
      touched.current.add(field);
      const message = problem(field, values, mode);
      if (message) found[field] = { message };
    }
    setErrors(found);
    const firstBad = FIELDS[mode].find(f => found[f]);
    if (firstBad) return inputs[firstBad].current?.focus();

    const payload: Record<string, string> = { email: normEmail(values.email), password: values.password };
    if (mode === 'signup') payload.name = normName(values.name);
    setSubmit('busy');
    const res = await send(mode === 'signup' ? '/auth/signup' : '/auth/login', payload);

    if (res.status === 200 && res.data?.two_factor) {
      setSubmit('idle');
      changeStep('code');
      return;
    }
    if (res.status === 200 || res.status === 201) {
      setSubmit('done');
      setTimeout(() => location.replace(destination()), reduced ? 0 : 500);  // let the check mark register first
      return;
    }
    setSubmit('idle');

    if (res.status === 429) {
      setLockedFor(Math.max(1, Math.ceil(res.retryAfter || res.detail?.retry_after || 60)));
      return;
    }

    // The server points at one field, for example a taken email or a wrong password
    const field = res.detail?.field as Field | undefined;
    if (field && field in inputs) {
      const taken = res.status === 409 && field === 'email' && mode === 'signup';
      setError(field, {
        message: taken ? 'An account with this email already exists.' : res.detail.message,
        serverValue: values[field],
        action: taken ? { label: 'Log in instead', run: logInInstead } : undefined,
      });
      inputs[field].current?.focus();
      if (res.status === 401) passwordRef.current?.select();
      return;
    }

    setBanner({ message: bannerFor(res), kind: 'error' });
  }

  function logInInstead() {
    switchMode('login', true);
    setValues(v => ({ ...v, password: '' }));
  }

  // The glass card follows the pointer with a faint highlight
  const glowFrame = useRef(0);
  function onPointerMove(e: PointerEvent<HTMLElement>) {
    if (reduced || !finePointer) return;
    const card = e.currentTarget, x = e.clientX, y = e.clientY;
    cancelAnimationFrame(glowFrame.current);
    glowFrame.current = requestAnimationFrame(() => {
      const r = card.getBoundingClientRect();
      card.style.setProperty('--mx', ((x - r.left) / r.width * 100).toFixed(1) + '%');
      card.style.setProperty('--my', ((y - r.top) / r.height * 100).toFixed(1) + '%');
    });
  }

  // ---- rendering ----
  const signup = mode === 'signup';
  const score = signup ? strength(values.password) : 0;
  const swap = switched ? 'swap' : '';

  function errorFor(field: Field) {
    const error = errors[field];
    if (!error) return null;
    return (
      <p className="err" id={field + 'Err'}>
        {error.message}
        {error.action && <> <button type="button" onClick={error.action.run}>{error.action.label}</button></>}
      </p>
    );
  }

  return (
    <>
      <Scene />

      <Navbar current={step === 'code' ? undefined : mode} onAuthLink={onNavLink} />

      <main className="stage" id="top">
        <section className="glass enter" ref={cardRef} aria-labelledby="title" onPointerMove={onPointerMove}>
          {step === 'password' && <nav className="seg enter" style={order(2)} role="tablist" aria-label="Choose how to continue" data-mode={mode}>
            <a href="/login" role="tab" aria-selected={!signup} onClick={e => onModeLink(e, 'login')}>Log in</a>
            <a href="/signup" role="tab" aria-selected={signup} onClick={e => onModeLink(e, 'signup')}>Sign up</a>
            <span className="seg-lamp" aria-hidden="true"></span>
          </nav>}

          <div className="enter" style={order(3)}>
            {step === 'code' ? (
              <div key="code" className={swap}>
                <h1 id="title" tabIndex={-1}>Two-step <em>verification</em></h1>
                <p className="sub">Your password is correct. One more step keeps your account safe.</p>
              </div>
            ) : (
              <div key={mode} className={swap}>
                <h1 id="title" tabIndex={-1}>{signup ? <>Create your <em>account</em></> : <>Welcome <em>back</em></>}</h1>
                <p className="sub">{signup ? 'Start shipping pull requests that test themselves.' : 'Log in to your QA workspace.'}</p>
              </div>
            )}
          </div>

          {lockedFor > 0 ? (
            <div className="banner" role="alert">
              <WarnIcon />
              <span>Too many attempts. For your security, try again in <b>{Math.floor(lockedFor / 60)}:{String(lockedFor % 60).padStart(2, '0')}</b>.</span>
            </div>
          ) : banner && (
            <div className={'banner' + (banner.kind === 'info' ? ' info' : '')} role={banner.kind === 'info' ? 'status' : 'alert'}>
              {banner.kind === 'info' ? <InfoIcon /> : <WarnIcon />}
              <span>{banner.message}</span>
            </div>
          )}

          {step === 'code' ? (
            <div className={swap}>
              <TwoFactorStep locked={lockedFor > 0} onLocked={setLockedFor}
                             onProblem={res => setBanner({ message: bannerFor(res), kind: 'error' })}
                             onExpired={() => changeStep('password', { message: 'Your sign in timed out. Enter your password again.', kind: 'info' })}
                             onBack={() => changeStep('password')} />
            </div>
          ) : <>
          <a className="oauth enter" style={order(4)} href="/auth/github" aria-busy={githubBusy}
             onClick={e => (busy ? e.preventDefault() : setGithubBusy(true))}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 .5C5.65.5.5 5.65.5 12a11.5 11.5 0 0 0 7.86 10.92c.58.1.79-.25.79-.56v-2c-3.2.7-3.87-1.37-3.87-1.37-.52-1.33-1.28-1.69-1.28-1.69-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.19 1.76 1.19 1.03 1.76 2.69 1.25 3.35.96.1-.75.4-1.25.73-1.54-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.84 1.19 3.1 0 4.42-2.69 5.39-5.25 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5Z" /></svg>
            {signup ? 'Sign up with GitHub' : 'Continue with GitHub'}
          </a>
          <div className="or enter" style={order(5)}>or with email</div>

          <form noValidate className="enter" style={order(6)} onSubmit={onSubmit}>
            {signup && (
              <div className={'field ' + swap}>
                <label htmlFor="name">Full name</label>
                <div className="control">
                  <input id="name" ref={nameRef} type="text" autoComplete="name" maxLength={80} placeholder="Ada Lovelace"
                         value={values.name} readOnly={busy} aria-invalid={!!errors.name} aria-describedby="nameErr"
                         onChange={e => onChange('name', e.target.value)} onBlur={() => onBlur('name')} />
                </div>
                {errorFor('name')}
              </div>
            )}

            <div className="field">
              <label htmlFor="email">{signup ? 'Work email' : 'Email'}</label>
              <div className="control">
                <input id="email" ref={emailRef} type="email" inputMode="email" autoComplete="email" autoCapitalize="off"
                       spellCheck={false} maxLength={254} placeholder="you@company.com"
                       value={values.email} readOnly={busy} aria-invalid={!!errors.email} aria-describedby="emailErr"
                       onChange={e => onChange('email', e.target.value)} onBlur={() => onBlur('email')} />
              </div>
              {errorFor('email')}
            </div>

            <div className="field">
              <label htmlFor="password">Password{signup && <small>8+ characters</small>}</label>
              <div className="control has-eye">
                <input id="password" ref={passwordRef} type={showPassword ? 'text' : 'password'}
                       autoComplete={signup ? 'new-password' : 'current-password'} maxLength={128} placeholder="••••••••"
                       value={values.password} readOnly={busy} aria-invalid={!!errors.password}
                       aria-describedby="passwordErr capsHint rulesList"
                       onChange={e => onChange('password', e.target.value)}
                       onBlur={() => { setCapsLock(false); onBlur('password'); }}
                       onKeyDown={e => setCapsLock(e.getModifierState('CapsLock'))}
                       onKeyUp={e => setCapsLock(e.getModifierState('CapsLock'))} />
                <button type="button" className="eye" aria-label={showPassword ? 'Hide password' : 'Show password'}
                        aria-pressed={showPassword} aria-controls="password" onClick={togglePassword}>
                  <svg className="on" viewBox="0 0 24 24"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></svg>
                  <svg className="off" viewBox="0 0 24 24"><path d="M10.7 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-2.2 3.2M6.6 6.6C3.9 8.4 2 12 2 12s3.5 7 10 7a9.7 9.7 0 0 0 5.4-1.6" /><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2M2 2l20 20" /></svg>
                </button>
              </div>
              {capsLock && (
                <p className="caps" id="capsHint"><svg viewBox="0 0 24 24"><path d="M12 4 4 12h4v6h8v-6h4z" /></svg>Caps Lock is on</p>
              )}
              {errorFor('password')}
              {!signup && <p className="forgot"><a href="/forgot-password">Forgot password?</a></p>}
              {signup && (
                <div>
                  <div className="meter" data-score={score} aria-hidden="true"><i></i><i></i><i></i><i></i></div>
                  <ul className="rules" id="rulesList">
                    <li className={values.password.length >= 8 ? 'ok' : ''}>8+ characters</li>
                    <li className={hasLetterAndNumber(values.password) ? 'ok' : ''}>A letter and a number</li>
                    <li className="strength" aria-live="polite">{STRENGTH_LABEL[score]}</li>
                  </ul>
                </div>
              )}
            </div>

            <button className="submit" type="submit" data-state={submit} aria-busy={submit === 'busy'} disabled={lockedFor > 0}>
              <span className="lbl">{signup ? 'Create account' : 'Log in'}</span>
              <span className="spin" aria-hidden="true"></span>
              <span className="ok" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg></span>
            </button>
          </form>

          <p className="switch enter" style={order(7)}>
            <span key={mode} className={swap}>
              {signup
                ? <>Already have an account? <a href="/login" onClick={e => onModeLink(e, 'login')}>Log in</a></>
                : <>New to Verixa? <a href="/signup" onClick={e => onModeLink(e, 'signup')}>Create an account</a></>}
            </span>
          </p>
          </>}
        </section>

        <p className="fine enter" style={order(8)}>
          <svg viewBox="0 0 24 24"><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
          Passwords are salted and hashed, never stored as plain text
        </p>
      </main>

      <Footer />
    </>
  );
}

function WarnIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4M12 17h.01" />
    </svg>
  );
}

function InfoIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" />
    </svg>
  );
}
