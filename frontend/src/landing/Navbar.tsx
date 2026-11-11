import { useState, type MouseEvent } from 'react';
import { currentTheme, saveTheme, type Theme } from './theme';

// Full paths, so the same navbar works on the landing page and on the log in and sign up page
const LINKS = [
  { label: 'Product', href: '/#product' },
  { label: 'Video', href: '/#video' },
  { label: 'How it works', href: '/#steps' },
  { label: 'Reviews', href: '/#reviews' },
];

type AuthPage = 'login' | 'signup';

interface Props {
  current?: AuthPage;                                            // the log in and sign up page marks where you are
  onAuthLink?: (e: MouseEvent<HTMLAnchorElement>, page: AuthPage) => void;  // and switches without reloading
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(currentTheme);
  const next: Theme = theme === 'dark' ? 'light' : 'dark';

  function toggle() {
    saveTheme(next);
    setTheme(next);
  }

  return (
    <button className="icon-btn" type="button" onClick={toggle} aria-label={`Switch to ${next} theme`} title={`Switch to ${next} theme`}>
      {theme === 'dark'
        ? <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
        : <svg viewBox="0 0 24 24"><path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z" /></svg>}
    </button>
  );
}

// The theme switch shows on the landing page and on the log in and sign up page
export default function Navbar({ current, onAuthLink }: Props) {
  return (
    <header className="nav-wrap">
      <nav className="nav" aria-label="Main">
        <a className="brand" href="/#top" aria-label="Verixa home">
          <img src="/assets/verixa-logo.png" alt="" />
          <span>Verixa</span>
        </a>
        <div className="nav-links">
          {LINKS.map(l => <a key={l.href} href={l.href}>{l.label}</a>)}
        </div>
        <div className="nav-actions">
          <ThemeToggle />
          <a className="btn ghost" href="/login" aria-current={current === 'login' ? 'page' : undefined}
             onClick={e => onAuthLink?.(e, 'login')}>Log in</a>
          <a className="btn solid" href="/signup" aria-current={current === 'signup' ? 'page' : undefined}
             onClick={e => onAuthLink?.(e, 'signup')}>
            Sign up<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
          </a>
        </div>
      </nav>
    </header>
  );
}
