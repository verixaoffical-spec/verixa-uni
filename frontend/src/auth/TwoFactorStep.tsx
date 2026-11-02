import { useEffect, useRef, useState, type FormEvent } from 'react';
import { send, type Reply } from './api';
import { DASHBOARD, destination } from './rules';

interface Props {
  locked: boolean;                       // the page is counting down after too many attempts
  onLocked: (seconds: number) => void;
  onProblem: (res: Reply) => void;       // anything that is not about the code itself goes in the page banner
  onExpired: () => void;                 // the five minutes after the password ran out
  onBack: () => void;
}

const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

// The second step of logging in: a code from the authenticator app, or a recovery code.
export default function TwoFactorStep({ locked, onLocked, onProblem, onExpired, onBack }: Props) {
  const [recovery, setRecovery] = useState(false);
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [submit, setSubmit] = useState<'idle' | 'busy' | 'done'>('idle');
  const [codesLeft, setCodesLeft] = useState<number | null>(null);  // set after signing in with a recovery code
  const inputRef = useRef<HTMLInputElement>(null);
  const toggled = useRef(false);

  // Switching between app and recovery code puts the cursor back in the field
  useEffect(() => {
    if (toggled.current) inputRef.current?.focus();
    toggled.current = true;
  }, [recovery]);

  function toggle() {
    setRecovery(r => !r);
    setCode('');
    setError('');
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (submit !== 'idle' || locked) return;
    const value = code.trim();
    const problem = !value ? (recovery ? 'Enter one of your recovery codes' : 'Enter the 6-digit code from your app')
      : !recovery && !/^\d{6}$/.test(value) ? 'The code is 6 digits' : '';
    setError(problem);
    if (problem) return inputRef.current?.focus();

    setSubmit('busy');
    const res = await send('/auth/2fa/verify', { code: value });
    if (res.status === 200) {
      const left = res.data?.recovery_codes_left;
      if (typeof left === 'number') {
        setSubmit('idle');
        setCodesLeft(left);
        return;
      }
      setSubmit('done');
      setTimeout(() => location.replace(destination()), reduced ? 0 : 500);
      return;
    }
    setSubmit('idle');
    if (res.status === 401) return onExpired();
    if (res.status === 429) return onLocked(Math.max(1, Math.ceil(res.retryAfter || res.detail?.retry_after || 60)));
    if (res.status === 400 && res.detail?.field === 'code') {
      setError(recovery ? 'That recovery code is not valid, or it has already been used' : res.detail.message);
      inputRef.current?.select();
      return;
    }
    onProblem(res);
  }

  // Signed in with a recovery code: say how many are left before moving on
  if (codesLeft !== null) {
    return (
      <div className="swap">
        <div className={'banner' + (codesLeft > 3 ? ' info' : '')} role="status">
          <span>
            Recovery code accepted. It cannot be used again.{' '}
            {codesLeft === 0 ? <b>That was your last one. Make new recovery codes now, or you could be locked out.</b>
              : <>You have <b>{codesLeft}</b> left{codesLeft <= 3 && '. Make new ones soon'}.</>}
          </span>
        </div>
        <button className="submit" type="button" autoFocus onClick={() => location.replace(destination())}>
          <span className="lbl">Continue</span>
        </button>
        <p className="switch"><a href={DASHBOARD + '#security'}>Make new recovery codes</a></p>
      </div>
    );
  }

  return (
    <>
      <form noValidate onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="code">{recovery ? 'Recovery code' : 'Authentication code'}</label>
          <div className="control">
            <input id="code" ref={inputRef} className="code-input" value={code} readOnly={submit !== 'idle'}
                   aria-invalid={!!error} aria-describedby="codeHint codeErr"
                   {...(recovery
                     ? { type: 'text', autoComplete: 'off', autoCapitalize: 'off', spellCheck: false, maxLength: 20, placeholder: 'abcde-fghjk' }
                     : { type: 'text', inputMode: 'numeric', autoComplete: 'one-time-code', placeholder: '123456' })}
                   // No maxLength: a pasted "123 456" must keep all six digits once the space is removed
                   onChange={e => { setCode(recovery ? e.target.value : e.target.value.replace(/\D/g, '').slice(0, 6)); setError(''); }} />
          </div>
          <p className="hint" id="codeHint">
            {recovery ? 'One of the codes you saved when you turned on two-step verification. Each one works once.'
              : 'Open your authenticator app and enter the code shown for Verixa.'}
          </p>
          {error && <p className="err" id="codeErr" role="alert">{error}</p>}
        </div>

        <button className="submit" type="submit" data-state={submit} aria-busy={submit === 'busy'} disabled={locked}>
          <span className="lbl">Verify</span>
          <span className="spin" aria-hidden="true"></span>
          <span className="ok" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg></span>
        </button>
      </form>

      <p className="switch">
        <button type="button" className="linkish" onClick={toggle}>
          {recovery ? 'Use your authenticator app instead' : 'Use a recovery code instead'}
        </button>
      </p>
      <p className="switch alt">
        <button type="button" className="linkish quiet" onClick={onBack}>Back to log in</button>
      </p>
    </>
  );
}
