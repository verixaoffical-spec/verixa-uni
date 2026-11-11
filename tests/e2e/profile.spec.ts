/**
 * Profile page, end to end in a real browser against the real app (tests/e2e/server.py, port 8011):
 * changing the name, and deleting the account. Every test makes its own verified account with a unique email
 * and its own X-Forwarded-For address. The database is read through a read-only query that never prints a hash.
 */
import { expect, request as playwrightRequest, test, type Browser, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const PYTHON = path.resolve(__dirname, '../../.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const INBOX = path.join(os.tmpdir(), 'verixa-e2e-mail.jsonl');
const PASSWORD = 'Profile-Pass-2026';
const NAME = 'Profile Tester';

let seq = 0;
const octet = () => Math.floor(Math.random() * 250) + 1;
const address = () => `${octet()}.${octet()}.${octet()}.${octet()}`;
const unique = () => `${Date.now().toString(36)}${(seq++).toString(36)}${Math.random().toString(36).slice(2, 6)}`;

function meta(steps: string[], expected: string, severity: 'Critical' | 'High' | 'Medium' | 'Low') {
  test.info().annotations.push({ type: 'steps', description: steps.join(' → ') },
                               { type: 'expected', description: expected }, { type: 'severity', description: severity });
}

/** Read-only facts about one account in the tests' own SQLite file. */
function db(email: string): { exists: boolean; name: string | null } {
  const script = [
    'import json, os, sqlite3, sys, tempfile',
    'db = sqlite3.connect("file:" + os.path.join(tempfile.gettempdir(), "verixa-e2e.db").replace(os.sep, "/") + "?mode=ro", uri=True)',
    'row = db.execute("SELECT name FROM users WHERE email = ?", (sys.argv[1],)).fetchone()',
    'print(json.dumps({"exists": bool(row), "name": row[0] if row else None}))',
  ].join('\n');
  return JSON.parse(execFileSync(PYTHON, ['-c', script, email], { encoding: 'utf-8' }));
}

/** A new, verified account made through the real sign up and verification API. */
async function account(baseURL: string): Promise<string> {
  const email = `pf-${unique()}@verixa.dev`;
  const api = await playwrightRequest.newContext({ baseURL, extraHTTPHeaders: { 'x-forwarded-for': address() } });
  expect((await api.post('/auth/signup', { data: { name: NAME, email, password: PASSWORD } })).status()).toBe(202);
  await expect.poll(() => fs.existsSync(INBOX) && fs.readFileSync(INBOX, 'utf-8').includes(`"to": "${email}"`), { timeout: 10_000 }).toBe(true);
  const mail = fs.readFileSync(INBOX, 'utf-8').split('\n').filter(Boolean).map(l => JSON.parse(l)).filter(m => m.to === email).at(-1);
  const token = /#token=([\w-]+)/.exec(mail.text)![1];
  expect((await api.post('/auth/verify-email', { data: { token } })).status()).toBe(200);
  await api.dispose();
  return email;
}

/** Logs in through the real form and opens the Profile page from the account menu. */
async function openProfile(browser: Browser, baseURL: string, email: string) {
  const context = await browser.newContext({ baseURL, extraHTTPHeaders: { 'x-forwarded-for': address() } });
  const page = await context.newPage();
  const problems: string[] = [];
  page.on('pageerror', e => problems.push('page error: ' + e.message));
  page.on('dialog', d => { problems.push('alert: ' + d.message()); d.dismiss(); });
  await page.goto('/login');
  await page.waitForFunction(() => document.body.classList.contains('ready') && !document.querySelector('.glass')?.inert);
  await page.getByLabel('Email').fill(email);
  await page.getByRole('textbox', { name: /^Password/ }).fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.waitForURL('**/verixa_prototype.html**');
  await page.getByRole('button', { name: /^Account/ }).click();
  await page.getByRole('menuitem', { name: 'Profile' }).click();
  await expect(page.getByRole('heading', { name: 'Your profile' })).toBeVisible();
  return { page, context, problems };
}

const nameBox = (page: Page) => page.getByRole('textbox', { name: 'Full name' });
const profile = (page: Page) => page.locator('section.workspace.security:not([hidden])');

test.describe('1. Name', () => {
  test('PF-NAME-01 the profile shows the saved name and email', async ({ browser, baseURL }) => {
    meta(['Log in', 'Open Profile from the account menu'], 'The name and email are shown', 'High');
    const email = await account(baseURL!);
    const { page, context, problems } = await openProfile(browser, baseURL!, email);
    await expect(nameBox(page)).toHaveValue(NAME);
    await expect(profile(page).getByText(email).first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Save name' })).toBeDisabled();  // nothing changed yet
    expect(page.url()).toContain('#profile');
    expect(problems).toEqual([]);
    await context.close();
  });

  test('PF-NAME-02 a new name is saved and shown everywhere', async ({ browser, baseURL }) => {
    meta(['Type "  Grace   Hopper "', 'Save name'], 'Saved as "Grace Hopper" in the database and the account menu', 'Critical');
    const email = await account(baseURL!);
    const { page, context } = await openProfile(browser, baseURL!, email);
    await nameBox(page).fill('  Grace   Hopper ');
    await page.getByRole('button', { name: 'Save name' }).click();
    await expect(page.getByText('Your name is saved')).toBeVisible();
    await expect(nameBox(page)).toHaveValue('Grace Hopper');
    expect(db(email).name).toBe('Grace Hopper');
    await expect(page.getByRole('button', { name: 'Account: Grace Hopper' })).toBeVisible();
    await page.reload();
    await expect(nameBox(page)).toHaveValue('Grace Hopper');  // still there after a reload
    await context.close();
  });

  test('PF-NAME-03 names at the edges: 2 and 50 characters are saved', async ({ browser, baseURL }) => {
    meta(['Save "Al"', 'Save 50 letters'], 'Both saved', 'High');
    const email = await account(baseURL!);
    const { page, context } = await openProfile(browser, baseURL!, email);
    for (const name of ['Al', 'B'.repeat(50)]) {
      await nameBox(page).fill(name);
      await page.getByRole('button', { name: 'Save name' }).click();
      await expect.poll(() => db(email).name).toBe(name);
    }
    await context.close();
  });

  test('PF-NAME-04 the field stops at 50 characters', async ({ browser, baseURL }) => {
    meta(['Type 70 letters'], 'Only 50 are kept', 'Medium');
    const email = await account(baseURL!);
    const { page, context } = await openProfile(browser, baseURL!, email);
    await nameBox(page).fill('');
    await nameBox(page).pressSequentially('C'.repeat(70));
    expect((await nameBox(page).inputValue()).length).toBe(50);
    await context.close();
  });

  test('PF-NAME-05 bad names are refused and nothing changes', async ({ browser, baseURL }) => {
    meta(['Try an empty, 1-letter and garbage name', 'Save name'], 'An error each time, the saved name unchanged', 'High');
    const email = await account(baseURL!);
    const { page, context, problems } = await openProfile(browser, baseURL!, email);
    const cases: [string, string][] = [
      ['', 'Enter your name'], ['   ', 'Enter your name'], ['A', 'Use at least 2 characters'],
      ['123', 'Use letters, spaces and simple punctuation only'], ['<script>alert(1)</script>', 'Use letters, spaces and simple punctuation only'],
      ["Robert'); DROP TABLE users;--", 'Use letters, spaces and simple punctuation only'], ['😀😀', 'Use letters, spaces and simple punctuation only'],
    ];
    for (const [name, message] of cases) {
      await nameBox(page).fill(name);
      await page.getByRole('button', { name: 'Save name' }).click();
      await expect(page.locator('#nameErr'), JSON.stringify(name)).toHaveText(message);
    }
    expect(db(email).name).toBe(NAME);
    expect(problems).toEqual([]);
    await context.close();
  });

  test('PF-NAME-06 the server refuses bad names even without the page', async ({ browser, baseURL }) => {
    meta(['POST bad names to /api/account/name with a signed in session'], '422 on the name field, name unchanged', 'High');
    const email = await account(baseURL!);
    const { page, context } = await openProfile(browser, baseURL!, email);
    for (const name of ['', 'A', 'A'.repeat(51), '123', '<b>x</b>', 'x'.repeat(600)]) {
      const res = await page.request.post('/api/account/name', { data: { name } });
      expect(res.status(), name).toBe(422);
    }
    expect(db(email).name).toBe(NAME);
    await context.close();
  });

  test('PF-NAME-07 Cancel puts the saved name back', async ({ browser, baseURL }) => {
    meta(['Type a new name', 'Cancel'], 'The saved name is shown again, nothing saved', 'Low');
    const email = await account(baseURL!);
    const { page, context } = await openProfile(browser, baseURL!, email);
    await nameBox(page).fill('Someone Else');
    await profile(page).getByRole('button', { name: 'Cancel' }).click();
    await expect(nameBox(page)).toHaveValue(NAME);
    expect(db(email).name).toBe(NAME);
    await context.close();
  });

  test('PF-NAME-08 renaming needs a signed in session', async ({ baseURL }) => {
    meta(['POST /api/account/name with no session'], '401', 'Critical');
    const api = await playwrightRequest.newContext({ baseURL });
    expect((await api.post('/api/account/name', { data: { name: 'Hacker' } })).status()).toBe(401);
    await api.dispose();
  });
});

test.describe('2. Delete account', () => {
  test('PF-DEL-01 the delete button stays off until DELETE is typed', async ({ browser, baseURL }) => {
    meta(['Delete my account', 'Enter the password', 'Type "delete" in lower case'], 'The final button stays disabled', 'High');
    const email = await account(baseURL!);
    const { page, context } = await openProfile(browser, baseURL!, email);
    await page.getByRole('button', { name: 'Delete my account', exact: true }).click();
    await page.getByLabel('Password').fill(PASSWORD);
    const final = page.getByRole('button', { name: 'Delete my account forever' });
    await expect(final).toBeDisabled();
    await page.getByLabel('Type DELETE to confirm').fill('delete');
    await expect(final).toBeDisabled();
    await page.getByLabel('Type DELETE to confirm').fill('DELETE');
    await expect(final).toBeEnabled();
    await profile(page).getByRole('button', { name: 'Cancel' }).click();
    await expect(final).toHaveCount(0);
    expect(db(email).exists).toBe(true);
    await context.close();
  });

  test('PF-DEL-02 a wrong or missing password keeps the account', async ({ browser, baseURL }) => {
    meta(['Delete my account', 'No password, then a wrong one', 'Type DELETE'], 'An error each time, the account still exists', 'Critical');
    const email = await account(baseURL!);
    const { page, context } = await openProfile(browser, baseURL!, email);
    await page.getByRole('button', { name: 'Delete my account', exact: true }).click();
    await page.getByLabel('Type DELETE to confirm').fill('DELETE');
    await page.getByRole('button', { name: 'Delete my account forever' }).click();
    await expect(page.locator('#passwordErr')).toHaveText('Enter your password');
    await page.getByLabel('Password').fill('Wrong-Pass-2026');
    await page.getByRole('button', { name: 'Delete my account forever' }).click();
    await expect(page.locator('#passwordErr')).toHaveText('That password is not correct');
    expect(db(email).exists).toBe(true);
    await context.close();
  });

  test('PF-DEL-03 deleting removes the account and signs out', async ({ browser, baseURL }) => {
    meta(['Delete my account', 'Password', 'Type DELETE', 'Delete my account forever'],
         'Login page says it is deleted, the user is gone from the database, logging in fails', 'Critical');
    const email = await account(baseURL!);
    const { page, context, problems } = await openProfile(browser, baseURL!, email);
    await page.getByRole('button', { name: 'Delete my account', exact: true }).click();
    await page.getByLabel('Password').fill(PASSWORD);
    await page.getByLabel('Type DELETE to confirm').fill('DELETE');
    await page.getByRole('button', { name: 'Delete my account forever' }).click();
    await page.waitForURL('**/login**');
    await expect(page.getByText('Your account and all its data have been deleted.')).toBeVisible();
    expect(db(email).exists).toBe(false);

    await page.goto('/verixa_prototype.html#profile');  // the old session no longer opens the dashboard
    await page.waitForURL('**/login**');
    const api = await playwrightRequest.newContext({ baseURL, extraHTTPHeaders: { 'x-forwarded-for': address() } });
    expect((await api.post('/auth/login', { data: { email, password: PASSWORD } })).status()).toBe(401);
    await api.dispose();
    expect(problems).toEqual([]);
    await context.close();
  });

  test('PF-DEL-04 the same email can sign up again after deleting', async ({ browser, baseURL }) => {
    meta(['Delete the account through the API', 'Sign up again with the same email'], '202, a new verification email', 'Medium');
    const email = await account(baseURL!);
    const { page, context } = await openProfile(browser, baseURL!, email);
    expect((await page.request.post('/api/account/delete', { data: { password: PASSWORD } })).status()).toBe(204);
    await context.close();
    const api = await playwrightRequest.newContext({ baseURL, extraHTTPHeaders: { 'x-forwarded-for': address() } });
    expect((await api.post('/auth/signup', { data: { name: NAME, email, password: PASSWORD } })).status()).toBe(202);
    await api.dispose();
  });

  test('PF-DEL-05 deleting needs a signed in session and the same site', async ({ browser, baseURL }) => {
    meta(['POST /api/account/delete with no session', 'Then from another website'], '401, then 403, account kept', 'Critical');
    const email = await account(baseURL!);
    const anonymous = await playwrightRequest.newContext({ baseURL });
    expect((await anonymous.post('/api/account/delete', { data: { password: PASSWORD } })).status()).toBe(401);
    await anonymous.dispose();
    const { page, context } = await openProfile(browser, baseURL!, email);
    const res = await page.request.post('/api/account/delete', { data: { password: PASSWORD }, headers: { origin: 'https://evil.example' } });
    expect(res.status()).toBe(403);
    expect(db(email).exists).toBe(true);
    await context.close();
  });
});

test.describe('3. Layout', () => {
  test('PF-UI-01 the account menu opens above the sticky bottom bars', async ({ browser, baseURL }) => {
    meta(['Open Integrations, then the Test Library', 'Open the account menu on each'],
         'Every menu item is on top and can be clicked, not hidden under the action bar', 'High');
    const email = await account(baseURL!);
    const { page, context } = await openProfile(browser, baseURL!, email);
    for (const view of ['connect', 'library', 'risk', 'security', 'profile']) {
      await page.goto(`/verixa_prototype.html#${view}`);
      await page.waitForTimeout(600);
      await page.getByRole('button', { name: /^Account/ }).click();
      const covered = await page.evaluate(() => [...document.querySelectorAll('.acct-item')].filter(item => {
        const r = item.getBoundingClientRect();
        const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return !hit || !item.contains(hit);
      }).map(item => item.textContent!.trim()));
      expect(covered, view).toEqual([]);
      await page.keyboard.press('Escape');
    }
    await context.close();
  });

  test('PF-UI-02 on a phone nothing scrolls sideways and the top bar keeps its height', async ({ browser, baseURL }) => {
    meta(['Open every dashboard page at 390 px wide'], 'No sideways scrolling, top bar under 80 px tall', 'Medium');
    const email = await account(baseURL!);
    const { page, context } = await openProfile(browser, baseURL!, email);
    await page.setViewportSize({ width: 390, height: 844 });
    for (const view of ['connect', 'library', 'risk', 'security', 'profile']) {
      await page.goto(`/verixa_prototype.html#${view}`);
      await page.waitForTimeout(600);
      expect(await page.evaluate(() => document.scrollingElement!.scrollWidth - innerWidth), view).toBeLessThanOrEqual(1);
      expect((await page.locator('.rail').boundingBox())!.height, view).toBeLessThan(80);
    }
    await context.close();
  });
});
