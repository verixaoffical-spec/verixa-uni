/**
 * The website with the real GitHub and the real models, on existing pull requests. It only reads from GitHub and writes nothing there.
 * Results are saved in a throwaway SQLite file, never the shared database.
 *
 *   $env:E2E_GITHUB_TOKEN = (gh auth token); npm run test:live
 *
 * Expected labels come from samples/test-data/shoplite/PULL-REQUESTS.md and the rules, written down before these runs.
 * The numbers are checked against GitHub's own answer, not against anything Verixa says.
 */
import { expect, test, type Page } from '@playwright/test';
import fs from 'node:fs';
import { analyse, closePages, detailOf, feed, openRisk, rowOf, signIn, tracePath } from './helpers';

const REPO = process.env.E2E_REPO || 'verixaoffical-spec/Shoplite';
const TOKEN = process.env.E2E_GITHUB_TOKEN!;
const CASES = [
  { number: 10, label: 'High', why: 'email validation in auth code' },
  { number: 9, label: 'Medium', why: 'cart quantity limit' },
  { number: 7, label: 'High', why: 'coupon codes at checkout' },
];

let page: Page;
let problems: string[] = [];

test.beforeEach(async ({ browser, baseURL }) => {
  problems = [];
  test.skip(!TOKEN, 'Needs E2E_GITHUB_TOKEN');
  ({ page, problems } = await signIn(browser, 'live@verixa.dev', baseURL!));
  await openRisk(page);
});

test.afterEach(async () => {
  await closePages();
  expect(problems, 'no alert, page error or blocked resource').toEqual([]);
});

async function github(number: number) {
  const response = await fetch(`https://api.github.com/repos/${REPO}/pulls/${number}`, {
    headers: { Authorization: `Bearer ${TOKEN}`, Accept: 'application/vnd.github+json' },
  });
  expect(response.status).toBe(200);
  return response.json();
}

for (const { number, label, why } of CASES) {
  test(`AT-27 AT-01 #${number} (${why}) matches GitHub and scores ${label}`, async () => {
    await analyse(page, number);
    await expect(page.getByRole('button', { name: 'Analysing…' })).toHaveCount(0, { timeout: 240_000 });
    await expect(rowOf(page, number)).toBeVisible();
    await expect(rowOf(page, number).locator('.rstate')).not.toHaveText('Analysing');

    const truth = await github(number);
    const row = (await feed(page)).items.find((item: { pr_number: number }) => item.pr_number === number);
    test.info().annotations.push({ type: 'result', description: JSON.stringify({
      state: row.state, label: row.risk_label, score: row.score, module: row.module, attempts: row.attempts, model: row.model_used,
      reasoning: row.reasoning, areas: row.test_areas, errors: row.errors,
    }) });

    expect(row.head_sha).toBe(truth.head.sha);
    expect(row.files_changed).toBe(truth.changed_files);
    expect(row.lines_changed).toBe(truth.additions + truth.deletions);
    expect(row.risk_label).toBe(label);
    await expect(rowOf(page, number).locator('.rbadge')).toHaveText(label);
    await expect(rowOf(page, number).locator('code')).toHaveText(truth.head.sha.slice(0, 7));

    // A real model's answer must get through the stricter checks, or they would only ever send work to a person.
    expect(row.state, `errors: ${JSON.stringify(row.errors)}`).toBe('scored');
    await expect(detailOf(page, number).getByText('Agent reasoning')).toBeVisible();
    expect(row.model_used).toBeTruthy();
    expect(row.test_areas.length).toBeGreaterThanOrEqual(2);
  });
}

test('AT-18 a pull request that does not exist gives a real error and no row', async () => {
  await analyse(page, 999999);
  await expect(page.getByText('404', { exact: false }).first()).toBeVisible({ timeout: 30_000 });
  await expect(rowOf(page, 999999)).toHaveCount(0);
});

test('AT-36 AT-44 the real token is nowhere in the log, and each run is traced to the commit', () => {
  const text = fs.readFileSync(tracePath('verixa-e2e-live'), 'utf8');
  expect(text).not.toContain(TOKEN);
  const lines = text.trim().split('\n').map(line => JSON.parse(line));
  const saved = lines.filter(line => line.event === 'service.saved');
  expect(saved.length).toBeGreaterThanOrEqual(3);
  for (const line of saved) expect(line.same_commit, JSON.stringify(line)).toBe(true);
});
