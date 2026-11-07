/**
 * Forgot Password, end to end in a real browser against the real app (tests/e2e/server.py, port 8011).
 * Frontend, backend, database and security checks, from the QA list in tests.txt (kept out of Git).
 *
 * Isolation: every test makes its own account with a unique email, and sends a unique X-Forwarded-For
 * address, so the rate limits of one test never affect another. Nothing touches the database in .env.
 * Emails go to a test inbox file (server.py), and the database is read through db_check.py, which never
 * prints a hash or a token. Test IDs (FP-...) match FORGOT_PASSWORD_QA_REPORT.md.
 */
import { expect, request as playwrightRequest, test, type APIRequestContext, type Browser, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const PYTHON = path.resolve(__dirname, '../../.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const INBOX = path.join(os.tmpdir(), 'verixa-e2e-mail.jsonl');
const ORIGINAL = 'Original-Pass-2026';
const NEW = 'Fresh-Start-2027';
const NAME = 'Reset Tester';
const GENERIC = 'If an account uses that email, we have sent it a link to reset the password.';

let seq = 0;
const octet = () => Math.floor(Math.random() * 250) + 1;
const address = (first: number) => `${first}.${octet()}.${octet()}.${octet()}`;
const unique = () => `${Date.now().toString(36)}${(seq++).toString(36)}${Math.random().toString(36).slice(2, 6)}`;

// ---------- helpers ----------

/** Records what the report needs besides pass or fail: the steps, the expected result and the severity if it fails. */
function meta(steps: string[], expected: string, severity: 'Critical' | 'High' | 'Medium' | 'Low') {
  test.info().annotations.push({ type: 'steps', description: steps.join(' → ') },
                               { type: 'expected', description: expected }, { type: 'severity', description: severity });
}

/** A browser page that looks like its own visitor (own address), with alerts and page errors recorded. */
async function visitor(browser: Browser, baseURL: string) {
  const ip = address(10);
  const context = await browser.newContext({ baseURL, extraHTTPHeaders: { 'x-forwarded-for': ip } });
  const page = await context.newPage();
  const problems: string[] = [];
  page.on('dialog', d => { problems.push('alert: ' + d.message()); d.dismiss(); });
  page.on('pageerror', e => problems.push('page error: ' + e.message));
  page.on('console', m => {
    if (m.type() === 'error' && !/fonts\.g|Failed to load resource/.test(m.text())) problems.push('console: ' + m.text());
  });
  return { page, context, ip, problems };
}

/** A new account made through the real sign up API, from its own address. Returns its email. */
async function account(baseURL: string, email = `fp-${unique()}@verixa.dev`, name = NAME): Promise<string> {
  const api = await playwrightRequest.newContext({ baseURL, extraHTTPHeaders: { 'x-forwarded-for': address(172) } });
  const res = await api.post('/auth/signup', { data: { name, email, password: ORIGINAL } });
  expect(res.status(), await res.text()).toBe(201);
  await api.dispose();
  return email;
}

/** An API client with its own address and no session. */
async function client(baseURL: string): Promise<APIRequestContext> {
  return playwrightRequest.newContext({ baseURL, extraHTTPHeaders: { 'x-forwarded-for': address(192) } });
}

/** Every email the app sent to this address, oldest first. */
function inbox(to: string): { to: string; subject: string; text: string }[] {
  if (!fs.existsSync(INBOX)) return [];
  return fs.readFileSync(INBOX, 'utf-8').split('\n').filter(Boolean).map(l => JSON.parse(l)).filter(m => m.to === to);
}

async function waitForEmail(to: string, count = 1) {
  await expect.poll(() => inbox(to).length, { timeout: 10_000, message: `email to ${to}` }).toBeGreaterThanOrEqual(count);
  return inbox(to)[count - 1];
}

const tokenOf = (text: string) => /#token=([\w-]+)/.exec(text)?.[1] ?? '';
const linkOf = (text: string) => /(https?:\/\/\S+\/reset-password#token=[\w-]+)/.exec(text)?.[1] ?? '';
const pathOf = (link: string) => link.replace(/^https?:\/\/[^/]+/, '');

/** Read-only database facts for one account. Never includes a hash or a token. */
function db(email: string, opts: { password?: string; token?: string } = {}) {
  const args = ['tests/e2e/db_check.py', email];
  if (opts.password) args.push('--password', opts.password);
  if (opts.token) args.push('--token', opts.token);
  return JSON.parse(execFileSync(PYTHON, args, { cwd: path.resolve(__dirname, '../..'), encoding: 'utf-8' }));
}

/** Test setup only, on the tests' own SQLite file: moves a link's expiry into the past. */
function expireLinks(email: string) {
  execFileSync(PYTHON, ['-c', [
    'import sqlite3, sys, tempfile, os',
    'db = sqlite3.connect(os.path.join(tempfile.gettempdir(), "verixa-e2e.db"))',
    'db.execute("UPDATE password_resets SET expires_at = \'2000-01-01 00:00:00\' WHERE user_id = (SELECT id FROM users WHERE email = ?)", (sys.argv[1],))',
    'db.commit()'].join('\n'), email]);
}

async function requestLink(page: Page, email: string) {
  await page.goto('/forgot-password');
  await page.getByLabel('Email').fill(email);
  await page.getByRole('button', { name: 'Send reset link' }).click();
  await expect(page.getByRole('heading', { name: 'Check your inbox' })).toBeVisible();
}

/** Asks for a link through the API from a fresh address, and returns the token from the email. */
async function linkFor(baseURL: string, email: string, nth = 1) {
  const api = await client(baseURL);
  expect((await api.post('/auth/forgot', { data: { email } })).status()).toBe(202);
  await api.dispose();
  const mail = await waitForEmail(email, nth);
  return { token: tokenOf(mail.text), path: pathOf(linkOf(mail.text)) };
}

async function choose(page: Page, password: string, again = password) {
  await page.getByRole('textbox', { name: /^New password/ }).fill(password);
  await page.getByLabel('Type it again').fill(again);
  await page.getByRole('button', { name: 'Save new password' }).click();
}

/** Logs in through the real login form. The card ignores input until its entrance has finished, so wait for that first. */
async function uiLogin(page: Page, email: string, password: string) {
  await page.goto('/login');
  await page.waitForFunction(() => document.body.classList.contains('ready') && !document.querySelector('.glass')?.inert);
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Log in' }).last().click();
}

async function apiLogin(baseURL: string, email: string, password: string) {
  const api = await client(baseURL);
  const res = await api.post('/auth/login', { data: { email, password } });
  await api.dispose();
  return res.status();
}

let current: Awaited<ReturnType<typeof visitor>> | null = null;
test.afterEach(async () => {
  if (current) {
    const problems = current.problems;
    await current.context.close();
    current = null;
    expect(problems, 'no alert, page error or console error').toEqual([]);
  }
});

async function open(browser: Browser, baseURL: string) {
  current = await visitor(browser, baseURL);
  return current;
}

// ---------- 1. Navigation ----------

test.describe('1. Navigation', () => {
  test('FP-NAV-01 the login page shows a Forgot password link', async ({ browser, baseURL }) => {
    meta(['Open /login', 'Find the Forgot password? link'], 'The link is visible, enabled and points to /forgot-password', 'High');
    const { page } = await open(browser, baseURL!);
    await page.goto('/login');
    const link = page.getByRole('link', { name: 'Forgot password?' });
    await expect(link).toBeVisible();
    await expect(link).toBeEnabled();
    await expect(link).toHaveAttribute('href', '/forgot-password');
  });

  test('FP-NAV-02 clicking it opens the Forgot Password page', async ({ browser, baseURL }) => {
    meta(['Open /login', 'Click Forgot password?'], 'The browser is on /forgot-password with the heading "Forgot your password?"', 'High');
    const { page } = await open(browser, baseURL!);
    await page.goto('/login');
    await page.getByRole('link', { name: 'Forgot password?' }).click();
    await expect(page).toHaveURL(/\/forgot-password$/);
    await expect(page.getByRole('heading', { name: 'Forgot your password?' })).toBeVisible();
    await expect(page).toHaveTitle('Forgot password · Verixa');
  });

  test('FP-NAV-03 the page has an email field, a submit button and a way back, in that order', async ({ browser, baseURL }) => {
    meta(['Open /forgot-password', 'Check each element'], 'Email field, Send reset link button and Back to log in link are visible and enabled; field above button above link', 'Medium');
    const { page } = await open(browser, baseURL!);
    await page.goto('/forgot-password');
    const email = page.getByLabel('Email'), button = page.getByRole('button', { name: 'Send reset link' });
    const back = page.getByRole('link', { name: 'Back to log in' });
    for (const el of [email, button, back]) { await expect(el).toBeVisible(); await expect(el).toBeEnabled(); }
    await expect(email).toHaveAttribute('type', 'email');
    await expect(email).toHaveAttribute('autocomplete', 'email');
    const [a, b, c] = await Promise.all([email.boundingBox(), button.boundingBox(), back.boundingBox()]);
    expect(a!.y).toBeLessThan(b!.y);
    expect(b!.y).toBeLessThan(c!.y);
  });

  test('FP-NAV-04 Back to log in returns to the login page', async ({ browser, baseURL }) => {
    meta(['Open /forgot-password', 'Click Back to log in'], 'The browser is on /login', 'Medium');
    const { page } = await open(browser, baseURL!);
    await page.goto('/forgot-password');
    await page.getByRole('link', { name: 'Back to log in' }).click();
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
  });
});

// ---------- 2. Email validation ----------

test.describe('2. Email validation', () => {
  for (const [id, value, why, message] of [
    ['FP-EM-01', '', 'empty', 'Enter your email address'],
    ['FP-EM-02', 'abc123', 'no @ at all', 'Enter a valid email address'],
    ['FP-EM-03', 'user@gmail', 'no domain ending', 'Enter a valid email address'],
    ['FP-EM-04', '@gmail.com', 'no username', 'Enter a valid email address'],
  ] as const) {
    test(`${id} ${why} email is refused before anything is sent`, async ({ browser, baseURL }) => {
      meta([`Open /forgot-password`, `Enter "${value}"`, 'Click Send reset link'], `Message "${message}", no request sent, page stays on the form`, 'Medium');
      const { page } = await open(browser, baseURL!);
      await page.goto('/forgot-password');
      const sent: string[] = [];
      page.on('request', r => { if (r.url().endsWith('/auth/forgot')) sent.push(r.url()); });
      await page.getByLabel('Email').fill(value);
      await page.getByRole('button', { name: 'Send reset link' }).click();
      await expect(page.locator('#emailErr')).toContainText(message);
      await expect(page.getByLabel('Email')).toHaveAttribute('aria-invalid', 'true');
      expect(sent).toEqual([]);
      // The server refuses it too, for anyone who skips the page
      if (value) {
        const api = await client(baseURL!);
        expect((await api.post('/auth/forgot', { data: { email: value } })).status()).toBe(422);
        await api.dispose();
      }
    });
  }

  test('FP-EM-05 a registered email gets the confirmation and an email', async ({ browser, baseURL }) => {
    meta(['Make an account', 'Ask for a link with its email'], '"Check your inbox" screen, one email in the inbox', 'Critical');
    const email = await account(baseURL!);
    const { page } = await open(browser, baseURL!);
    await requestLink(page, email);
    await expect(page.getByText('a reset link is on its way')).toBeVisible();
    expect((await waitForEmail(email)).subject).toBe('Reset your Verixa password');
  });

  test('FP-EM-06 an unregistered email gets the same answer and no email', async ({ browser, baseURL }) => {
    meta(['Ask for a link for an email with no account', 'Compare with a registered one'], 'Same screen and same API answer as a registered email; no email sent', 'High');
    const registered = await account(baseURL!);
    const nobody = `nobody-${unique()}@verixa.dev`;
    const { page } = await open(browser, baseURL!);
    await requestLink(page, nobody);
    const api = await client(baseURL!);
    const [a, b] = [await api.post('/auth/forgot', { data: { email: registered } }), await api.post('/auth/forgot', { data: { email: `nobody2-${unique()}@verixa.dev` } })];
    expect([a.status(), b.status()]).toEqual([202, 202]);
    expect(await a.json()).toEqual(await b.json());
    expect((await a.json()).message).toContain(GENERIC);
    await api.dispose();
    await waitForEmail(registered);
    expect(inbox(nobody)).toEqual([]);
  });

  test('FP-EM-07 spaces and capitals around the email are removed', async ({ browser, baseURL }) => {
    meta(['Enter "  EMAIL  " with spaces and capitals'], 'Accepted; the email goes to the trimmed, lowercase address', 'Medium');
    const email = await account(baseURL!);
    const { page } = await open(browser, baseURL!);
    await requestLink(page, `   ${email.toUpperCase()}   `);
    expect((await waitForEmail(email)).to).toBe(email);
  });

  test('FP-EM-08 an extremely long email is refused', async ({ browser, baseURL }) => {
    meta(['Type a 300 character email', 'Send it straight to the API too'], 'The field holds at most 254 characters; the page shows an error; the API answers 422', 'Low');
    const long = 'a'.repeat(290) + '@verixa.dev';
    const { page } = await open(browser, baseURL!);
    await page.goto('/forgot-password');
    await page.getByLabel('Email').pressSequentially(long.slice(0, 260), { delay: 0 });
    expect((await page.getByLabel('Email').inputValue()).length).toBeLessThanOrEqual(254);
    await page.getByRole('button', { name: 'Send reset link' }).click();
    await expect(page.locator('#emailErr')).toBeVisible();
    const api = await client(baseURL!);
    expect((await api.post('/auth/forgot', { data: { email: long } })).status()).toBe(422);
    await api.dispose();
  });

  test('FP-EM-09 an email with allowed special characters works', async ({ browser, baseURL }) => {
    meta(["Make an account with qa.o'brien+reset_1@verixa.dev", 'Ask for a link'], 'Accepted, and the email arrives', 'Low');
    const email = await account(baseURL!, `qa.o'brien+reset_${unique()}@verixa.dev`);
    const { page } = await open(browser, baseURL!);
    await requestLink(page, email);
    await waitForEmail(email);
  });

  test('FP-EM-10 clicking Send many times quickly sends one request', async ({ browser, baseURL }) => {
    meta(['Enter a registered email', 'Click Send reset link 5 times fast'], 'One request and one email; the button is busy while sending', 'Medium');
    const email = await account(baseURL!);
    const { page } = await open(browser, baseURL!);
    await page.goto('/forgot-password');
    let posts = 0;
    page.on('request', r => { if (r.url().endsWith('/auth/forgot') && r.method() === 'POST') posts++; });
    await page.getByLabel('Email').fill(email);
    const button = page.getByRole('button', { name: 'Send reset link' });
    await Promise.all([1, 2, 3, 4, 5].map(() => button.click({ force: true, noWaitAfter: true }).catch(() => {})));
    await expect(page.getByRole('heading', { name: 'Check your inbox' })).toBeVisible();
    await page.waitForTimeout(500);
    expect(posts).toBe(1);
    expect(inbox(email)).toHaveLength(1);
  });
});

// ---------- 3. Email delivery ----------

test.describe('3. Email delivery', () => {
  test('FP-MAIL-01 the email has the right subject, greeting, link and expiry', async ({ browser, baseURL }) => {
    meta(['Ask for a link', 'Open the test inbox'], 'Subject "Reset your Verixa password", the account name, a /reset-password#token= link, "30 minutes", "works once"', 'High');
    const email = await account(baseURL!);
    const { page } = await open(browser, baseURL!);
    await requestLink(page, email);
    const mail = await waitForEmail(email);
    expect(mail.subject).toBe('Reset your Verixa password');
    expect(mail.text).toContain(`Hi ${NAME},`);
    expect(linkOf(mail.text)).toMatch(/^http:\/\/localhost:8011\/reset-password#token=[\w-]{40,}$/);
    expect(mail.text).toContain('within 30 minutes');
    expect(mail.text).toContain('The link works once');
    expect(mail.text).toContain('If you did not ask for this');
  });

  test('FP-MAIL-02 the link from the email opens the Reset Password page', async ({ browser, baseURL }) => {
    meta(['Ask for a link', 'Open the link from the email'], 'The "Choose a new password" form shows, with no error', 'Critical');
    const email = await account(baseURL!);
    const { path: link } = await linkFor(baseURL!, email);
    const { page } = await open(browser, baseURL!);
    await page.goto(link);
    await expect(page.getByRole('heading', { name: 'Choose a new password' })).toBeVisible();
    await expect(page.getByRole('textbox', { name: /^New password/ })).toBeVisible();
    await expect(page.locator('.banner')).toHaveCount(0);
  });

  test('FP-MAIL-03 delivery to a real mailbox through SMTP', async () => {
    meta(['Set SMTP_HOST in .env', 'Ask for a link', 'Check a real mailbox'], 'The email arrives in a real inbox', 'High');
    test.skip(true, 'BLOCKED: no mail server is set up (SMTP_HOST is empty in .env), so real delivery cannot be checked. The email content is checked through the test inbox instead (FP-MAIL-01).');
  });
});

// ---------- 4. Reset token ----------

test.describe('4. Reset token', () => {
  test('FP-TOK-01 a valid link is accepted', async ({ browser, baseURL }) => {
    meta(['Open a fresh link', 'Set a new password'], 'The password is changed', 'Critical');
    const email = await account(baseURL!);
    const { path: link } = await linkFor(baseURL!, email);
    const { page } = await open(browser, baseURL!);
    await page.goto(link);
    await choose(page, NEW);
    await expect(page.getByRole('heading', { name: 'Password changed' })).toBeVisible();
  });

  test('FP-TOK-02 an expired link is refused by the server', async ({ browser, baseURL }) => {
    meta(['Ask for a link', 'Move its expiry into the past (test database)', 'Open it and set a password'], '"not valid, or it has expired" message; password unchanged', 'Critical');
    const email = await account(baseURL!);
    const { path: link } = await linkFor(baseURL!, email);
    const before = db(email).hash_fingerprint;
    expireLinks(email);
    const { page } = await open(browser, baseURL!);
    await page.goto(link);
    await choose(page, NEW);
    await expect(page.locator('.banner')).toContainText('This reset link is not valid, or it has expired');
    await expect(page.getByRole('link', { name: 'Ask for a new link' })).toBeVisible();
    expect(db(email).hash_fingerprint).toBe(before);
  });

  test('FP-TOK-03 a changed token is refused', async ({ browser, baseURL }) => {
    meta(['Change one character of the token', 'Open it and set a password'], 'Refused; password unchanged; the real link still works', 'Critical');
    const email = await account(baseURL!);
    const { token } = await linkFor(baseURL!, email);
    const tampered = token.slice(0, -1) + (token.endsWith('A') ? 'B' : 'A');
    const before = db(email).hash_fingerprint;
    const { page } = await open(browser, baseURL!);
    await page.goto(`/reset-password#token=${tampered}`);
    await choose(page, NEW);
    await expect(page.locator('.banner')).toContainText('not valid, or it has expired');
    expect(db(email).hash_fingerprint).toBe(before);
    const api = await client(baseURL!);
    expect((await api.post('/auth/reset', { data: { token, password: NEW } })).status()).toBe(200);
    await api.dispose();
  });

  test('FP-TOK-04 the reset page without a token says the link is incomplete', async ({ browser, baseURL }) => {
    meta(['Open /reset-password with no token'], 'A clear message, a way to ask for a new link, and no password form', 'Medium');
    const { page } = await open(browser, baseURL!);
    await page.goto('/reset-password');
    await expect(page.locator('.banner')).toContainText('This reset link is not complete');
    await expect(page.getByRole('textbox', { name: /^New password/ })).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'Ask for a new link' })).toHaveAttribute('href', '/forgot-password');
    const api = await client(baseURL!);
    expect((await api.post('/auth/reset', { data: { token: '', password: NEW } })).status()).toBe(400);
    await api.dispose();
  });

  test('FP-TOK-05 a used link cannot be used again', async ({ browser, baseURL }) => {
    meta(['Reset the password with a link', 'Open the same link again'], 'Second use refused; the first new password stays', 'Critical');
    const email = await account(baseURL!);
    const { path: link } = await linkFor(baseURL!, email);
    const { page } = await open(browser, baseURL!);
    await page.goto(link);
    await choose(page, NEW);
    await expect(page.getByRole('heading', { name: 'Password changed' })).toBeVisible();
    await page.goto('about:blank');
    await page.goto(link);
    await choose(page, 'Another-Pass-2028');
    await expect(page.locator('.banner')).toContainText('not valid, or it has expired');
    expect(await apiLogin(baseURL!, email, NEW)).toBe(200);
  });

  test('FP-TOK-06 asking twice: only the newest link works', async ({ browser, baseURL }) => {
    meta(['Ask for a link twice', 'Try the first, then the second'], 'First refused, second accepted; one link stored', 'High');
    const email = await account(baseURL!);
    const first = await linkFor(baseURL!, email, 1);
    const second = await linkFor(baseURL!, email, 2);
    expect(first.token).not.toBe(second.token);
    expect(db(email).reset_rows).toBe(1);
    const { page } = await open(browser, baseURL!);
    await page.goto(first.path);
    await choose(page, NEW);
    await expect(page.locator('.banner')).toContainText('not valid, or it has expired');
    await page.goto('about:blank');
    await page.goto(second.path);
    await choose(page, NEW);
    await expect(page.getByRole('heading', { name: 'Password changed' })).toBeVisible();
  });

  test('FP-TOK-07 refreshing the reset page', async ({ browser, baseURL }) => {
    meta(['Open a link', 'Reload the page'], 'No crash. The token was removed from the address bar on first load, so after a reload the page says the link is incomplete and offers a new one', 'Low');
    const email = await account(baseURL!);
    const { path: link } = await linkFor(baseURL!, email);
    const { page } = await open(browser, baseURL!);
    await page.goto(link);
    await expect(page.getByRole('textbox', { name: /^New password/ })).toBeVisible();
    await page.reload();
    await expect(page.locator('.banner')).toContainText('This reset link is not complete');
    // The link itself still works from the email
    await page.goto('about:blank');
    await page.goto(link);
    await expect(page.getByRole('textbox', { name: /^New password/ })).toBeVisible();
  });

  test('FP-TOK-08 Back and Forward after a reset do not reopen the form', async ({ browser, baseURL }) => {
    meta(['Open /login, then the link', 'Reset the password', 'Press Back, then Forward'], 'Back shows the login page; Forward shows the reset page without a usable form', 'Medium');
    const email = await account(baseURL!);
    const { path: link } = await linkFor(baseURL!, email);
    const { page } = await open(browser, baseURL!);
    await page.goto('/login');
    await page.goto(link);
    await choose(page, NEW);
    await expect(page.getByRole('heading', { name: 'Password changed' })).toBeVisible();
    await page.goBack();
    await expect(page).toHaveURL(/\/login$/);
    await page.goForward();
    await expect(page).toHaveURL(/\/reset-password$/);
    await expect(page.locator('.banner')).toContainText('not complete');
    await expect(page.getByRole('textbox', { name: /^New password/ })).toHaveCount(0);
  });
});

// ---------- 5. New password ----------

test.describe('5. New password', () => {
  async function onForm(browser: Browser, baseURL: string) {
    const email = await account(baseURL);
    const { path: link, token } = await linkFor(baseURL, email);
    const visit = await open(browser, baseURL);
    await visit.page.goto(link);
    await expect(visit.page.getByRole('textbox', { name: /^New password/ })).toBeVisible();
    return { ...visit, email, token };
  }

  for (const [id, password, why, message] of [
    ['FP-PW-01', '', 'empty', 'Enter a password'],
    ['FP-PW-02', 'password123', 'common, weak', 'too common'],
    ['FP-PW-03', 'ab1cd', 'below the minimum length of 8', 'Use at least 8 characters'],
  ] as const) {
    test(`${id} ${why} password is refused on the page`, async ({ browser, baseURL }) => {
      meta([`Enter "${password}" twice`, 'Click Save new password'], `Message containing "${message}"; nothing sent; password unchanged`, 'High');
      const { page, email } = await onForm(browser, baseURL!);
      const before = db(email).hash_fingerprint;
      let posts = 0;
      page.on('request', r => { if (r.url().endsWith('/auth/reset')) posts++; });
      await choose(page, password);
      await expect(page.locator('#passwordErr')).toContainText(message);
      expect(posts).toBe(0);
      expect(db(email).hash_fingerprint).toBe(before);
    });
  }

  test('FP-PW-04 a password of exactly 8 characters is accepted', async ({ browser, baseURL }) => {
    meta(['Enter "kq7mz2xp" (8 characters) twice', 'Save'], 'Accepted; logging in with it works', 'Medium');
    const { page, email } = await onForm(browser, baseURL!);
    await choose(page, 'kq7mz2xp');
    await expect(page.getByRole('heading', { name: 'Password changed' })).toBeVisible();
    expect(await apiLogin(baseURL!, email, 'kq7mz2xp')).toBe(200);
  });

  test('FP-PW-05 a password over 128 characters is refused', async ({ browser, baseURL }) => {
    meta(['Type 140 characters in the field', 'Send 129 characters straight to the API'], 'The field keeps at most 128; the API answers 422; password unchanged', 'Low');
    const { page, email, token } = await onForm(browser, baseURL!);
    await page.getByRole('textbox', { name: /^New password/ }).pressSequentially('x9'.repeat(70), { delay: 0 });
    expect((await page.getByRole('textbox', { name: /^New password/ }).inputValue()).length).toBe(128);
    const before = db(email).hash_fingerprint;
    const api = await client(baseURL!);
    const res = await api.post('/auth/reset', { data: { token, password: 'x9'.repeat(64) + 'y' } });
    expect(res.status()).toBe(422);
    expect((await res.json()).detail.message).toContain('128');
    await api.dispose();
    expect(db(email).hash_fingerprint).toBe(before);
  });

  test('FP-PW-06 different passwords in the two fields are refused', async ({ browser, baseURL }) => {
    meta(['Enter two different valid passwords', 'Save'], '"The two passwords do not match"; nothing sent', 'High');
    const { page } = await onForm(browser, baseURL!);
    let posts = 0;
    page.on('request', r => { if (r.url().endsWith('/auth/reset')) posts++; });
    await choose(page, NEW, NEW + 'x');
    await expect(page.locator('#againErr')).toHaveText('The two passwords do not match');
    expect(posts).toBe(0);
  });

  test('FP-PW-07 matching valid passwords are accepted', async ({ browser, baseURL }) => {
    meta(['Enter the same strong password twice', 'Save'], '"Password changed" screen', 'Critical');
    const { page } = await onForm(browser, baseURL!);
    await choose(page, NEW);
    await expect(page.getByRole('heading', { name: 'Password changed' })).toBeVisible();
    await expect(page.getByText('Every other session has been signed out')).toBeVisible();
  });

  test('FP-PW-08 Show password reveals and hides the new password', async ({ browser, baseURL }) => {
    meta(['Type a password', 'Click Show password, then Hide password'], 'The field switches between hidden and visible', 'Low');
    const { page } = await onForm(browser, baseURL!);
    const field = page.getByRole('textbox', { name: /^New password/ });
    await field.fill(NEW);
    await expect(field).toHaveAttribute('type', 'password');
    await page.getByRole('button', { name: 'Show password' }).click();
    await expect(field).toHaveAttribute('type', 'text');
    await page.getByRole('button', { name: 'Hide password' }).click();
    await expect(field).toHaveAttribute('type', 'password');
  });

  test('FP-PW-09 the same control reveals the confirm field', async ({ browser, baseURL }) => {
    meta(['Type in Type it again', 'Click Show password'], 'The confirm field becomes visible too, so both can be compared', 'Low');
    const { page } = await onForm(browser, baseURL!);
    const again = page.getByLabel('Type it again');
    await again.fill(NEW);
    await expect(again).toHaveAttribute('type', 'password');
    await page.getByRole('button', { name: 'Show password' }).click();
    await expect(again).toHaveAttribute('type', 'text');
  });

  test('FP-PW-10 a password with special characters works', async ({ browser, baseURL }) => {
    meta(['Set "Qa!@#$%^&*()_+-=[]{};:,.<>/?9 ü" as the password', 'Log in with it'], 'Accepted, and logging in with exactly that text works', 'Medium');
    const special = 'Qa!@#$%^&*()_+-=[]{};:,.<>/?9 ü';
    const { page, email } = await onForm(browser, baseURL!);
    await choose(page, special);
    await expect(page.getByRole('heading', { name: 'Password changed' })).toBeVisible();
    expect(await apiLogin(baseURL!, email, special)).toBe(200);
  });

  test('FP-PW-11 a password containing the account name is refused by the server', async ({ browser, baseURL }) => {
    meta(['Enter "ResetTester2026" (contains the name "Reset Tester")', 'Save'], 'The server refuses it and the page shows "Do not use your name"; the link still works', 'Medium');
    const { page, email, token } = await onForm(browser, baseURL!);
    await choose(page, 'ResetTester2026');
    await expect(page.locator('#passwordErr')).toContainText('Do not use your name');
    expect(db(email, { token }).token_row_found).toBe(true);
  });
});

// ---------- 6. End to end ----------

test.describe('6. End to end', () => {
  test('FP-E2E-01 the whole journey, proved by logging in', async ({ browser, baseURL }) => {
    meta(['Log in page → Forgot password?', 'Send link', 'Open the email link', 'Set a new password', 'Log in with the new password',
          'Log out, log in with the old password', 'Open the link again'],
         'New password logs in to the dashboard; old password is refused; the link is refused the second time', 'Critical');
    const email = await account(baseURL!);
    const { page } = await open(browser, baseURL!);
    await page.goto('/login');
    await page.getByRole('link', { name: 'Forgot password?' }).click();
    await page.getByLabel('Email').fill(email);
    await page.getByRole('button', { name: 'Send reset link' }).click();
    await expect(page.getByRole('heading', { name: 'Check your inbox' })).toBeVisible();
    const link = pathOf(linkOf((await waitForEmail(email)).text));
    await page.goto(link);
    await choose(page, NEW);
    await expect(page.getByRole('heading', { name: 'Password changed' })).toBeVisible();
    await page.getByRole('link', { name: 'Log in' }).last().click();
    await expect(page).toHaveURL(/\/login$/);

    await uiLogin(page, email, NEW);
    await expect(page).toHaveURL(/verixa_prototype\.html/, { timeout: 15_000 });

    expect((await page.request.post('/auth/logout')).status()).toBe(204);
    await uiLogin(page, email, ORIGINAL);
    await expect(page.locator('#passwordErr')).toHaveText('Email or password is incorrect');

    await page.goto('about:blank');
    await page.goto(link);
    await choose(page, 'Third-Pass-2029');
    await expect(page.locator('.banner')).toContainText('not valid, or it has expired');
  });
});

// ---------- 7. Security ----------

test.describe('7. Security', () => {
  test("FP-SEC-01 SQL injection in the email field is refused and changes nothing", async ({ browser, baseURL }) => {
    meta(["Enter ' OR '1'='1 and admin'-- in the email field"], 'Refused as an invalid email; no email sent; no reset row created', 'Critical');
    const { page } = await open(browser, baseURL!);
    for (const payload of ["' OR '1'='1", "admin'--@verixa.dev' OR 1=1--", "x@y.com'; DROP TABLE users;--"]) {
      await page.goto('/forgot-password');
      await page.getByLabel('Email').fill(payload);
      await page.getByRole('button', { name: 'Send reset link' }).click();
      await expect(page.locator('#emailErr')).toBeVisible();
      const api = await client(baseURL!);
      expect((await api.post('/auth/forgot', { data: { email: payload } })).status()).toBe(422);
      await api.dispose();
    }
    // The users table is still there and still works
    const email = await account(baseURL!);
    expect(await apiLogin(baseURL!, email, ORIGINAL)).toBe(200);
  });

  test('FP-SEC-02 SQL injection in the password field is stored as plain text, safely', async ({ browser, baseURL }) => {
    meta(["Set the new password to x' OR '1'='1' --9", 'Log in with it; check another account'], 'Saved as an ordinary password: logging in needs exactly that text; another account is untouched', 'Critical');
    const other = await account(baseURL!);
    const otherBefore = db(other);
    const email = await account(baseURL!);
    const { path: link } = await linkFor(baseURL!, email);
    const { page } = await open(browser, baseURL!);
    await page.goto(link);
    const payload = "x' OR '1'='1' --9";
    await choose(page, payload);
    await expect(page.getByRole('heading', { name: 'Password changed' })).toBeVisible();
    expect(await apiLogin(baseURL!, email, payload)).toBe(200);
    expect(await apiLogin(baseURL!, email, "' OR '1'='1")).toBe(401);
    const otherAfter = db(other);
    expect([otherAfter.hash_fingerprint, otherAfter.session_version]).toEqual([otherBefore.hash_fingerprint, otherBefore.session_version]);
  });

  test('FP-SEC-03 script in the fields never runs', async ({ browser, baseURL }) => {
    meta(['Enter <script>alert(1)</script> in the email field', 'Enter <img src=x onerror=alert(1)>9a as a new password'], 'No alert appears; the email is refused; the password is stored as text', 'Critical');
    const { page, problems } = await open(browser, baseURL!);
    await page.goto('/forgot-password');
    await page.getByLabel('Email').fill('<script>alert(1)</script>');
    await page.getByRole('button', { name: 'Send reset link' }).click();
    await expect(page.locator('#emailErr')).toBeVisible();
    const email = await account(baseURL!);
    const { path: link } = await linkFor(baseURL!, email);
    await page.goto(link);
    const xss = '<img src=x onerror=alert(1)>9a';
    await choose(page, xss);
    await expect(page.getByRole('heading', { name: 'Password changed' })).toBeVisible();
    expect(await apiLogin(baseURL!, email, xss)).toBe(200);
    expect(problems.filter(p => p.startsWith('alert'))).toEqual([]);
  });

  test('FP-SEC-04 guessing tokens is slowed down', async ({ baseURL }) => {
    meta(['Send 20 made-up tokens from one address', 'Send one more'], 'All refused with 400, then 429 with Retry-After', 'High');
    const api = await client(baseURL!);
    for (let i = 0; i < 20; i++) {
      expect((await api.post('/auth/reset', { data: { token: `guess-${i}-${'z'.repeat(40)}`, password: NEW } })).status()).toBe(400);
    }
    const blocked = await api.post('/auth/reset', { data: { token: 'guess-final-' + 'z'.repeat(40), password: NEW } });
    expect(blocked.status()).toBe(429);
    expect(blocked.headers()['retry-after']).toBeTruthy();
    await api.dispose();
  });

  test("FP-SEC-05 a link only ever changes its own account's password", async ({ baseURL }) => {
    meta(["Get a link for account A", "Use it while naming account B's email", 'Check B'], "Only A changes; there is no way to name another account; B logs in with its old password", 'Critical');
    const a = await account(baseURL!), b = await account(baseURL!);
    const bBefore = db(b);
    const { token } = await linkFor(baseURL!, a);
    const api = await client(baseURL!);
    expect((await api.post('/auth/reset', { data: { token, password: NEW, email: b, user_id: 1 } })).status()).toBe(200);
    expect((await api.post('/auth/reset', { data: { email: b, password: NEW } })).status()).toBe(400);
    await api.dispose();
    expect(await apiLogin(baseURL!, a, NEW)).toBe(200);
    expect(await apiLogin(baseURL!, b, ORIGINAL)).toBe(200);
    expect(db(b).hash_fingerprint).toBe(bBefore.hash_fingerprint);
  });

  test('FP-SEC-06 repeated requests for one email are limited', async ({ browser, baseURL }) => {
    meta(['Ask for a link for one email 4 times in an hour'], 'The first 3 send an email; the 4th is refused with 429 and the page shows a countdown', 'High');
    const email = await account(baseURL!);
    for (let i = 0; i < 3; i++) {
      const api = await client(baseURL!);
      expect((await api.post('/auth/forgot', { data: { email } })).status()).toBe(202);
      await api.dispose();
    }
    const { page } = await open(browser, baseURL!);
    await page.goto('/forgot-password');
    await page.getByLabel('Email').fill(email);
    await page.getByRole('button', { name: 'Send reset link' }).click();
    await expect(page.locator('.banner')).toContainText('Too many attempts');
    await expect(page.getByRole('button', { name: 'Send reset link' })).toBeDisabled();
    await page.waitForTimeout(300);
    expect(inbox(email)).toHaveLength(3);
  });

  test('FP-SEC-07 the token is not sent to the server log or kept in the address bar', async ({ browser, baseURL }) => {
    meta(['Open a reset link', 'Watch every request the page makes', 'Read the address bar and history'], 'The token never appears in a request URL or a Referer, and is removed from the address bar on load', 'High');
    const email = await account(baseURL!);
    const { path: link, token } = await linkFor(baseURL!, email);
    const { page } = await open(browser, baseURL!);
    const leaks: string[] = [];
    page.on('request', r => {
      if (r.url().includes(token) || (r.headers()['referer'] ?? '').includes(token)) leaks.push(r.url());
    });
    await page.goto(link);
    await expect(page.getByRole('textbox', { name: /^New password/ })).toBeVisible();
    expect(page.url()).not.toContain(token);
    expect(await page.evaluate(() => location.hash)).toBe('');
    await choose(page, NEW);
    await expect(page.getByRole('heading', { name: 'Password changed' })).toBeVisible();
    expect(leaks).toEqual([]);
  });

  test('FP-SEC-08 reset links use the public address, which is HTTPS for the real site', async ({ baseURL }) => {
    meta(['Read the link in the email', "Read the scheme of PUBLIC_URL in the real .env (only the scheme)"], 'The link is built from PUBLIC_URL; the real site uses https://', 'Medium');
    const email = await account(baseURL!);
    await linkFor(baseURL!, email);
    expect(linkOf((await waitForEmail(email)).text).startsWith('http://localhost:8011/')).toBe(true);  // the tests' own PUBLIC_URL
    const env = path.resolve(__dirname, '../../.env');
    test.skip(!fs.existsSync(env), 'No .env on this computer to check the real address');
    const scheme = /^PUBLIC_URL\s*=\s*"?(\w+):/m.exec(fs.readFileSync(env, 'utf-8'))?.[1];
    expect(scheme).toBe('https');
  });

  test('FP-SEC-09 forms posted from another website are refused', async ({ baseURL }) => {
    meta(['POST /auth/forgot and /auth/reset with Origin https://evil.example'], 'Both refused with 403; no email sent; password unchanged', 'High');
    const email = await account(baseURL!);
    const { token } = await linkFor(baseURL!, email);
    const before = db(email).hash_fingerprint;
    const api = await client(baseURL!);
    const evil = { origin: 'https://evil.example' };
    expect((await api.post('/auth/forgot', { data: { email }, headers: evil })).status()).toBe(403);
    expect((await api.post('/auth/reset', { data: { token, password: NEW }, headers: evil })).status()).toBe(403);
    await api.dispose();
    expect(inbox(email)).toHaveLength(1);
    expect(db(email).hash_fingerprint).toBe(before);
  });

  test('FP-SEC-10 a reset signs out every other session', async ({ browser, baseURL }) => {
    meta(['Log in on browser A', 'Reset the password on browser B', 'Use browser A again'], 'Browser A is signed out and sent to the login page', 'Critical');
    const email = await account(baseURL!);
    const a = await visitor(browser, baseURL!);
    await uiLogin(a.page, email, ORIGINAL);
    await expect(a.page).toHaveURL(/verixa_prototype\.html/, { timeout: 15_000 });
    const versionBefore = db(email).session_version;

    const { path: link } = await linkFor(baseURL!, email);
    const { page } = await open(browser, baseURL!);
    await page.goto(link);
    await choose(page, NEW);
    await expect(page.getByRole('heading', { name: 'Password changed' })).toBeVisible();

    expect((await (await a.page.request.get('/api/session')).json()).account ?? null).toBeNull();
    await a.page.goto('/verixa_prototype.html');
    await expect(a.page).toHaveURL(/\/login/);
    expect(db(email).session_version).toBeGreaterThan(versionBefore);
    await a.context.close();
  });

  test('FP-SEC-11 reset pages and answers are never cached', async ({ baseURL }) => {
    meta(['Load /forgot-password and /reset-password', 'Send a bad reset'], 'Cache-Control: no-store on the pages and on the refusal', 'Low');
    const api = await client(baseURL!);
    for (const page of ['/forgot-password', '/reset-password']) {
      expect((await api.get(page)).headers()['cache-control']).toBe('no-store');
    }
    expect((await api.post('/auth/reset', { data: { token: 'nope-' + 'q'.repeat(40), password: NEW } })).headers()['cache-control']).toBe('no-store');
    await api.dispose();
  });
});

// ---------- 8. Database (read-only checks) ----------

test.describe('8. Database', () => {
  test('FP-DB-01 a request stores one link, as a hash only', async ({ baseURL }) => {
    meta(['Ask for a link', 'Read the password_resets table'], 'One row for the account; it holds the SHA-256 of the token, never the token', 'Critical');
    const email = await account(baseURL!);
    const { token } = await linkFor(baseURL!, email);
    const facts = db(email, { token });
    expect(facts.reset_rows).toBe(1);
    expect(facts.reset_rows_detail[0].stored_as_sha256_hex).toBe(true);
    expect(facts.token_row_found).toBe(true);
    expect(facts.raw_token_stored).toBe(false);
  });

  test('FP-DB-02 the link expires 30 minutes after it is made', async ({ baseURL }) => {
    meta(['Ask for a link', 'Read its expiry'], 'expires_at is 30 minutes after created_at, and about 30 minutes from now', 'High');
    const email = await account(baseURL!);
    await linkFor(baseURL!, email);
    const [row] = db(email).reset_rows_detail;
    expect(row.lifetime_minutes).toBeCloseTo(30, 0);
    expect(row.minutes_left).toBeGreaterThan(29);
    expect(row.minutes_left).toBeLessThanOrEqual(30);
  });

  test('FP-DB-03 a used link is deleted', async ({ baseURL }) => {
    meta(['Reset the password', 'Read the table'], 'No link left for the account', 'Critical');
    const email = await account(baseURL!);
    const { token } = await linkFor(baseURL!, email);
    const api = await client(baseURL!);
    expect((await api.post('/auth/reset', { data: { token, password: NEW } })).status()).toBe(200);
    await api.dispose();
    expect(db(email, { token }).reset_rows).toBe(0);
  });

  test('FP-DB-04 the password hash changes after a reset, and stays scrypt', async ({ baseURL }) => {
    meta(['Fingerprint the hash', 'Reset', 'Fingerprint again'], 'Different fingerprint; still an scrypt hash; the session version goes up', 'Critical');
    const email = await account(baseURL!);
    const before = db(email);
    const { token } = await linkFor(baseURL!, email);
    const api = await client(baseURL!);
    expect((await api.post('/auth/reset', { data: { token, password: NEW } })).status()).toBe(200);
    await api.dispose();
    const after = db(email);
    expect(after.hash_fingerprint).not.toBe(before.hash_fingerprint);
    expect(after.hash_is_scrypt).toBe(true);
    expect(after.session_version).toBe(before.session_version + 1);
  });

  test('FP-DB-05 the new password is never stored as plain text', async ({ baseURL }) => {
    meta(['Reset to a known password', 'Search the user row for it'], 'The password text is nowhere in the row', 'Critical');
    const email = await account(baseURL!);
    const { token } = await linkFor(baseURL!, email);
    const api = await client(baseURL!);
    expect((await api.post('/auth/reset', { data: { token, password: NEW } })).status()).toBe(200);
    await api.dispose();
    expect(db(email, { password: NEW }).password_in_plain_text).toBe(false);
  });

  test('FP-DB-06 a refused new password changes nothing', async ({ baseURL }) => {
    meta(['Send a weak password with a valid link'], 'Hash, session version and the link all unchanged', 'High');
    const email = await account(baseURL!);
    const { token } = await linkFor(baseURL!, email);
    const before = db(email, { token });
    const api = await client(baseURL!);
    expect((await api.post('/auth/reset', { data: { token, password: 'password123' } })).status()).toBe(422);
    await api.dispose();
    const after = db(email, { token });
    expect([after.hash_fingerprint, after.session_version, after.token_row_found]).toEqual([before.hash_fingerprint, before.session_version, true]);
  });

  test('FP-DB-07 a bad token changes no account', async ({ baseURL }) => {
    meta(['Send a made-up token'], 'No user row changes; no link is removed', 'High');
    const email = await account(baseURL!);
    const { token } = await linkFor(baseURL!, email);
    const before = db(email, { token });
    const api = await client(baseURL!);
    expect((await api.post('/auth/reset', { data: { token: token.split('').reverse().join(''), password: NEW } })).status()).toBe(400);
    await api.dispose();
    const after = db(email, { token });
    expect([after.hash_fingerprint, after.session_version, after.reset_rows]).toEqual([before.hash_fingerprint, before.session_version, 1]);
  });

  test('FP-DB-08 many requests leave exactly one link', async ({ baseURL }) => {
    meta(['Ask for a link 3 times'], 'Exactly one row for the account, matching the newest email', 'High');
    const email = await account(baseURL!);
    for (let i = 1; i <= 3; i++) await linkFor(baseURL!, email, i);
    const newest = tokenOf(inbox(email)[2].text);
    const facts = db(email, { token: newest });
    expect(facts.reset_rows).toBe(1);
    expect(facts.token_row_found).toBe(true);
  });

  test("FP-DB-09 only the intended account is updated", async ({ baseURL }) => {
    meta(['Make accounts A and B, both with links', "Reset A's password"], "A changes; B's hash, session version and link are untouched", 'Critical');
    const a = await account(baseURL!), b = await account(baseURL!);
    const { token } = await linkFor(baseURL!, a);
    const { token: bToken } = await linkFor(baseURL!, b);
    const bBefore = db(b, { token: bToken });
    const api = await client(baseURL!);
    expect((await api.post('/auth/reset', { data: { token, password: NEW } })).status()).toBe(200);
    await api.dispose();
    const bAfter = db(b, { token: bToken });
    expect([bAfter.hash_fingerprint, bAfter.session_version, bAfter.token_row_found])
      .toEqual([bBefore.hash_fingerprint, bBefore.session_version, true]);
  });
});
