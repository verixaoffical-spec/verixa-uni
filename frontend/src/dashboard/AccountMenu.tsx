import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { signOut, type Account } from './api';
import { icons } from './icons';
import { useToast } from './Toast';

interface Props {
  account: Account | null;
  unsavedChanges: number;
  onIntegrations: () => void;
  onSecurity: () => void;
  onSignedOut: () => void;
}

const initialsOf = (name: string) =>
  name.split(/\s+/).filter(Boolean).map(word => [...word][0]).join('').slice(0, 2).toUpperCase() || 'V';

// The round avatar at the bottom of the rail, and the menu it opens
export default function AccountMenu({ account, unsavedChanges, onIntegrations, onSecurity, onSignedOut }: Props) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const avatarRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // While open: focus the first item, and close when clicking anywhere else
  useEffect(() => {
    if (!open) return;
    menuRef.current?.querySelector<HTMLElement>('.acct-item')?.focus();
    const onPointerDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open]);

  // Escape closes, the arrow keys move between items, Tab leaves the menu
  function onKeyDown(e: KeyboardEvent) {
    const items = [...menuRef.current!.querySelectorAll<HTMLElement>('.acct-item')];
    const i = items.indexOf(document.activeElement as HTMLElement);
    if (e.key === 'Escape') {
      e.preventDefault();
      setOpen(false);
      avatarRef.current?.focus();
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus();
    } else if (e.key === 'Tab') {
      setOpen(false);
    }
  }

  async function onSignOut() {
    setSigningOut(true);
    if (await signOut()) {
      setOpen(false);
      onSignedOut();
    } else {
      setSigningOut(false);
      toast('Could not sign out. Check your connection and try again');
    }
  }

  return (
    <div className="rail-foot" ref={rootRef}>
      <button className="avatar" type="button" ref={avatarRef} aria-haspopup="menu" aria-expanded={open}
              aria-label={account ? `Account: ${account.name}` : 'Account'} onClick={() => setOpen(!open)}>
        {account ? initialsOf(account.name) : 'V'}
      </button>
      {open && (
        <div className="acct" role="menu" aria-label="Account" ref={menuRef} onKeyDown={onKeyDown}>
          <div className="acct-who">
            <b>{account?.name}</b>
            <small>{account?.email || (account?.github_login ? `@${account.github_login} on GitHub` : '')}</small>
          </div>
          {unsavedChanges > 0 && <p className="acct-warn">You have unsaved Test Library changes. Signing out discards them.</p>}
          <button className="acct-item" type="button" role="menuitem" onClick={() => { setOpen(false); onIntegrations(); }}>
            {icons.integrations}Integrations
          </button>
          <button className="acct-item" type="button" role="menuitem" onClick={() => { setOpen(false); onSecurity(); }}>
            {icons.lock}Security
          </button>
          <button className="acct-item danger" type="button" role="menuitem" disabled={signingOut} onClick={onSignOut}>
            {icons.signOut}<span>{unsavedChanges ? 'Discard changes and sign out' : 'Sign out'}</span>
          </button>
        </div>
      )}
    </div>
  );
}
