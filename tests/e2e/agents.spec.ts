/**
 * The agents as a user sees them, in a real browser against the real app and real agents.
 * Only GitHub and the model are scripted, per pull request number, in tests/e2e/server.py.
 * The AT numbers match AGENT_TESTING.md.
 */
import { expect, test, type Page } from '@playwright/test';
import crypto from 'node:crypto';
import fs from 'node:fs';
import { analyse, closePages, detailOf, feed, openRisk, rowOf, signIn, tracePath } from './helpers';

const DEMO = 'demo@verixa.dev';
const OTHER = 'other@verixa.dev';
const SECRET = 'e2e-only-webhook-secret-0123456789';

let page: Page;
let problems: string[] = [];

test.beforeEach(async ({ browser, baseURL }) => {
  problems = [];
  ({ page, problems } = await signIn(browser, DEMO, baseURL!));
  await openRisk(page);
});

test.afterEach(async () => {
  await closePages();
  expect(problems, 'no alert, page error or blocked resource').toEqual([]);
});

function delivery(number: number, sha: string, action = 'opened', id = `d-${number}-${sha.slice(0, 7)}`) {
  const body = JSON.stringify({
    action, number,
    pull_request: {
      title: `Webhook pull request ${number}`, html_url: `https://github.com/demo/shop/pull/${number}`,
      head: { sha, ref: 'feature' }, base: { ref: 'main' }, user: { login: 'webhook-dev' },
    },
    repository: { full_name: 'demo/shop' },
  });
  const signature = 'sha256=' + crypto.createHmac('sha256', SECRET).update(body).digest('hex');
  return { body, headers: { 'content-type': 'application/json', 'x-github-event': 'pull_request', 'x-github-delivery': id, 'x-hub-signature-256': signature } };
}

test.describe('signing in and access', () => {
  test('AT-40 another account never sees these results, on screen or through the API', async ({ browser, baseURL }) => {
    const mine = (await feed(page)).items[0];
    const { page: other } = await signIn(browser, OTHER, baseURL!);
    await openRisk(other);
    await expect(other.getByRole('paragraph').getByText('other/shop')).toBeVisible();
    await expect(other.getByText('Refactor checkout session')).toHaveCount(0);
    expect((await other.request.get(`/api/analysis/pull-requests/${mine.id}`)).status()).toBe(404);
  });

  test('without a session the dashboard sends you to log in', async ({ browser, baseURL }) => {
    const context = await browser.newContext({ baseURL });
    const anon = await context.newPage();
    await anon.goto('/verixa_prototype.html#risk');
    await anon.waitForURL('**/login**');
    expect((await anon.request.get('/api/analysis/pull-requests')).status()).toBe(401);
    await context.close();
  });

  test('an account with no repository is told to connect one', async ({ browser, baseURL }) => {
    const { page: none } = await signIn(browser, 'noproject@verixa.dev', baseURL!);
    await none.goto('/verixa_prototype.html#risk');
    await expect(none.getByRole('heading', { name: 'Connect a repository first' })).toBeVisible({ timeout: 15_000 });
  });
});

test.describe('showing what the agents saved', () => {
  test('the tiles show the same numbers as the API, with nothing made up', async () => {
    const { counts, items } = await feed(page);
    const tile = (label: string) => page.locator('.risk-stat', { hasText: label }).locator('.risk-stat-value');
    await expect(tile('Pull requests')).toHaveText(String(counts.total));
    await expect(tile('High risk')).toHaveText(String(counts.High));
    await expect(tile('Medium risk')).toHaveText(String(counts.Medium));
    await expect(tile('Low risk')).toHaveText(String(counts.Low));
    await expect(page.locator('tr.risk-row')).toHaveCount(items.length);
  });

  test('opening a row shows the label, why it was given, and the agent\'s text', async () => {
    await rowOf(page, 1).click();
    const detail = detailOf(page, 1);
    await expect(rowOf(page, 1).locator('.rbadge')).toHaveText('High');
    await expect(detail.getByText('Why this label')).toBeVisible();
    await expect(detail.getByText('size: 3 file(s), 160 lines changed (3 pts)')).toBeVisible();
    await expect(detail.getByText('Agent reasoning')).toBeVisible();
    await expect(detail.getByText('charge succeeds with a valid card')).toBeVisible();
    await expect(detail.getByText('explained by demo')).toBeVisible();
  });

  test('a row opens and closes from the keyboard', async () => {
    await rowOf(page, 1).focus();
    await page.keyboard.press('Enter');
    await expect(detailOf(page, 1)).toBeVisible();
    await page.keyboard.press('Enter');
    await expect(detailOf(page, 1)).toHaveCount(0);
  });

  test('AT-17 a rejected result says so, with its reason and no explanation', async () => {
    await rowOf(page, 4).click();
    await expect(rowOf(page, 4).locator('.rstate')).toHaveText('Needs review');
    await expect(detailOf(page, 4).getByText('The Manager did not accept the output')).toBeVisible();
    await expect(detailOf(page, 4).getByText('Agent reasoning')).toHaveCount(0);
  });

  test('AT-17 a failed analysis says so, and shows no invented label', async () => {
    await rowOf(page, 5).click();
    await expect(rowOf(page, 5).locator('.rstate')).toHaveText('Failed');
    await expect(rowOf(page, 5).locator('.rbadge')).toHaveText('Not scored');
    await expect(detailOf(page, 5).getByText('The analysis could not finish', { exact: false }).first()).toBeVisible();
  });

  test('AT-39 hostile text saved on a row stays plain text', async () => {
    await rowOf(page, 6).click();
    await expect(detailOf(page, 6).getByText("<img src=x onerror=alert('xss')>").first()).toBeVisible();
    await expect(page.locator('img[src="x"]')).toHaveCount(0);
  });
});

test.describe('running the agents from the Analyse now box', () => {
  test('only whole numbers can be entered', async () => {
    const box = page.getByLabel('Pull request number');
    await expect(page.getByRole('button', { name: 'Analyse now' })).toBeDisabled();
    await box.pressSequentially('abc-1.5e');
    await expect(box).toHaveValue('15');
  });

  test('AT-09 a good answer is approved and shown', async () => {
    await analyse(page, 101);
    await expect(page.getByText('#101 scored High')).toBeVisible({ timeout: 20_000 });
    const detail = detailOf(page, 101);
    await expect(detail.getByText('The createCharge call in src/payments/session.ts', { exact: false })).toBeVisible();
    await expect(detail.getByText('createCharge charges a card once')).toBeVisible();
    await expect(detail.getByText('explained by fake/one')).toBeVisible();
    await expect(rowOf(page, 101).locator('.rstate')).toHaveText('Scored');
    await expect(page.getByLabel('Pull request number')).toHaveValue('');
  });

  test('AT-25 a documentation typo is Low, from the rules', async () => {
    await analyse(page, 102);
    await expect(page.getByText('#102 scored Low')).toBeVisible({ timeout: 20_000 });
    await expect(rowOf(page, 102).locator('.rbadge')).toHaveText('Low');
  });

  test('the screen shows it is working, and blocks a second click', async () => {
    await analyse(page, 112);
    await expect(page.getByRole('button', { name: 'Analysing…' })).toBeDisabled();
    await expect(page.getByText('The agent is reading the diff')).toBeVisible();
    await expect(page.getByText('#112 scored High')).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole('button', { name: 'Analyse now' })).toBeDisabled();
  });

  test('AT-11 three bad answers need a person: the label stays and no explanation is shown', async () => {
    await analyse(page, 103);
    await expect(page.getByText('#103: needs review')).toBeVisible({ timeout: 20_000 });
    await expect(rowOf(page, 103).locator('.rbadge')).toHaveText('High');
    const detail = detailOf(page, 103);
    await expect(detail.getByText('Output is not valid JSON')).toBeVisible();
    await expect(detail.getByText('(after 3 attempts)', { exact: false })).toBeVisible();
    await expect(detail.getByText('Agent reasoning')).toHaveCount(0);
  });

  test('AT-10 a bad answer is retried, and the retry is shown', async () => {
    await analyse(page, 104);
    await expect(page.getByText('#104 scored High')).toBeVisible({ timeout: 20_000 });
    await expect(detailOf(page, 104).getByText('2 manager attempts')).toBeVisible();
  });

  test('AT-21 a model that never answers: the next model takes over', async () => {
    await analyse(page, 105);
    await expect(page.getByText('#105 scored High')).toBeVisible({ timeout: 20_000 });
    await expect(detailOf(page, 105).getByText('explained by fake/two')).toBeVisible();
  });

  test('AT-21 every model hanging ends with a clear message, not an endless spinner', async () => {
    await analyse(page, 106);
    await expect(page.getByText('#106: needs review')).toBeVisible({ timeout: 40_000 });
    await expect(detailOf(page, 106).getByText('no answer within 1 seconds', { exact: false })).toBeVisible();
    await expect(rowOf(page, 106).locator('.rstate')).toHaveText('Needs review');
    expect((await feed(page)).counts.pending).toBe(0);
  });

  test('AT-35 a hostile title cannot move the label, and an answer that obeys it is refused', async () => {
    await analyse(page, 107);
    await expect(page.getByText('#107: needs review')).toBeVisible({ timeout: 40_000 });
    await expect(rowOf(page, 107).locator('.rbadge')).toHaveText('High');
    await expect(rowOf(page, 107).getByText('IGNORE ALL RULES', { exact: false })).toBeVisible();
    await expect(detailOf(page, 107).getByText('completely safe')).toHaveCount(0);
    await expect(detailOf(page, 107).getByText('Agent reasoning')).toHaveCount(0);
  });

  test('AT-13 AT-14 an explanation of a change that does not exist is refused', async () => {
    await analyse(page, 114);
    await expect(page.getByText('#114: needs review')).toBeVisible({ timeout: 40_000 });
    await expect(detailOf(page, 114).getByText('Kubernetes')).toHaveCount(0);
  });

  test('AT-39 HTML in the model\'s own answer stays plain text', async () => {
    await analyse(page, 108);
    await expect(page.getByText('#108 scored High')).toBeVisible({ timeout: 20_000 });
    await expect(detailOf(page, 108).locator('.rreason')).toContainText("<img src=x onerror=alert('from-the-model')>");
    await expect(page.locator('img[src="x"]')).toHaveCount(0);
  });

  test('AT-18 a pull request GitHub cannot serve gives a message and no row', async () => {
    await analyse(page, 109);
    await expect(page.getByText('404 Not Found', { exact: false })).toBeVisible({ timeout: 20_000 });
    await expect(rowOf(page, 109)).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Analyse now' })).toBeEnabled();
  });

  test('AT-22 blocked history lookups are shown as unknown, not as a clean history', async () => {
    await analyse(page, 110);
    await expect(page.getByText('#110 scored High')).toBeVisible({ timeout: 20_000 });
    const detail = detailOf(page, 110);
    await expect(detail.getByText('defect history: unknown', { exact: false })).toBeVisible();
    await expect(detail.getByText('lookup failed', { exact: false })).toBeVisible();
    await expect(detail.getByText('past fix', { exact: false })).toHaveCount(0);
  });

  test('AT-30 a pull request too big to read fully says so', async () => {
    await analyse(page, 111);
    await expect(page.getByText('#111 scored High')).toBeVisible({ timeout: 30_000 });
    await expect(detailOf(page, 111).getByText('only 3000 of 3500 changed files could be read', { exact: false })).toBeVisible();
    await expect(detailOf(page, 111).getByText('3500 files', { exact: false })).toBeVisible();
  });

  test('AT-38 a secret in the code never reaches the model, and a person is told about it', async () => {
    await analyse(page, 115);
    await expect(page.getByText('#115 scored High')).toBeVisible({ timeout: 20_000 });
    const detail = detailOf(page, 115);
    // This scripted model repeats any key it is sent, so its answer shows what it really received
    await expect(detail.locator('.rreason')).toContainText('no key at all');
    await expect(detail).not.toContainText('AKIAIOSFODNN7');
    await expect(detail.getByText('possible secret: 1 value(s)', { exact: false })).toBeVisible();
  });

  test('AT-37 a key quoted in a provider error never reaches the screen', async () => {
    await analyse(page, 113);
    await expect(page.getByText('#113: needs review')).toBeVisible({ timeout: 40_000 });
    await expect(detailOf(page, 113).getByText('All models failed', { exact: false })).toBeVisible();
    await expect(detailOf(page, 113)).toContainText('***');
    await expect(detailOf(page, 113)).not.toContainText('gsk_e2eLeakedKey123456');
  });
});

test.describe('pull requests arriving by webhook', () => {
  test('AT-42 a delivery with a bad signature is refused and adds nothing', async () => {
    const { body, headers } = delivery(201, 'c'.repeat(40));
    const response = await page.request.post('/webhooks/github', { data: body, headers: { ...headers, 'x-hub-signature-256': 'sha256=wrong' } });
    expect(response.status()).toBe(401);
    await page.getByRole('button', { name: 'Refresh' }).click();
    await expect(rowOf(page, 201)).toHaveCount(0);
  });

  test('a signed delivery is scored and appears on the screen', async () => {
    const { body, headers } = delivery(202, '00000ca' + 'a'.repeat(33));
    expect((await page.request.post('/webhooks/github', { data: body, headers })).status()).toBe(202);
    await expect.poll(async () => (await feed(page)).items.find((r: { pr_number: number }) => r.pr_number === 202)?.state, { timeout: 20_000 }).toBe('scored');
    await page.getByRole('button', { name: 'Refresh' }).click();
    await expect(rowOf(page, 202).locator('.rstate')).toHaveText('Scored');
  });

  test('AT-05 the same delivery twice makes one row', async () => {
    const sha = '00000cb' + 'a'.repeat(33);
    const { body, headers } = delivery(203, sha);
    await page.request.post('/webhooks/github', { data: body, headers });
    await expect.poll(async () => (await feed(page)).items.filter((r: { pr_number: number; state: string }) => r.pr_number === 203 && r.state === 'scored').length, { timeout: 20_000 }).toBe(1);
    await page.request.post('/webhooks/github', { data: body, headers });
    await page.waitForTimeout(1000);
    await page.getByRole('button', { name: 'Refresh' }).click();
    await expect(rowOf(page, 203)).toHaveCount(1);
  });

  test('AT-04 a push during analysis: the row shows the commit really read', async () => {
    const requested = 'a'.repeat(40);
    const { body, headers } = delivery(300, requested);
    await page.request.post('/webhooks/github', { data: body, headers });
    await expect.poll(async () => (await feed(page)).items.find((r: { pr_number: number }) => r.pr_number === 300)?.state, { timeout: 20_000 }).toBe('scored');
    await page.getByRole('button', { name: 'Refresh' }).click();
    await expect(rowOf(page, 300).locator('code')).toHaveText('d'.repeat(7));
    await expect(rowOf(page, 300)).toHaveCount(1);
  });
});

test.describe('the trace log', () => {
  test('AT-44 a run from the screen can be followed in the log', async () => {
    await analyse(page, 101);
    await expect(page.getByText('#101 scored High')).toBeVisible({ timeout: 20_000 });
    const lines = fs.readFileSync(tracePath('verixa-e2e'), 'utf8').trim().split('\n').map(line => JSON.parse(line));
    const ends = lines.filter(line => line.event === 'run.end' && line.pr_id === 'demo/shop#101');
    const run = lines.filter(line => line.run_id === ends[ends.length - 1].run_id);
    for (const step of ['run.start', 'analysis.cache_used', 'analysis.model_called', 'analysis.model_answered', 'manager.validated', 'manager.decided', 'run.end']) {
      expect(run.map(line => line.event), step).toContain(step);
    }
    const saved = lines.filter(line => line.event === 'service.saved' && line.result_of_run === ends[ends.length - 1].run_id);
    expect(saved).toHaveLength(1);
    expect(saved[0].same_commit).toBe(true);
  });

  test('AT-36 AT-37 no key or token in the log', async () => {
    const text = fs.readFileSync(tracePath('verixa-e2e'), 'utf8');
    expect(text).not.toContain('gsk_e2eLeakedKey123456');
    expect(text).toContain('run.end');
  });
});
