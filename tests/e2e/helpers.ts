import { expect, type Browser, type BrowserContext, type Page } from '@playwright/test';
import os from 'node:os';
import path from 'node:path';

export const PASSWORD = 'Verixa-Demo-2026';
const sessions = new Map<string, Awaited<ReturnType<ReturnType<Browser['newContext']> extends Promise<infer C> ? C['storageState'] : never>>>();

/** A page signed in through the real login form. Logs in once per account, so the login rate limit is not what gets tested. */
export async function signIn(browser: Browser, email: string, baseURL: string): Promise<{ page: Page; problems: string[] }> {
  if (!sessions.has(email)) {
    const context = await browser.newContext({ baseURL });
    const page = await context.newPage();
    await page.goto('/login');
    await page.waitForLoadState('networkidle');
    // The form can still be starting up after the page has loaded, so it is tried again until a login really goes through
    await expect(async () => {
      await page.locator('#email').fill(email);
      await page.locator('#password').fill(PASSWORD);
      await page.locator('button.submit').click();
      await page.waitForURL('**/verixa_prototype.html**', { timeout: 3_000 });
    }).toPass({ timeout: 20_000 });
    sessions.set(email, await context.storageState());
    await context.close();
  }
  const context = await browser.newContext({ baseURL, storageState: sessions.get(email) });
  opened.push(context);
  const page = await context.newPage();
  const problems = watch(page);
  return { page, problems };
}

const opened: BrowserContext[] = [];

/** Closes the pages of a finished test, because a page left open keeps polling the server. */
export async function closePages() {
  await Promise.all(opened.splice(0).map(context => context.close()));
}

/** Records anything a user should never see: an alert from injected script, a page error or a blocked resource. */
export function watch(page: Page): string[] {
  const problems: string[] = [];
  page.on('dialog', dialog => { problems.push('alert: ' + dialog.message()); dialog.dismiss(); });
  page.on('pageerror', error => problems.push('page error: ' + error.message));
  page.on('console', message => {
    const text = message.text();
    // Web fonts come from Google, which the test machine may not reach. An expected 4xx or 5xx is the test's own doing.
    if (message.type() === 'error' && !/fonts\.g|Failed to load resource/.test(text)) problems.push('console: ' + text);
    if (/Content Security Policy/i.test(text)) problems.push('blocked by the page policy: ' + text);
  });
  return problems;
}

export async function openRisk(page: Page) {
  await page.goto('/verixa_prototype.html#risk');
  await expect(page.getByRole('heading', { name: 'Risk Analysis' })).toBeVisible({ timeout: 15_000 });
}

export const rowOf = (page: Page, number: number) => page.locator('tr.risk-row', { hasText: `#${number}` }).filter({
  has: page.locator(`.rpr-title b:text-is("#${number}")`),
});

/** The expanded details of a row. Details always sit in the row right after it, inside the same tbody. */
export const detailOf = (page: Page, number: number) =>
  page.locator('tbody', { has: rowOf(page, number) }).locator('.rdetail');

export async function analyse(page: Page, number: number) {
  await page.getByLabel('Pull request number').fill(String(number));
  await page.getByRole('button', { name: 'Analyse now' }).click();
}

export async function feed(page: Page) {
  const response = await page.request.get('/api/analysis/pull-requests');
  expect(response.status()).toBe(200);
  return response.json();
}

export const tracePath = (name: string) => path.join(os.tmpdir(), `${name}-trace.jsonl`);
