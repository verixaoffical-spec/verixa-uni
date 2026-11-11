import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { NAME_MAX, normName, problem } from '../auth/rules';
import { ApiError, api, type Account, type TwoFactorStatus } from './api';
import { Chip } from './connection';
import { icons } from './icons';
import { useToast } from './Toast';

interface Props {
  hidden: boolean;
  account: Account | null;
  onAccount: (account: Account) => void;
  onDeleted: () => void;
  onSignInAgain: () => void;   // accounts without a password confirm who they are by signing in again
}

interface FormError { field: string; message: string }

const CONFIRM_WORD = 'DELETE';

function Section({ icon, title, hint, children }: { icon: ReactNode; title: string; hint: string; children: ReactNode }) {
  return (
    <div className="sec is-active">
      <div className="lab"><span className="lic">{icon}</span><div><b>{title}</b><small>{hint}</small></div></div>
      <div>{children}</div>
    </div>
  );
}

// The account's own page: change the name, or delete the account and everything in it
export default function ProfileView({ hidden, account, onAccount, onDeleted, onSignInAgain }: Props) {
  const toast = useToast();
  const [status, setStatus] = useState<TwoFactorStatus | null>(null);  // has a password? two-step on?
  const [name, setName] = useState('');
  const [deleting, setDeleting] = useState(false);                     // the delete form is open
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [typed, setTyped] = useState('');
  const [error, setError] = useState<FormError | null>(null);
  const [busy, setBusy] = useState(false);

  // Every visit starts fresh, with the saved name and the delete form closed
  useEffect(() => {
    if (hidden) return;
    setName(account?.name ?? '');
    closeDelete();
    api.twoFactor().then(setStatus).catch(err => {
      if (!(err instanceof ApiError && err.status === 401)) toast(err.message);  // 401: App.tsx sends the person to log in
    });
  }, [hidden]);

  useEffect(() => { if (account && !busy) setName(account.name); }, [account?.name]);

  function closeDelete() {
    setDeleting(false);
    setPassword('');
    setCode('');
    setTyped('');
    setError(null);
  }

  async function run<T>(call: () => Promise<T>): Promise<T | null | undefined> {
    setBusy(true);
    setError(null);
    try {
      return await call();
    } catch (err) {
      if (!(err instanceof ApiError)) setError({ field: 'form', message: 'Cannot reach Verixa. Check your connection and try again' });
      else if (err.status === 429) setError({ field: 'form', message: err.detail?.message ?? 'Too many attempts. Try again later' });
      else if (err.status !== 401) setError({ field: err.detail?.field ?? 'form', message: err.detail?.message ?? err.message });
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  // ---- the name ----
  const cleanName = normName(name);
  const nameProblem = problem('name', { name, email: '', password: '' }, 'signup');
  const nameChanged = !!account && cleanName !== account.name;

  async function onSaveName(e: FormEvent) {
    e.preventDefault();
    if (busy || !nameChanged) return;
    if (nameProblem) return setError({ field: 'name', message: nameProblem });
    const res = await run(() => api.renameAccount(cleanName));
    if (!res) return;
    onAccount(res.account);
    setName(res.account.name);
    toast('Your name is saved');
  }

  // ---- deleting the account ----
  const needsPassword = !!status?.has_password;
  const needsCode = !!status?.enabled;

  async function onDelete(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    if (needsPassword && !password) return setError({ field: 'password', message: 'Enter your password' });
    if (needsCode && !code.trim()) return setError({ field: 'code', message: 'Enter a code from your app, or a recovery code' });
    if (typed.trim() !== CONFIRM_WORD) return setError({ field: 'typed', message: `Type ${CONFIRM_WORD} to confirm` });
    const res = await run(() => api.deleteAccount(password, code.trim()));
    if (res === null) onDeleted();  // 204: the account is gone and the session has ended
  }

  // ---- rendering ----
  const errorFor = (field: string) => error?.field === field && <p className="form-err" id={field + 'Err'} role="alert">{error.message}</p>;
  const formError = error && !['name', 'password', 'code', 'typed'].includes(error.field) && (
    <div className="form-err" role="alert">
      {error.message}
      {error.field === 'reauth' && <> <button type="button" className="btn sm ghost" onClick={onSignInAgain}>Log in again</button></>}
    </div>
  );

  return (
    <section className="workspace security" hidden={hidden}>
      <article className="card">
        <div className="head">
          <h1>Your <em>profile</em></h1>
          <p className="lead">Change the name Verixa shows, or delete your account and everything in it.</p>
          {account && (
            <div className="chips">
              {account.email && <Chip on>{account.email}</Chip>}
              {account.github_login && <Chip on>@{account.github_login} on GitHub</Chip>}
            </div>
          )}
        </div>

        <Section icon={icons.user} title="Name" hint={`2 to ${NAME_MAX} characters. Letters, spaces, ' - and . only`}>
          <form className="sec-form" noValidate onSubmit={onSaveName}>
            <label className="field">Full name
              <input type="text" autoComplete="name" maxLength={NAME_MAX} value={name} disabled={deleting}
                     aria-invalid={error?.field === 'name'} aria-describedby="nameErr"
                     onChange={e => { setName(e.target.value); if (error?.field === 'name') setError(null); }} />
              {errorFor('name')}
            </label>
            <label className="field">Email
              <input type="text" value={account?.email ?? 'None: you signed up with GitHub'} readOnly disabled />
            </label>
            {!deleting && formError}
            <div className="sec-actions">
              <button className="btn" disabled={busy || !nameChanged || deleting}>Save name</button>
              {nameChanged && !deleting && (
                <button type="button" className="btn ghost" onClick={() => { setName(account!.name); setError(null); }}>Cancel</button>
              )}
            </div>
          </form>
        </Section>

        <Section icon={icons.trash} title="Delete account" hint="This cannot be undone">
          {!deleting ? (
            <>
              <p className="hintline">Deletes your account, your connected repository and Jira project, your Test Library,
                your risk analyses and your recovery codes. Your GitHub and Jira themselves are not touched.</p>
              <div className="sec-actions">
                <button className="btn ghost danger" disabled={!status} onClick={() => { setDeleting(true); setError(null); }}>Delete my account</button>
              </div>
            </>
          ) : (
            <form className="sec-form" noValidate onSubmit={onDelete}>
              <p className="warnbox">Everything in your Verixa account is deleted for good. You will be signed out.</p>
              {needsPassword ? (
                <label className="field">Password
                  <input type="password" autoComplete="current-password" maxLength={128} value={password} autoFocus
                         aria-invalid={error?.field === 'password'} aria-describedby="passwordErr"
                         onChange={e => setPassword(e.target.value)} />
                  {errorFor('password')}
                </label>
              ) : <p className="hintline">You signed in with GitHub, so there is no password to enter.</p>}
              {needsCode && (
                <label className="field">Code from your app, or a recovery code
                  <input className="mono" type="text" value={code} autoComplete="one-time-code" spellCheck={false} maxLength={20}
                         placeholder="123456 or abcde-fghjk" autoFocus={!needsPassword}
                         aria-invalid={error?.field === 'code'} aria-describedby="codeErr" onChange={e => setCode(e.target.value)} />
                  {errorFor('code')}
                </label>
              )}
              <label className="field">Type {CONFIRM_WORD} to confirm
                <input className="mono" type="text" value={typed} autoComplete="off" spellCheck={false} maxLength={20}
                       autoFocus={!needsPassword && !needsCode}
                       aria-invalid={error?.field === 'typed'} aria-describedby="typedErr" onChange={e => setTyped(e.target.value)} />
                {errorFor('typed')}
              </label>
              {formError}
              <div className="sec-actions">
                <button className="btn danger-solid" disabled={busy || typed.trim() !== CONFIRM_WORD}>Delete my account forever</button>
                <button type="button" className="btn ghost" onClick={closeDelete}>Cancel</button>
              </div>
            </form>
          )}
        </Section>
      </article>
    </section>
  );
}
