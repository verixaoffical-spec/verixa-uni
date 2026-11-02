import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { ApiError, api, type Account, type TwoFactorStatus } from './api';
import { Chip } from './connection';
import { icons } from './icons';
import { useToast } from './Toast';

interface Props {
  hidden: boolean;
  onAccount: (account: Account) => void;
  onSignInAgain: () => void;   // accounts without a password confirm who they are by signing in again
}

type Action = 'setup' | 'disable' | 'regenerate';
type Screen =
  | { name: 'status' }
  | { name: 'confirm'; action: Action }               // asks for the password, and a code to turn off or regenerate
  | { name: 'scan'; qr: string; secret: string }      // the QR code and the code that confirms it
  | { name: 'codes'; codes: string[] };               // new recovery codes, shown once

interface FormError { field: string; message: string }

const CONFIRM: Record<Action, { title: string; hint: string; button: string }> = {
  setup: { title: 'Confirm it is you', hint: 'Enter your password to set up two-step verification.', button: 'Continue' },
  disable: { title: 'Turn off two-step verification', hint: 'Your account will be protected by your password only.', button: 'Turn off' },
  regenerate: { title: 'Make new recovery codes', hint: 'Your current recovery codes stop working straight away.', button: 'Make new codes' },
};

function Section({ icon, title, hint, children }: { icon: ReactNode; title: string; hint: string; children: ReactNode }) {
  return (
    <div className="sec is-active">
      <div className="lab"><span className="lic">{icon}</span><div><b>{title}</b><small>{hint}</small></div></div>
      <div>{children}</div>
    </div>
  );
}

// Account settings: turn two-step verification on or off, and manage recovery codes
export default function SecurityView({ hidden, onAccount, onSignInAgain }: Props) {
  const toast = useToast();
  const [status, setStatus] = useState<TwoFactorStatus | null>(null);
  const [screen, setScreen] = useState<Screen>({ name: 'status' });
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState<FormError | null>(null);
  const [busy, setBusy] = useState(false);

  // Load the status every time the page opens, and start from the overview
  useEffect(() => {
    if (hidden) return;
    go({ name: 'status' });
    api.twoFactor().then(setStatus).catch(err => {
      if (!(err instanceof ApiError && err.status === 401)) toast(err.message);  // 401: App.tsx sends the person to log in
    });
  }, [hidden]);

  function go(next: Screen) {
    setScreen(next);
    setPassword('');
    setCode('');
    setError(null);
  }

  // Runs a call. A refusal becomes a message next to the field it is about, or under the form.
  async function run<T>(call: () => Promise<T>): Promise<T | null> {
    setBusy(true);
    setError(null);
    try {
      return await call();
    } catch (err) {
      if (!(err instanceof ApiError)) setError({ field: 'form', message: 'Cannot reach Verixa. Check your connection and try again' });
      else if (err.status !== 401) setError({ field: err.detail?.field ?? 'form', message: err.detail?.message ?? err.message });
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function startSetup() {
    if (status?.has_password) return go({ name: 'confirm', action: 'setup' });
    const res = await run(() => api.setupTwoFactor(''));
    if (res) go({ name: 'scan', ...res });
  }

  function showCodes(codes: string[]) {
    setStatus(s => s && { ...s, enabled: true, recovery_codes_left: codes.length });
    go({ name: 'codes', codes });
  }

  async function onConfirm(e: FormEvent) {
    e.preventDefault();
    if (screen.name !== 'confirm' || busy) return;
    const { action } = screen, typed = code.trim();
    if (status?.has_password && !password) return setError({ field: 'password', message: 'Enter your password' });
    if (action !== 'setup' && !typed) return setError({ field: 'code', message: 'Enter a code from your app, or a recovery code' });

    if (action === 'setup') {
      const res = await run(() => api.setupTwoFactor(password));
      if (res) go({ name: 'scan', ...res });
    } else if (action === 'disable') {
      const res = await run(() => api.disableTwoFactor(password, typed));
      if (!res) return;
      onAccount(res.account);
      setStatus(s => s && { ...s, enabled: false, recovery_codes_left: 0 });
      go({ name: 'status' });
      toast('Two-step verification is off');
    } else {
      const res = await run(() => api.newRecoveryCodes(password, typed));
      if (res) showCodes(res.recovery_codes);
    }
  }

  async function onEnable(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    if (!/^\d{6}$/.test(code)) return setError({ field: 'code', message: 'Enter the 6-digit code from your app' });
    const res = await run(() => api.enableTwoFactor(code));
    if (!res) return;
    onAccount(res.account);
    showCodes(res.recovery_codes);
    toast('Two-step verification is on');
  }

  function copy(text: string, what: string) {
    navigator.clipboard.writeText(text).then(() => toast(`${what} copied`), () => toast('Could not copy. Select the text and copy it instead'));
  }

  function download(codes: string[]) {
    const text = `Verixa recovery codes\nEach code signs you in once if you cannot use your authenticator app.\n\n${codes.join('\n')}\n`;
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
    a.download = 'verixa-recovery-codes.txt';
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // ---- rendering ----
  const errorFor = (field: string) => error?.field === field && <p className="form-err" id={field + 'Err'} role="alert">{error.message}</p>;
  const formError = error && !['password', 'code'].includes(error.field) && (
    <div className="form-err" role="alert">
      {error.message}
      {error.field === 'reauth' && <> <button type="button" className="btn sm ghost" onClick={onSignInAgain}>Log in again</button></>}
      {error.field === 'setup' && <> <button type="button" className="btn sm ghost" onClick={startSetup}>Start again</button></>}
    </div>
  );
  const passwordField = status?.has_password && (
    <label className="field">Password
      <input type="password" autoComplete="current-password" maxLength={128} value={password} autoFocus
             aria-invalid={error?.field === 'password'} aria-describedby="passwordErr" onChange={e => setPassword(e.target.value)} />
      {errorFor('password')}
    </label>
  );
  const codeField = (label: string, recoveryAllowed: boolean, autoFocus: boolean) => (
    <label className="field">{label}
      <input className="mono" type="text" value={code} autoFocus={autoFocus} autoComplete="one-time-code" spellCheck={false}
             inputMode={recoveryAllowed ? 'text' : 'numeric'} maxLength={recoveryAllowed ? 20 : undefined}
             placeholder={recoveryAllowed ? '123456 or abcde-fghjk' : '123456'}
             aria-invalid={error?.field === 'code'} aria-describedby="codeErr"
             onChange={e => setCode(recoveryAllowed ? e.target.value : e.target.value.replace(/\D/g, '').slice(0, 6))} />
      {errorFor('code')}
    </label>
  );

  let body: ReactNode = null;
  if (!status) {
    body = <div className="sec"><p className="hintline">Loading your security settings</p></div>;
  } else if (screen.name === 'confirm') {
    const { title, hint, button } = CONFIRM[screen.action];
    body = (
      <Section icon={icons.lock} title={title} hint={hint}>
        <form className="sec-form" noValidate onSubmit={onConfirm}>
          {passwordField}
          {!status.has_password && <p className="hintline">You signed in with GitHub, so there is no password to enter.</p>}
          {screen.action !== 'setup' && codeField('Code from your app, or a recovery code', true, !status.has_password)}
          {formError}
          <div className="sec-actions">
            <button className={'btn' + (screen.action === 'disable' ? ' danger-solid' : '')} disabled={busy}>{button}</button>
            <button type="button" className="btn ghost" onClick={() => go({ name: 'status' })}>Cancel</button>
          </div>
        </form>
      </Section>
    );
  } else if (screen.name === 'scan') {
    body = (
      <>
        <Section icon={icons.user} title="1. Scan the QR code" hint="Google Authenticator, Microsoft Authenticator, Authy or any authenticator app">
          <img className="qr" src={screen.qr} alt="QR code to add Verixa to your authenticator app" width={180} height={180} />
          <p className="hintline">Cannot scan it? Choose to enter a setup key in your app and type this key:</p>
          <div className="secret">
            <code aria-label="Setup key">{screen.secret}</code>
            <button type="button" className="btn sm ghost" onClick={() => copy(screen.secret.replace(/ /g, ''), 'Setup key')}>{icons.copy}Copy</button>
          </div>
        </Section>
        <Section icon={icons.lock} title="2. Enter the code" hint="Proves the app is set up correctly">
          <form className="sec-form" noValidate onSubmit={onEnable}>
            {codeField('6-digit code from the app', false, true)}
            {formError}
            <div className="sec-actions">
              <button className="btn" disabled={busy}>Turn on</button>
              <button type="button" className="btn ghost" onClick={() => go({ name: 'status' })}>Cancel</button>
            </div>
          </form>
        </Section>
      </>
    );
  } else if (screen.name === 'codes') {
    body = (
      <Section icon={icons.lock} title="Save your recovery codes" hint="Each one signs you in once if you lose your phone">
        <p className="warnbox">These codes are shown only once. Keep them somewhere safe, such as a password manager.</p>
        <ol className="codes" aria-label="Recovery codes">{screen.codes.map(c => <li key={c}>{c}</li>)}</ol>
        <div className="sec-actions">
          <button type="button" className="btn ghost" onClick={() => copy(screen.codes.join('\n'), 'Recovery codes')}>{icons.copy}Copy</button>
          <button type="button" className="btn ghost" onClick={() => download(screen.codes)}>{icons.download}Download</button>
          <button type="button" className="btn" autoFocus onClick={() => go({ name: 'status' })}>I have saved them</button>
        </div>
      </Section>
    );
  } else if (!status.enabled) {
    body = (
      <Section icon={icons.lock} title="Authenticator app" hint="Not set up">
        <p className="hintline">After your password, Verixa will ask for a 6-digit code from an app on your phone.</p>
        {formError}
        <div className="sec-actions"><button className="btn" disabled={busy} onClick={startSetup}>Turn on two-step verification</button></div>
      </Section>
    );
  } else {
    const left = status.recovery_codes_left;
    body = (
      <>
        <Section icon={icons.lock} title="Authenticator app" hint="On">
          <p className="note">Two-step verification is on. You are asked for a code each time you log in.</p>
          <div className="sec-actions"><button className="btn ghost danger" onClick={() => go({ name: 'confirm', action: 'disable' })}>Turn off</button></div>
        </Section>
        <Section icon={icons.file} title="Recovery codes" hint="For when you cannot use your phone">
          <p className="hintline">{left} of 10 codes left. Each one works once.</p>
          {left <= 3 && <p className="warnbox">{left ? 'You are running low on recovery codes.' : 'You have no recovery codes left.'} Make new ones so you are never locked out.</p>}
          <div className="sec-actions"><button className="btn ghost" onClick={() => go({ name: 'confirm', action: 'regenerate' })}>Make new recovery codes</button></div>
        </Section>
      </>
    );
  }

  return (
    <section className="workspace security" hidden={hidden}>
      <article className="card">
        <div className="head">
          <h1>Account <em>security</em></h1>
          <p className="lead">Two-step verification asks for a code from your phone after your password, so a stolen password is not enough to get in.</p>
          {status && (
            <div className="chips">
              <Chip on={status.enabled}>{status.enabled ? 'Two-step verification on' : 'Two-step verification off'}</Chip>
              {status.enabled && <Chip on={status.recovery_codes_left > 3}>{status.recovery_codes_left} recovery codes left</Chip>}
            </div>
          )}
        </div>
        {body}
      </article>
    </section>
  );
}
