/**
 * Sign up, end to end in a real browser against the real app (tests/e2e/server.py, port 8011).
 * Positive, negative and edge cases for the name (2 to 50 characters), the email and the password, checked twice:
 * in the form, which stops a bad value before anything is sent, and straight at the API, which must refuse it too.
 * Then the email verification: nothing is saved in users until the link from the email is used.
 *
 * Isolation: every test uses a unique email and its own X-Forwarded-For address, so rate limits never leak between
 * tests. Emails go to the test inbox file, and the database is read through a read-only query that never prints a
 * hash or a token. Nothing touches the database in .env.
 */
import { expect, request as playwrightRequest, test, type Browser, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const PYTHON = path.resolve(__dirname, '../../.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const INBOX = path.join(os.tmpdir(), 'verixa-e2e-mail.jsonl');
const PASSWORD = 'Signup-Pass-2026';
const VERIFY = 'Verify your email for Verixa';
const BAD_EMAIL = 'Enter a valid email address, like name@company.com';
const BAD_NAME = 'Use letters, spaces and simple punctuation only';

let seq = 0;
const octet = () => Math.floor(Math.random() * 250) + 1;
const address = () => `${octet()}.${octet()}.${octet()}.${octet()}`;
const unique = () => `${Date.now().toString(36)}${(seq++).toString(36)}${Math.random().toString(36).slice(2, 6)}`;
const freshEmail = () => `su-${unique()}@verixa.dev`;

// ---------- the values under test ----------

/** Emails that must never be accepted. Each is refused by the form and by the server. */
const GARBAGE_EMAILS = [
  'plainaddress', '@nouser.com', 'user@', 'user@@x.com', 'user@x', 'user@x.c', 'user@.com', 'user@com.', 'user@-x.com',
  'user@x-.com', '.user@x.com', 'user.@x.com', 'us..er@x.com', 'user@x..com', 'user name@x.com', 'user@x.com.',
  "'''@x.com", '---@x.com', '+++@x.com', '%%%@x.com', '_@x.com', 'user@x.c0m', 'user@x.123', 'user@1.2.3.4',
  'user@[1.2.3.4]', 'user@localhost', 'user@exa_mple.com', '<script>@x.com', 'user@x.com<script>', 'a;b@x.com',
  'a,b@x.com', 'a(b)@x.com', 'a"b@x.com', 'a@x.com/path', 'a@x.com?q=1', 'javascript:alert(1)@x.com', "' or 1=1--",
  "admin'--@x.com", 'a@x.com; drop table users', '😀@x.com', 'a@😀.com', 'a@b@c.com', '1234567890', '@', '.', '@.',
  'a@x.' + 't'.repeat(25), 'a@' + 'b'.repeat(64) + '.com', 'a'.repeat(65) + '@x.com',
];

/** Real addresses at the edges of the rules. Each is accepted. */
const GOOD_EMAILS = [
  "o'brien@x.com", 'first.last+tag@x.co.uk', '1@2.com', 'a1@b.io', 'a@b.c.d.e.f.com', 'user@xn--bcher-kva.ch',
  'a@x.' + 't'.repeat(24), 'a'.repeat(64) + '@x.com', 'a@' + ['b'.repeat(63), 'b'.repeat(63)].join('.') + '.com', 'a_b%c+d@x.com',
];

const GARBAGE_NAMES = ['123', 'Ada 2', '@@@', '-Ada', "'Ada", '.', 'Ada<b>', 'Ada; drop table users', '😀', 'Ada 😀',
  '<img src=x onerror=alert(1)>', '${7*7}', '{{7*7}}', 'Ada_Lovelace', 'Ada@home', '!!!', '#$%^&*'];

// ---------- helpers ----------

function meta(steps: string[], expected: string, severity: 'Critical' | 'High' | 'Medium' | 'Low') {
  test.info().annotations.push({ type: 'steps', description: steps.join(' → ') },
                               { type: 'expected', description: expected }, { type: 'severity', description: severity });
}

/** The sign up form in a fresh browser with its own address. Counts every request sent to /auth/signup. */
async function signupPage(browser: Browser, baseURL: string) {
  const context = await browser.newContext({ baseURL, extraHTTPHeaders: { 'x-forwarded-for': address() } });
  const page = await context.newPage();
  const problems: string[] = [];
  const sent = { signup: 0 };
  page.on('dialog', d => { problems.push('alert: ' + d.message()); d.dismiss(); });
  page.on('pageerror', e => problems.push('page error: ' + e.message));
  page.on('request', r => { if (r.url().endsWith('/auth/signup')) sent.signup++; });
  await page.goto('/signup');
  await page.waitForFunction(() => document.body.classList.contains('ready') && !document.querySelector('.glass')?.inert);
  return { page, context, problems, sent };
}

async function fill(page: Page, values: { name?: string; email?: string; password?: string }) {
  if (values.name !== undefined) await page.getByLabel('Full name').fill(values.name);
  if (values.email !== undefined) await page.getByLabel('Work email').fill(values.email);
  if (values.password !== undefined) await page.getByRole('textbox', { name: /^Password/ }).fill(values.password);
}

const submit = (page: Page) => page.getByRole('button', { name: 'Create account' }).click();
const errorOf = (page: Page, field: 'name' | 'email' | 'password') => page.locator(`#${field}Err`);

/** Sign up straight at the API, skipping the form, from its own address. */
async function apiSignup(baseURL: string, body: Record<string, unknown>) {
  const api = await playwrightRequest.newContext({ baseURL, extraHTTPHeaders: { 'x-forwarded-for': address() } });
  const res = await api.post('/auth/signup', { data: body });
  const out = { status: res.status(), body: await res.json().catch(() => ({})) };
  await api.dispose();
  return out;
}

function inbox(to: string) {
  if (!fs.existsSync(INBOX)) return [];
  return fs.readFileSync(INBOX, 'utf-8').split('\n').filter(Boolean).map(l => JSON.parse(l))
    .filter((m: { to: string; subject: string }) => m.to === to && m.subject === VERIFY) as { to: string; text: string }[];
}

async function verificationLink(to: string) {
  await expect.poll(() => inbox(to).length, { timeout: 10_000, message: `verification email to ${to}` }).toBeGreaterThan(0);
  const text = inbox(to).at(-1)!.text;
  return /https?:\/\/[^/\s]+(\/verify-email#token=[\w-]+)/.exec(text)![1];
}

/** Read-only facts from the tests' own SQLite file. Never a hash or a token. */
function db(email: string): { users: number; pending: number; name: string | null; hashed: boolean; plain: boolean } {
  const script = [
    'import json, os, sqlite3, sys, tempfile',
    'db = sqlite3.connect("file:" + os.path.join(tempfile.gettempdir(), "verixa-e2e.db").replace(os.sep, "/") + "?mode=ro", uri=True)',
    'email, pw = sys.argv[1], sys.argv[2]',
    'u = db.execute("SELECT name, password_hash FROM users WHERE email = ?", (email,)).fetchone()',
    'p = db.execute("SELECT COUNT(*) FROM pending_signups WHERE email = ?", (email,)).fetchone()[0]',
    'print(json.dumps({"users": 1 if u else 0, "pending": p, "name": u[0] if u else None,',
    '  "hashed": bool(u) and u[1].startswith("scrypt$"), "plain": bool(u) and pw in u[1]}))',
  ].join('\n');
  return JSON.parse(execFileSync(PYTHON, ['-c', script, email, PASSWORD], { encoding: 'utf-8' }));
}

function totalUsers(): number {
  return Number(execFileSync(PYTHON, ['-c', [
    'import os, sqlite3, tempfile',
    'db = sqlite3.connect("file:" + os.path.join(tempfile.gettempdir(), "verixa-e2e.db").replace(os.sep, "/") + "?mode=ro", uri=True)',
    'print(db.execute("SELECT COUNT(*) FROM users").fetchone()[0])'].join('\n')], { encoding: 'utf-8' }).trim());
}

// =====================================================================================================================

test.describe('1. Name', () => {
  test('SU-NAME-01 an empty name is refused before anything is sent', async ({ browser, baseURL }) => {
    meta(['Leave Full name empty', 'Fill a valid email and password', 'Create account'], '"Enter your name", no request', 'High');
    const { page, sent, context } = await signupPage(browser, baseURL!);
    await fill(page, { name: '', email: freshEmail(), password: PASSWORD });
    await submit(page);
    await expect(errorOf(page, 'name')).toHaveText('Enter your name');
    expect(sent.signup).toBe(0);
    await context.close();
  });

  test('SU-NAME-02 only spaces counts as empty', async ({ browser, baseURL }) => {
    meta(['Type only spaces as the name', 'Create account'], '"Enter your name"', 'Medium');
    const { page, sent, context } = await signupPage(browser, baseURL!);
    await fill(page, { name: '     ', email: freshEmail(), password: PASSWORD });
    await submit(page);
    await expect(errorOf(page, 'name')).toHaveText('Enter your name');
    expect(sent.signup).toBe(0);
    await context.close();
  });

  test('SU-NAME-03 one character is too short (minimum is 2)', async ({ browser, baseURL }) => {
    meta(['Name "A"', 'Create account'], '"Use at least 2 characters"', 'Medium');
    const { page, sent, context } = await signupPage(browser, baseURL!);
    await fill(page, { name: 'A', email: freshEmail(), password: PASSWORD });
    await submit(page);
    await expect(errorOf(page, 'name')).toHaveText('Use at least 2 characters');
    expect(sent.signup).toBe(0);
    await context.close();
  });

  test('SU-NAME-04 exactly 2 characters is accepted (lower edge)', async ({ browser, baseURL }) => {
    meta(['Name "Al"', 'Create account'], 'Check your inbox', 'High');
    const { page, context } = await signupPage(browser, baseURL!);
    await fill(page, { name: 'Al', email: freshEmail(), password: PASSWORD });
    await submit(page);
    await expect(page.getByRole('heading', { name: 'Check your inbox' })).toBeVisible();
    await context.close();
  });

  test('SU-NAME-05 exactly 50 characters is accepted (upper edge)', async ({ browser, baseURL }) => {
    meta(['Name of 50 letters', 'Create account'], 'Check your inbox', 'High');
    const { page, context } = await signupPage(browser, baseURL!);
    await fill(page, { name: 'A'.repeat(50), email: freshEmail(), password: PASSWORD });
    await submit(page);
    await expect(page.getByRole('heading', { name: 'Check your inbox' })).toBeVisible();
    await context.close();
  });

  test('SU-NAME-06 the field stops at 50 characters', async ({ browser, baseURL }) => {
    meta(['Type 70 letters into Full name'], 'The field keeps only 50', 'Medium');
    const { page, context } = await signupPage(browser, baseURL!);
    await expect(page.getByLabel('Full name')).toHaveAttribute('maxlength', '50');
    await page.getByLabel('Full name').pressSequentially('B'.repeat(70));
    expect((await page.getByLabel('Full name').inputValue()).length).toBe(50);
    await context.close();
  });

  test('SU-NAME-07 the server refuses 51 characters even without the form', async ({ baseURL }) => {
    meta(['POST /auth/signup with a 51 character name'], '422 on the name field, nothing saved', 'High');
    const email = freshEmail();
    const res = await apiSignup(baseURL!, { name: 'A'.repeat(51), email, password: PASSWORD });
    expect(res.status).toBe(422);
    expect(res.body.detail).toEqual({ field: 'name', message: 'Use 50 characters or fewer' });
    expect(db(email)).toMatchObject({ users: 0, pending: 0 });
  });

  test('SU-NAME-08 garbage names are refused by the form', async ({ browser, baseURL }) => {
    meta(['Try each garbage name', 'Create account'], `"${BAD_NAME}" each time, no request`, 'High');
    const { page, sent, context, problems } = await signupPage(browser, baseURL!);
    await fill(page, { email: freshEmail(), password: PASSWORD });
    for (const name of GARBAGE_NAMES) {
      await fill(page, { name });
      await submit(page);
      await expect(errorOf(page, 'name'), name).toHaveText(BAD_NAME);
    }
    expect(sent.signup).toBe(0);
    expect(problems).toEqual([]);  // no injected script ran
    await context.close();
  });

  test('SU-NAME-09 garbage names are refused by the server too', async ({ baseURL }) => {
    meta(['POST each garbage name to /auth/signup'], '422 on the name field each time', 'High');
    for (const name of GARBAGE_NAMES) {
      const res = await apiSignup(baseURL!, { name, email: freshEmail(), password: PASSWORD });
      expect(res.status, name).toBe(422);
      expect(res.body.detail.field, name).toBe('name');
    }
  });

  test('SU-NAME-10 accents, apostrophes and hyphens are fine, and spaces are tidied', async ({ browser, baseURL }) => {
    meta(['Name "  Zoë   O\'Brien-Smith "', 'Sign up and verify'], 'Saved as "Zoë O\'Brien-Smith"', 'Medium');
    const { page, context } = await signupPage(browser, baseURL!);
    const email = freshEmail();
    await fill(page, { name: "  Zoë   O'Brien-Smith ", email, password: PASSWORD });
    await submit(page);
    await expect(page.getByRole('heading', { name: 'Check your inbox' })).toBeVisible();
    await page.goto(await verificationLink(email));
    await page.getByRole('button', { name: 'Verify my email' }).click();
    await page.waitForURL('**/verixa_prototype.html**');
    expect(db(email).name).toBe("Zoë O'Brien-Smith");
    await context.close();
  });
});

test.describe('2. Email', () => {
  test('SU-EMAIL-01 an empty email is refused', async ({ browser, baseURL }) => {
    meta(['Leave Work email empty', 'Create account'], '"Enter your email address"', 'High');
    const { page, sent, context } = await signupPage(browser, baseURL!);
    await fill(page, { name: 'Ada Lovelace', email: '', password: PASSWORD });
    await submit(page);
    await expect(errorOf(page, 'email')).toHaveText('Enter your email address');
    expect(sent.signup).toBe(0);
    await context.close();
  });

  test('SU-EMAIL-02 garbage emails are refused by the form', async ({ browser, baseURL }) => {
    meta(['Try each garbage email', 'Create account'], `"${BAD_EMAIL}" each time, no request`, 'Critical');
    const { page, sent, context, problems } = await signupPage(browser, baseURL!);
    await fill(page, { name: 'Ada Lovelace', password: PASSWORD });
    // Chrome turns an emoji domain into its punycode form (a@xn--e28h.com), a real kind of address, before the page
    // sees it. Sent as typed, the server still refuses it (SU-EMAIL-03).
    for (const email of GARBAGE_EMAILS.filter(e => e !== 'a@😀.com')) {
      await fill(page, { email });
      await submit(page);
      await expect(errorOf(page, 'email'), email).toHaveText(BAD_EMAIL);
    }
    expect(sent.signup).toBe(0);
    expect(problems).toEqual([]);
    await context.close();
  });

  test('SU-EMAIL-03 garbage emails are refused by the server too', async ({ baseURL }) => {
    meta(['POST each garbage email to /auth/signup'], '422 on the email field, no account, no email sent', 'Critical');
    const before = totalUsers();
    for (const email of [...GARBAGE_EMAILS, 'a@x.com\u0000', 'a\tb@x.com', 'a'.repeat(250) + '@x.com']) {
      const res = await apiSignup(baseURL!, { name: 'Ada Lovelace', email, password: PASSWORD });
      expect(res.status, email).toBe(422);
      expect(res.body.detail.field, email).toBe('email');
      expect(inbox(email), email).toEqual([]);
    }
    expect(totalUsers()).toBe(before);
  });

  test('SU-EMAIL-04 real addresses at the edges are accepted', async ({ browser, baseURL }) => {
    meta(['Type each edge-case address', 'Leave the field'], 'No error shown for any of them', 'High');
    const { page, context } = await signupPage(browser, baseURL!);
    for (const email of GOOD_EMAILS) {
      await fill(page, { email });
      await page.getByLabel('Full name').focus();  // leaving the field runs its check
      await expect(errorOf(page, 'email'), email).toHaveCount(0);
    }
    await context.close();
  });

  test('SU-EMAIL-05 the server accepts the same edge addresses', async ({ baseURL }) => {
    meta(['POST each edge address, each with a unique tag'], '202 and a verification email', 'High');
    for (const email of GOOD_EMAILS) {
      const res = await apiSignup(baseURL!, { name: 'Ada Lovelace', email, password: PASSWORD });
      expect(res.status, email).toBe(202);
    }
  });

  test('SU-EMAIL-06 capitals and spaces are tidied before saving', async ({ browser, baseURL }) => {
    meta(['Email "  SU-Mixed@Verixa.DEV "', 'Create account'], 'The link goes to the lowercase address', 'Medium');
    const { page, context } = await signupPage(browser, baseURL!);
    const lower = freshEmail();
    await fill(page, { name: 'Ada Lovelace', email: '  ' + lower.toUpperCase() + ' ', password: PASSWORD });
    await submit(page);
    await expect(page.getByText(lower, { exact: true })).toBeVisible();
    expect(await verificationLink(lower)).toContain('/verify-email#token=');
    await context.close();
  });

  test('SU-EMAIL-07 the field stops at 254 characters', async ({ browser, baseURL }) => {
    meta(['Look at the email field'], 'maxlength is 254', 'Low');
    const { page, context } = await signupPage(browser, baseURL!);
    await expect(page.getByLabel('Work email')).toHaveAttribute('maxlength', '254');
    await context.close();
  });

  test('SU-EMAIL-08 an email that already has an account is refused', async ({ browser, baseURL }) => {
    meta(['Sign up with demo@verixa.dev, which exists'], '"An account with this email already exists." and Log in instead', 'High');
    const { page, context } = await signupPage(browser, baseURL!);
    await fill(page, { name: 'Ada Lovelace', email: 'demo@verixa.dev', password: PASSWORD });
    await submit(page);
    await expect(errorOf(page, 'email')).toContainText('An account with this email already exists.');
    await expect(page.getByRole('button', { name: 'Log in instead' })).toBeVisible();
    expect(inbox('demo@verixa.dev')).toEqual([]);
    await context.close();
  });
});

test.describe('3. Password', () => {
  const cases: [string, string, string][] = [
    ['empty', '', 'Enter a password'],
    ['7 characters', 'Abcde12', 'Use at least 8 characters'],
    ['letters only', 'OnlyLettersHere', 'Use at least one letter and one number'],
    ['numbers only', '1234567890123', 'Use at least one letter and one number'],
    ['a common password', 'password123', 'That password is too common. Pick something less guessable'],
    ['the same character again and again', 'aaaaaaa1', 'That password is too common. Pick something less guessable'],
    ['only spaces', '          ', 'A password cannot be only spaces'],
  ];
  for (const [what, password, message] of cases) {
    test(`SU-PW ${what} is refused`, async ({ browser, baseURL }) => {
      meta([`Password: ${what}`, 'Create account'], `"${message}", no request`, 'High');
      const { page, sent, context } = await signupPage(browser, baseURL!);
      await fill(page, { name: 'Ada Lovelace', email: freshEmail(), password });
      await submit(page);
      await expect(errorOf(page, 'password')).toHaveText(message);
      expect(sent.signup).toBe(0);
      await context.close();
    });
  }

  test('SU-PW containing the name is refused', async ({ browser, baseURL }) => {
    meta(['Name "Grace Hopper", password "GraceHopper99"'], '"Do not use your name in the password"', 'Medium');
    const { page, context } = await signupPage(browser, baseURL!);
    await fill(page, { name: 'Grace Hopper', email: freshEmail(), password: 'GraceHopper99' });
    await submit(page);
    await expect(errorOf(page, 'password')).toHaveText('Do not use your name in the password');
    await context.close();
  });

  test('SU-PW containing the email is refused', async ({ browser, baseURL }) => {
    meta(['Email gracie@verixa.dev, password "gracie2026!"'], '"Do not use your email address in the password"', 'Medium');
    const { page, context } = await signupPage(browser, baseURL!);
    await fill(page, { name: 'Ada Lovelace', email: 'gracie@verixa.dev', password: 'gracie2026!' });
    await submit(page);
    await expect(errorOf(page, 'password')).toHaveText('Do not use your email address in the password');
    await context.close();
  });

  test('SU-PW exactly 8 and exactly 128 characters are accepted (edges)', async ({ baseURL }) => {
    meta(['POST passwords of 8 and 128 characters'], '202 for both', 'High');
    for (const password of ['Abcdef12', 'Ab1' + 'xyz9'.repeat(31) + 'Q']) {
      expect(password.length === 8 || password.length === 128).toBe(true);
      expect((await apiSignup(baseURL!, { name: 'Ada Lovelace', email: freshEmail(), password })).status).toBe(202);
    }
  });

  test('SU-PW 129 characters is refused by the server', async ({ baseURL }) => {
    meta(['POST a 129 character password'], '422 on the password field', 'Medium');
    const res = await apiSignup(baseURL!, { name: 'Ada Lovelace', email: freshEmail(), password: 'Ab1' + 'x'.repeat(126) });
    expect(res.status).toBe(422);
    expect(res.body.detail.field).toBe('password');
  });
});

test.describe('4. Wrong shapes sent to the server', () => {
  test('SU-API-01 missing fields, wrong types and broken JSON are refused', async ({ baseURL }) => {
    meta(['POST odd bodies to /auth/signup'], '422 for every one, nothing saved', 'High');
    const before = totalUsers();
    const bodies: unknown[] = [{}, { name: 'Ada' }, { email: freshEmail() }, { name: 123, email: freshEmail(), password: PASSWORD },
      { name: ['Ada'], email: freshEmail(), password: PASSWORD }, { name: 'Ada Lovelace', email: null, password: PASSWORD },
      { name: 'Ada Lovelace', email: freshEmail(), password: 12345678 }, { name: 'x'.repeat(600), email: freshEmail(), password: PASSWORD }];
    for (const body of bodies) expect((await apiSignup(baseURL!, body as Record<string, unknown>)).status, JSON.stringify(body)).toBe(422);
    const api = await playwrightRequest.newContext({ baseURL, extraHTTPHeaders: { 'x-forwarded-for': address() } });
    const broken = await api.post('/auth/signup', { headers: { 'content-type': 'application/json' }, data: '{"name": "Ada", ' });
    expect(broken.status()).toBe(422);
    await api.dispose();
    expect(totalUsers()).toBe(before);
  });

  test('SU-API-02 a form posted from another website is refused', async ({ baseURL }) => {
    meta(['POST /auth/signup with Origin https://evil.example'], '403, nothing saved', 'Critical');
    const email = freshEmail();
    const api = await playwrightRequest.newContext({ baseURL, extraHTTPHeaders: { 'x-forwarded-for': address(), origin: 'https://evil.example' } });
    const res = await api.post('/auth/signup', { data: { name: 'Ada Lovelace', email, password: PASSWORD } });
    expect(res.status()).toBe(403);
    await api.dispose();
    expect(db(email)).toMatchObject({ users: 0, pending: 0 });
  });
});

test.describe('5. Email verification', () => {
  test('SU-VER-01 the whole journey: nothing in users until the link is used', async ({ browser, baseURL }) => {
    meta(['Sign up in the form', 'Check the database', 'Open the link from the email', 'Press Verify my email'],
         'Pending only, then a user with a hashed password, signed in on the dashboard', 'Critical');
    const { page, context, problems } = await signupPage(browser, baseURL!);
    const email = freshEmail();
    await fill(page, { name: 'Ada Lovelace', email, password: PASSWORD });
    await submit(page);
    await expect(page.getByRole('heading', { name: 'Check your inbox' })).toBeVisible();
    expect(db(email)).toMatchObject({ users: 0, pending: 1 });

    await page.goto(await verificationLink(email));
    await expect(page.getByRole('heading', { name: 'Verify your email' })).toBeVisible();
    expect(db(email)).toMatchObject({ users: 0, pending: 1 });  // opening the link alone creates nothing
    await page.getByRole('button', { name: 'Verify my email' }).click();
    await page.waitForURL('**/verixa_prototype.html**');
    expect(db(email)).toEqual({ users: 1, pending: 0, name: 'Ada Lovelace', hashed: true, plain: false });
    expect(problems).toEqual([]);
    await context.close();
  });

  test('SU-VER-02 logging in before verifying does not work', async ({ baseURL }) => {
    meta(['Sign up through the API', 'Log in with the same email and password'], '401, no session', 'Critical');
    const email = freshEmail();
    expect((await apiSignup(baseURL!, { name: 'Ada Lovelace', email, password: PASSWORD })).status).toBe(202);
    const api = await playwrightRequest.newContext({ baseURL, extraHTTPHeaders: { 'x-forwarded-for': address() } });
    expect((await api.post('/auth/login', { data: { email, password: PASSWORD } })).status()).toBe(401);
    await api.dispose();
  });

  test('SU-VER-03 a used link cannot be used again', async ({ browser, baseURL }) => {
    meta(['Verify once', 'Open the same link again and press Verify'], '"Link not valid", still one user', 'High');
    const email = freshEmail();
    expect((await apiSignup(baseURL!, { name: 'Ada Lovelace', email, password: PASSWORD })).status).toBe(202);
    const link = await verificationLink(email);
    for (const expected of ['/verixa_prototype.html', 'Link not valid']) {
      const context = await browser.newContext({ baseURL, extraHTTPHeaders: { 'x-forwarded-for': address() } });
      const page = await context.newPage();
      await page.goto(link);
      await page.getByRole('button', { name: 'Verify my email' }).click();
      if (expected.startsWith('/')) await page.waitForURL('**' + expected + '**');
      else await expect(page.getByRole('heading', { name: expected })).toBeVisible();
      await context.close();
    }
    expect(db(email)).toMatchObject({ users: 1, pending: 0 });
  });

  test('SU-VER-04 a made-up or cut short link is refused', async ({ browser, baseURL }) => {
    meta(['Open /verify-email with a fake token, and with none'], '"Link not valid" each time', 'High');
    const context = await browser.newContext({ baseURL, extraHTTPHeaders: { 'x-forwarded-for': address() } });
    const page = await context.newPage();
    await page.goto('/verify-email#token=' + 'x'.repeat(43));
    await page.getByRole('button', { name: 'Verify my email' }).click();
    await expect(page.getByRole('heading', { name: 'Link not valid' })).toBeVisible();
    await page.goto('/verify-email');
    await expect(page.getByRole('heading', { name: 'Link not valid' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Sign up again' })).toBeVisible();
    await context.close();
  });

  test('SU-VER-05 the token never stays in the address bar', async ({ browser, baseURL }) => {
    meta(['Open the verification link'], 'The #token part is removed at once', 'Medium');
    const email = freshEmail();
    expect((await apiSignup(baseURL!, { name: 'Ada Lovelace', email, password: PASSWORD })).status).toBe(202);
    const context = await browser.newContext({ baseURL });
    const page = await context.newPage();
    await page.goto(await verificationLink(email));
    await expect(page.getByRole('heading', { name: 'Verify your email' })).toBeVisible();
    expect(page.url()).not.toContain('token');
    await context.close();
  });

  test('SU-VER-06 one inbox gets at most 3 verification emails an hour', async ({ baseURL }) => {
    meta(['Sign up 4 times with one email, each from a different address'], '202 three times, then 429', 'Medium');
    const email = freshEmail();
    for (let i = 0; i < 3; i++) expect((await apiSignup(baseURL!, { name: 'Ada Lovelace', email, password: PASSWORD })).status).toBe(202);
    expect((await apiSignup(baseURL!, { name: 'Ada Lovelace', email, password: PASSWORD })).status).toBe(429);
    await expect.poll(() => inbox(email).length).toBe(3);
  });
});
