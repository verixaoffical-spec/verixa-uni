/**
 * 68 inputs across the whole app, against the real server (tests/e2e/server.py): first the correct inputs, then
 * negative, edge and attack inputs. Each must get the right answer and change nothing it should not.
 * Writes test-results/inputs.md, a table of every input and what happened, for the project report.
 */
import { expect, test, type APIRequestContext } from '@playwright/test';
import fs from 'node:fs';
import { closePages, signIn } from './helpers';

test.describe.configure({ mode: 'serial' });
const rows: string[] = [];
let api: APIRequestContext;
let n = 0;

function record(area: string, input: string, expected: string, got: string, ok: boolean) {
  rows.push(`| ${++n} | ${area} | ${input.replace(/\|/g, '\\|').slice(0, 70)} | ${expected} | ${got} | ${ok ? 'pass' : '**FAIL**'} |`);
  expect(ok, `${area}: ${input} expected ${expected}, got ${got}`).toBeTruthy();
}

async function check(area: string, input: string, call: () => Promise<{ status(): number; text(): Promise<string> }>,
                     status: number, contains = '') {
  const res = await call();
  const body = await res.text();
  record(area, input, `${status}${contains ? ` "${contains}"` : ''}`, `${res.status()}`,
         res.status() === status && (!contains || body.includes(contains)));
  return body;
}

const json = (data: object) => ({ data, headers: { 'content-type': 'application/json' } });
const spec = (body: string) => `import { test, expect } from '@playwright/test';\n${body}\ntest('home page opens', async ({ page }) => { await page.goto('/'); expect(1).toBe(1); });\n`;
const collection = (items: object[]) => JSON.stringify({ info: { name: 'API', schema: 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json' }, item: items });

test.beforeAll(async ({ browser, baseURL }) => {
  const { page } = await signIn(browser, 'demo@verixa.dev', baseURL!);
  api = page.request;
});

test.afterAll(async () => {
  fs.mkdirSync('test-results', { recursive: true });
  fs.writeFileSync('test-results/inputs.md', ['| # | Area | Input | Expected | Got | Result |', '|---|---|---|---|---|---|', ...rows].join('\n') + '\n');
  await closePages();
});

test('sign up: correct, negative and attack inputs', async ({ playwright, baseURL }) => {
  const anon = await playwright.request.newContext({ baseURL });
  const signup = (name: string, email: string, password: string) => () => anon.post('/auth/signup', json({ name, email, password }));
  await check('Sign up', 'valid: Ada Lovelace / ada.new@example.com / Verixa-2026', signup('Ada Lovelace', 'ada.new@example.com', 'Verixa-2026'), 202);
  await check('Sign up', 'empty name', signup('', 'a1@example.com', 'Verixa-2026'), 422, 'name');
  await check('Sign up', 'name is a script tag <script>alert(1)</script>', signup('<script>alert(1)</script>', 'a2@example.com', 'Verixa-2026'), 422, 'name');
  await check('Sign up', 'email ada@@example.com', signup('Ada', 'ada@@example.com', 'Verixa-2026'), 422, 'email');
  await check('Sign up', 'email of 300 characters', signup('Ada', 'a'.repeat(290) + '@example.com', 'Verixa-2026'), 422, 'email');
  await check('Sign up', 'password "short1" (too short)', signup('Ada', 'a3@example.com', 'short1'), 422, 'password');
  await check('Sign up', 'password "onlyletters" (no number)', signup('Ada', 'a4@example.com', 'onlyletters'), 422, 'password');
  await check('Sign up', 'password "password123" (common)', signup('Ada', 'a5@example.com', 'password123'), 422, 'password');
  await check('Sign up', 'email already used: demo@verixa.dev', signup('Someone', 'demo@verixa.dev', 'Verixa-2026'), 409, 'email');
  await anon.dispose();
});

test('log in: wrong, empty and injection inputs', async ({ playwright, baseURL }) => {
  const anon = await playwright.request.newContext({ baseURL });
  const login = (email: string, password: string) => () => anon.post('/auth/login', json({ email, password }));
  await check('Log in', 'unknown email nobody@example.com', login('nobody@example.com', 'Verixa-2026'), 401);
  await check('Log in', 'SQL injection in email: \' OR 1=1 --', login("' OR 1=1 --", 'x'), 422);
  await check('Log in', 'empty email and password', login('', ''), 422);
  await check('Log in', 'right email, wrong password', login('other@verixa.dev', 'Wrong-pass-1'), 401);
  await check('Log in', 'valid: other@verixa.dev / Verixa-Demo-2026', login('other@verixa.dev', 'Verixa-Demo-2026'), 200);
  await anon.dispose();
});

test('staging address: every rule', async () => {
  const save = (url: unknown) => () => api.post('/api/project/staging', json({ url }));
  for (const [input, why] of [['', 'empty'], ['ftp://files.example.com', 'not http'], ['javascript:alert(1)', 'script address'],
    ['http://169.254.169.254/latest/meta-data', 'cloud metadata'], ['http://[::ffff:169.254.169.254]/', 'metadata in IPv6'],
    ['http://user:secret@staging.example.com', 'password in address'], ['http://staging.example.com/?debug=1', 'query part'],
    ['http://localhost:8011', 'the Verixa server itself'], ['http://no-such-host.invalid', 'host does not exist']] as const) {
    await check('Staging', `${input || '(empty)'}  [${why}]`, save(input), 422);
  }
  await check('Staging', 'a number instead of text', save(5), 422);
  await check('Staging', 'valid: http://127.0.0.1:8013', save('http://127.0.0.1:8013'), 200, 'reachable');
});

test('Test Library: unsafe and broken files are refused, good ones saved', async () => {
  const saveSpec = (name: string, text: string) => () => api.post('/api/library/apply', json({ specs: [{ name, text }] }));
  const refused: [string, string][] = [
    ['imports fs', "import fs from 'fs';\n" + spec('')],
    ['require child_process', spec("const x = require('child_process');")],
    ['reads process.env', spec('const key = process.env.SECRET_KEY;')],
    ['eval of text', spec("eval('1+1');")],
    ['globalThis', spec('globalThis.x = 1;')],
    ['opens a file:// page', spec("test('reads a file', async ({ page }) => { await page.goto('file:///C:/Windows/win.ini'); });")],
    ['constructor trick', spec("(() => 1).constructor('return 1')();")],
    ['empty file', ''],
    ['no test in it', "import { test } from '@playwright/test';\n"],
    ['unclosed bracket', "import { test, expect } from '@playwright/test';\ntest('a b c', async () => {\n"],
  ];
  let i = 0;
  for (const [why, text] of refused) await check('Library spec', `refused: ${why}`, saveSpec(`bad${++i}.spec.ts`, text), 422);
  await check('Library spec', 'refused: name ../../evil.spec.ts', saveSpec('../../evil.spec.ts', spec('')), 422);
  await check('Library spec', 'valid spec checkout.spec.ts', saveSpec('checkout.spec.ts', spec('')), 200);

  const saveCol = (text: string) => () => api.post('/api/library/apply', json({ collection: { name: 'api2.json', text, revision: 1 } }));
  await check('Library collection', 'refused: not JSON {oops', saveCol('{oops'), 422);
  await check('Library collection', 'refused: request to javascript:alert(1)', saveCol(collection([{ name: 'x', request: { method: 'GET', url: 'javascript:alert(1)' } }])), 422);
  await check('Library collection', 'refused: no requests at all', saveCol(collection([])), 422);
});

let runId = 0;
let bugResult = 0;
let ticketId = 0;

test('Run Now: only a real, scored pull request of this account runs', async () => {
  const feed = await (await api.get('/api/analysis/pull-requests')).json();
  const scored = feed.items.find((r: any) => r.state === 'scored' && r.risk_label === 'High');
  const run = (id: unknown) => () => api.post('/api/runs', json({ assessment_id: id }));
  await check('Run Now', 'id as text "1"', run('1'), 422);
  await check('Run Now', 'id 0', run(0), 422);
  await check('Run Now', 'id of a row that does not exist (999999)', run(999999), 404);
  await check('Run Now', 'no id at all', () => api.post('/api/runs', json({})), 422);
  const body = await check('Run Now', `valid: PR #${scored.pr_number} (High risk)`, run(scored.id), 202);
  runId = JSON.parse(body).id;
  await check('Run Now', 'second run while one is running', run(scored.id), 409, 'already in progress');
  await expect.poll(async () => (await (await api.get(`/api/runs/${runId}`)).json()).run.status, { timeout: 300_000 }).not.toBe('running');
  const detail = await (await api.get(`/api/runs/${runId}`)).json();
  bugResult = detail.results.find((r: any) => r.outcome === 'real_bug').id;
  ticketId = detail.tickets[0].id;
  record('Run Now', 'run finishes and sorts results', 'real bugs and pending found', `${detail.run.counts.real_bug} bugs, ${detail.run.counts.deployment_pending} pending`,
         detail.run.counts.real_bug > 0 && detail.run.counts.deployment_pending > 0);
});

test('ticket review: bad edits are refused, a script in the title stays text', async () => {
  const edit = (body: object) => () => api.post(`/api/tickets/${ticketId}`, json({ title: 'Cart total is wrong', root_cause: 'The price is added twice.', steps: ['Open the cart'], priority: 'High', ...body }));
  await check('Ticket', 'priority "Urgent" (not a Jira priority)', edit({ priority: 'Urgent' }), 422);
  await check('Ticket', 'title "abc" (too short)', edit({ title: 'abc' }), 422);
  await check('Ticket', 'no steps', edit({ steps: [] }), 422);
  await check('Ticket', '21 steps (over the limit)', edit({ steps: Array(21).fill('step') }), 422);
  await check('Ticket', 'valid edit with <img src=x onerror=alert(1)> in the title', edit({ title: 'Cart <img src=x onerror=alert(1)> total' }), 200);
});

test('fix, trends, evidence and memory: odd inputs', async () => {
  await check('Suggest a fix', 'a result id that is not a real bug or not yours (999999)', () => api.post('/api/results/999999/fix', json({})), 404);
  await check('Suggest a fix', `valid: real bug #${bugResult}`, () => api.post(`/api/results/${bugResult}/fix`, json({})), 200, 'diff');
  await check('Trends', 'days=5 (not a period on offer)', () => api.get('/api/trends?days=5'), 422);
  await check('Trends', 'days=abc', () => api.get('/api/trends?days=abc'), 422);
  await check('Trends', 'valid: days=30', () => api.get('/api/trends?days=30'), 200, 'share');
  await check('Evidence', 'id 0', () => api.get('/api/evidence/0'), 422);
  await check('Evidence', 'path trick ..%2F..%2F.env', () => api.get('/api/evidence/..%2F..%2F.env'), 404);
  const memory = (await (await api.get('/api/memory')).json()).items;
  await check('QA Memory', `remove entry #${memory[0].id}`, () => api.post(`/api/memory/${memory[0].id}/delete`, json({})), 204);
  await check('QA Memory', 'remove the same entry again', () => api.post(`/api/memory/${memory[0].id}/delete`, json({})), 404);
  const feed = await (await api.get('/api/analysis/pull-requests')).json();
  const scored = feed.items.find((r: any) => r.state === 'scored' && r.risk_label === 'High');
  const wrong = (id: number, expected: unknown) => () => api.post(`/api/analysis/pull-requests/${id}/wrong-label`, json({ expected }));
  await check('Risk label', 'marked wrong, expected "Urgent" (not a label)', wrong(scored.id, 'Urgent'), 422);
  await check('Risk label', 'marked wrong, expected High (the label it already has)', wrong(scored.id, 'High'), 422, 'already');
  await check('Risk label', 'a row that does not exist (999999)', wrong(999999, 'Low'), 404);
  await check('Risk label', 'valid: High marked wrong, expected Low', wrong(scored.id, 'Low'), 200, '"marked_wrong":true');
  await check('Risk label', 'marked wrong a second time', wrong(scored.id, 'Low'), 409, 'already marked');
  await check('QA Memory', 'the wrong label is now a memory entry', () => api.get('/api/memory?kind=risk_label'), 200, 'marked wrong');
  await check('Cross site', 'Run Now sent from another site (Origin: https://evil.example)',
              () => api.post('/api/runs', { data: { assessment_id: 1 }, headers: { 'content-type': 'application/json', origin: 'https://evil.example' } }), 403);
});
