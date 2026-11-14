/**
 * UC4 to UC11 as a tester uses them, in a real browser, against the real app, real Playwright and Newman and a real
 * staging app (tests/e2e/server.py). Only the model and Jira are scripted. One account goes through the whole loop in
 * order: staging address, Run Now, results and proof, ticket, fix, drafted test, second run, comparison, trends, memory.
 */
import { expect, test, type Page } from '@playwright/test';
import { closePages, openRisk, signIn } from './helpers';

const DEMO = 'demo@verixa.dev';
const OTHER = 'other@verixa.dev';
const STAGING = 'http://127.0.0.1:8013';

test.describe.configure({ mode: 'serial' });
let page: Page;
let problems: string[] = [];

test.beforeEach(async ({ browser, baseURL }) => {
  ({ page, problems } = await signIn(browser, DEMO, baseURL!));
  page.removeAllListeners('dialog');  // this flow answers its own confirm questions
  page.on('dialog', dialog => dialog.message().includes('alert') || dialog.type() === 'alert'
    ? (problems.push('alert: ' + dialog.message()), dialog.dismiss()) : dialog.accept());
});

test.afterEach(async () => {
  await closePages();
  expect(problems, 'no alert, page error or blocked resource').toEqual([]);
});

const toast = (p: Page) => p.locator('.toast.on');

async function waitForRun(p: Page) {
  await expect(p.locator('.qsummary .qtag')).not.toHaveText(/Running/, { timeout: 90_000 });
}

test('UC4 without a staging address Run Now explains what to do', async () => {
  await openRisk(page);
  await page.locator('tr.risk-row', { hasText: '#1' }).first().getByRole('button', { name: 'Run Now' }).click();
  await expect(toast(page)).toContainText('staging address');
  await expect(toast(page).getByRole('button', { name: 'Open Integrations' })).toBeVisible();
});

test('UC4 the staging address refuses bad input and accepts a real one', async () => {
  await page.goto('/verixa_prototype.html#connect');
  await expect(page.getByText('demo/shop is linked to QA Board (QA)')).toBeVisible();
  const box = page.getByPlaceholder('https://staging.example.com');
  const save = page.getByRole('button', { name: /staging address/ });
  await expect(save).toBeDisabled();                       // empty
  await box.fill('ftp://files.example');
  await save.click();
  await expect(page.getByRole('status').filter({ hasText: 'http:// or https://' })).toBeVisible();
  await box.fill('http://169.254.169.254/latest');         // cloud metadata: refused by the server
  await save.click();
  await expect(page.getByRole('status').filter({ hasText: 'not allowed' })).toBeVisible();
  await box.fill(STAGING + '/');
  await box.press('Enter');
  await expect(page.getByRole('status').filter({ hasText: 'answered' })).toBeVisible();
  await expect(save).toBeDisabled();                       // nothing changed since saving
});

test('UC3 and UC4 High risk is listed first, and Run Now opens the run with live progress', async () => {
  await openRisk(page);
  const labels = await page.locator('tr.risk-row .rbadge').allInnerTexts();
  const rank = (l: string) => (l.includes('High') ? 0 : l.includes('Medium') ? 1 : l.includes('Low') ? 2 : 3);
  expect(labels.map(rank)).toEqual([...labels.map(rank)].sort());
  await page.locator('tr.risk-row', { hasText: 'Refactor checkout session' }).getByRole('button', { name: 'Run Now' }).click();
  await expect(page).toHaveURL(/#runs$/);
  await expect(page.getByRole('heading', { name: /Run #\d+/ })).toBeVisible();
  await waitForRun(page);
  await expect(page.locator('.qcount.ok b')).toHaveText('2');            // home page and health
  await expect(page.locator('.qcount.bad b')).toHaveText('2');           // cart total and orders
  await expect(page.locator('.qcount.info b')).toHaveText('2');          // wishlist page and coupons endpoint
  await expect(page.locator('.qsummary').getByText('High risk, so the full regression set runs')).toBeVisible();
});

test('UC6 a failure shows its screenshot, trace and logs; a pending test is never failed', async () => {
  await page.goto('/verixa_prototype.html#runs');
  await page.locator('.qruns tr.qres').first().click();
  await page.getByRole('tab', { name: /Deployment pending/ }).click();
  await page.locator('tr.qres', { hasText: 'wishlist lists saved items' }).click();
  await expect(page.getByText('A pending test is never counted as failed')).toBeVisible();

  await page.getByRole('tab', { name: /Real bug/ }).click();
  const row = page.locator('tr.qres', { hasText: 'cart total is right' });
  await expect(row).toContainText('<img src=x onerror=alert(1)>');      // shown as text, never run
  await row.press('Enter');                                              // keyboard works too
  const shot = page.getByRole('img', { name: /Screenshot when/ });
  await expect(shot).toBeVisible();
  expect(await shot.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
  await expect(page.getByRole('link', { name: 'Download trace' })).toHaveAttribute('href', /\/api\/evidence\/\d+/);
  await expect(page.locator('.qlog', { hasText: 'Console log' }).locator('pre')).toContainText('cart loaded');
  await page.locator('.qlog summary', { hasText: 'Network log' }).click();
  await expect(page.locator('.qlog', { hasText: 'Network log' }).locator('pre')).toContainText('127.0.0.1:8013');
});

test('UC7 a ticket is checked, edited and filed only when approved', async () => {
  await page.goto('/verixa_prototype.html#runs');
  await page.locator('.qruns tr.qres').first().click();
  await page.locator('tr.qres', { hasText: 'cart total is right' }).click();
  const ticket = page.locator('.qticket');
  await expect(ticket).toContainText('Drafted');
  const title = ticket.getByLabel('Title');
  const file = ticket.getByRole('button', { name: 'Approve and file in Jira' });
  await title.fill('abc');                                               // too short
  await expect(ticket.getByText('at least 5 characters')).toBeVisible();
  await expect(file).toBeDisabled();
  await title.fill('Cart total doubles the price');
  await ticket.getByLabel('Priority').selectOption('High');
  await file.click();
  await expect(toast(page)).toContainText(/Filed in Jira as QA-\d+/);
  await expect(ticket.getByRole('link', { name: /Open QA-\d+ in Jira/ })).toHaveAttribute('href', /demo\.atlassian\.net\/browse\/QA-/);
  await expect(ticket.getByLabel('Title')).toBeDisabled();               // a filed ticket cannot change
});

test('UC9 a fix is suggested as text and added to the ticket draft on request', async () => {
  await page.goto('/verixa_prototype.html#runs');
  await page.locator('.qruns tr.qres').first().click();
  await page.locator('tr.qres', { hasText: 'orders' }).click();
  await page.getByRole('button', { name: 'Suggest a fix' }).click();
  await expect(page.locator('.qdiff .add')).toContainText('+total = price');
  await expect(page.getByText('Verixa never changes your repository')).toBeVisible();
  await page.getByRole('button', { name: 'Add to ticket draft' }).click();
  await expect(toast(page)).toContainText('Added to the ticket draft');
  await page.locator('.qticket summary', { hasText: 'Suggested fix in this ticket' }).click();
  await expect(page.locator('.qticket pre')).toContainText('total = price');
});

test('UC5 a drafted test is approved into the Test Library', async () => {
  await page.goto('/verixa_prototype.html#runs');
  await page.locator('.qruns tr.qres').first().click();
  const card = page.locator('.qdraft', { hasText: 'verixa-payments.spec.ts' });
  await expect(card).toContainText('no test covered');
  await card.getByRole('button', { name: 'Approve and add to library' }).click();
  await expect(toast(page)).toContainText('added to the Test Library');
  await expect(card).toContainText('Approved');
  await page.goto('/verixa_prototype.html#library');
  await expect(page.locator('section:not([hidden])').getByText('verixa-payments.spec.ts').first()).toBeVisible();
});

test('UC10 a second run is compared with the first, side by side', async () => {
  await openRisk(page);
  await page.locator('tr.risk-row', { hasText: 'Refactor checkout session' }).getByRole('button', { name: 'Run Now' }).click();
  await waitForRun(page);
  await page.getByRole('tab', { name: 'Compare runs' }).click();
  await page.getByRole('button', { name: 'Compare' }).click();
  await expect(page.locator('.qtag', { hasText: 'new test' }).first()).toBeVisible();   // the approved drafted test
  await expect(page.locator('.qtag', { hasText: 'still failing' }).first()).toBeVisible();
  await page.locator('tr.qres', { hasText: 'cart total is right' }).click();
  await expect(page.locator('.qside h4')).toHaveText(['Before', 'After']);
});

test('UC7 the Tickets screen separates waiting and filed tickets, and a ticket can be rejected', async () => {
  await page.goto('/verixa_prototype.html#tickets');
  await page.getByRole('tab', { name: /Filed/ }).click();
  await expect(page.locator('.qcard', { hasText: 'Cart total doubles the price' })).toBeVisible();
  await page.getByRole('tab', { name: /Waiting for you/ }).click();
  const first = page.locator('.qcard').first();
  await first.locator('.qcard-head').click();
  await first.getByRole('button', { name: 'Reject' }).click();
  await expect(toast(page)).toContainText('Nothing was sent to Jira');
});

test('UC11 trends show the share of risk and the modules that fail most', async () => {
  await page.goto('/verixa_prototype.html#trends');
  const view = page.locator('section:not([hidden])');
  await expect(view.locator('.risk-stat.high .risk-stat-value')).not.toHaveText('0');
  await expect(page.locator('.qhbar', { hasText: 'payments' })).toContainText('real bugs');
  await expect(view.locator('tr', { hasText: 'Refactor checkout session' })).toContainText(/QA-\d+/);  // its filed ticket
  await view.locator('label', { hasText: 'Period' }).locator('select').selectOption('7');
  await view.locator('.qhbar', { hasText: 'payments' }).click();
  await expect(page.getByRole('heading', { name: 'Pull requests touching payments' })).toBeVisible();
});

test('UC8 QA Memory lists what was learned and a wrong entry can be removed', async () => {
  await page.goto('/verixa_prototype.html#memory');
  const rows = page.locator('.qmemrow');
  await expect(rows.first()).toBeVisible();
  const before = await rows.count();
  await rows.first().getByRole('button', { name: /Remove memory entry/ }).click();
  await expect(toast(page)).toContainText('Memory entry removed');
  await expect(rows).toHaveCount(before - 1);
});

test('another account sees none of it, on screen or through the API', async ({ browser, baseURL }) => {
  const runs = await (await page.request.get('/api/runs')).json();
  const { page: other } = await signIn(browser, OTHER, baseURL!);
  await other.goto('/verixa_prototype.html#runs');
  await expect(other.getByText('No runs yet')).toBeVisible();
  expect((await other.request.get(`/api/runs/${runs.items[0].id}`)).status()).toBe(404);
  expect((await other.request.get('/api/tickets')).ok()).toBeTruthy();
  expect((await (await other.request.get('/api/tickets')).json()).items).toEqual([]);
});

test('the new screens fit a phone without sideways scrolling', async () => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const view of ['runs', 'tickets', 'trends', 'memory', 'connect']) {
    await page.goto(`/verixa_prototype.html#${view}`);
    await page.waitForLoadState('networkidle');
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, view).toBeLessThanOrEqual(1);
  }
});
