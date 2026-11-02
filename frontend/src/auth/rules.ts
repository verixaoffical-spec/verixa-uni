// Sign up and log in checks. Kept in step with backend/accounts.py, which has the final say.

export type Mode = 'login' | 'signup';
export type Field = 'name' | 'email' | 'password';
export type Values = Record<Field, string>;

export const DASHBOARD = '/verixa_prototype.html';

const EMAIL_RE = /^[^@\s]{1,64}@[^@\s]+\.[^@\s.]{2,}$/;
const COMMON = new Set(['password', 'password1', 'password12', 'password123', '12345678', '123456789', '1234567890', 'qwerty123',
  'qwertyuiop', 'iloveyou1', 'letmein123', 'welcome1', 'welcome123', 'admin123', 'abc12345', 'passw0rd', '11111111', '00000000',
  'verixa123', 'monkey123', 'dragon123', 'football1', 'baseball1', 'sunshine1']);

export const normEmail = (v: string) => v.normalize('NFKC').trim().toLowerCase();
export const normName = (v: string) => v.normalize('NFKC').trim().split(/\s+/).filter(Boolean).join(' ');
export const hasLetterAndNumber = (pw: string) => /[A-Za-z]/.test(pw) && /\d/.test(pw);

// Returns what is wrong with one field, or null when it is fine.
export function problem(field: Field, values: Values, mode: Mode): string | null {
  const email = normEmail(values.email), name = normName(values.name), pw = values.password;

  if (field === 'name') {
    if (!name) return 'Enter your name';
    if (name.length > 80) return 'Use 80 characters or fewer';
    if (/[<>\p{C}]/u.test(name)) return 'Use letters, spaces and simple punctuation only';
  }

  if (field === 'email') {
    if (!email) return 'Enter your email address';
    if (email.length > 254 || !EMAIL_RE.test(email) || email.includes('..')) return 'Enter a valid email address, like name@company.com';
  }

  if (field === 'password') {
    if (!pw) return mode === 'login' ? 'Enter your password' : 'Enter a password';
    if (mode === 'login') return null;
    if (pw.length < 8) return 'Use at least 8 characters';
    if (pw.length > 128) return 'Use 128 characters or fewer';
    if (!pw.trim()) return 'A password cannot be only spaces';
    if (!hasLetterAndNumber(pw)) return 'Use at least one letter and one number';
    const lower = pw.toLowerCase(), localPart = email.split('@')[0];
    if (COMMON.has(lower)) return 'That password is too common. Pick something less guessable';
    if ((localPart.length >= 4 && lower.includes(localPart)) || (email && lower === email)) return 'Do not use your email address in the password';
    if (name.length >= 4 && lower.replace(/ /g, '').includes(name.toLowerCase().replace(/ /g, ''))) return 'Do not use your name in the password';
  }

  return null;
}

// Password strength from 0 (empty) to 4 (strong), for the meter under the field.
export function strength(pw: string): number {
  if (!pw) return 0;
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) score++;
  if (pw.length < 8 || COMMON.has(pw.toLowerCase())) score = Math.min(score, 1);
  return Math.max(1, Math.min(4, score));
}

// Where to go after signing in. Only paths on this site are allowed, so the page can never bounce people elsewhere.
export function destination(): string {
  const next = new URLSearchParams(location.search).get('next');
  let target = DASHBOARD;
  if (next && next.length <= 500 && next.startsWith('/') && !next.startsWith('//') && !next.includes('\\')
      && !/[\u0000-\u001f]/.test(next) && !['/login', '/signup'].includes(next.split(/[?#]/)[0])) {
    target = next;
  }
  const hash = /^#[\w-]{1,40}$/.test(location.hash) ? location.hash : '';
  return target + (next?.includes('#') ? '' : hash);
}
