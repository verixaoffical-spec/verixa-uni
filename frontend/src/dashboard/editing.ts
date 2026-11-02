// Edits made in the dashboard tables. Each function takes the file text and returns the new file text,
// or throws an Error with a message for the person. Pure functions, no React.

import { METHODS, STATUS_RE, scan, type TestCase } from './validation';

// ---- Playwright specs ----

// Same length as the source, with comments and the inside of strings blanked, so brackets can be matched safely.
function mask(src: string): string {
  const clean = scan(src).clean;
  let out = '', quote: string | null = null;
  for (let i = 0; i < clean.length; i++) {
    const c = clean[i];
    if (quote) {
      if (c === '\\') { out += i + 1 < clean.length ? (clean[i + 1] === '\n' ? ' \n' : '  ') : ' '; i++; continue; }
      if (c === quote) { quote = null; out += c; } else out += c === '\n' ? c : ' ';
      continue;
    }
    if (c === '\\') {  // an escaped character outside a string, such as the ) in /x\)/
      out += ' ';
      if (i + 1 < clean.length) { out += clean[i + 1] === '\n' ? '\n' : ' '; i++; }
      continue;
    }
    if (c === '"' || c === "'" || c === '`') quote = c;
    out += c;
  }
  return out;
}

const prefixLength = (t: TestCase) => 4 + (t.mode ? t.mode.length + 1 : 0);  // "test" or "test.skip"

// The test name as a person reads it, without escape backslashes
export const displayTitle = (t: TestCase) => t.title.replace(/\\(['"`])/g, '$1');

// Names with other backslash escapes are only editable in the file itself
export const titleEditable = (t: TestCase) => !t.title.replace(/\\['"`]/g, '').includes('\\');

function titleProblem(title: string, quote = "'"): string {
  if (!title.trim()) return 'The test case name cannot be empty';
  if (title.length > 200) return 'The test case name is too long (200 characters at most)';
  if (/[\r\n]/.test(title)) return 'The test case name must be one line';
  if (title.includes('\\')) return 'Backslashes are not supported in test case names here';
  if (quote === '`' && title.includes('${')) return 'The test case name cannot contain ${ here';
  return '';
}

export function renameTest(src: string, t: TestCase, newTitle: string): string {
  const title = newTitle.trim();
  const problem = titleProblem(title, t.quote);
  if (problem) throw new Error(problem);
  const from = t.end - 1 - t.title.length;
  return src.slice(0, from) + title.split(t.quote).join('\\' + t.quote) + src.slice(t.end - 1);
}

export function setTestMode(src: string, t: TestCase, mode: string): string {
  if (!['', 'skip', 'fixme', 'only'].includes(mode)) throw new Error('Unknown run mode');
  return src.slice(0, t.at) + 'test' + (mode ? '.' + mode : '') + src.slice(t.at + prefixLength(t));
}

// Removes the whole test(...) statement, including its trailing semicolon and the rest of its last line.
export function deleteTest(src: string, t: TestCase): string {
  const m = mask(src);

  // Find the bracket that closes test(
  let open = t.at + prefixLength(t);
  while (open < m.length && m[open] !== '(') open++;
  let depth = 0, close = open;
  for (; close < m.length; close++) {
    if (m[close] === '(') depth++;
    else if (m[close] === ')' && --depth === 0) break;
  }
  if (depth !== 0 || close >= m.length) throw new Error('This test case could not be removed safely. Edit your file instead');

  // Take the semicolon and the line break after it too
  let end = close + 1;
  while (m[end] === ' ' || m[end] === '\t') end++;
  if (m[end] === ';') end++;
  let k = end;
  while (m[k] === ' ' || m[k] === '\t' || m[k] === '\r') k++;
  if (m[k] === '\n') end = k + 1; else if (k >= m.length) end = k;

  // And the indentation before it, when the test starts its own line
  let start = t.at;
  while (start > 0 && (src[start - 1] === ' ' || src[start - 1] === '\t')) start--;
  if (start > 0 && src[start - 1] !== '\n') start = t.at;
  return src.slice(0, start) + src.slice(end);
}

// New test cases are added as test.fixme placeholders: Playwright skips them until the steps are written.
export function appendTest(src: string, newTitle: string): string {
  const title = newTitle.trim();
  const problem = titleProblem(title);
  if (problem) throw new Error(problem);
  const nl = src.includes('\r\n') ? '\r\n' : '\n';
  const body = [
    "test.fixme('" + title.split("'").join("\\'") + "', async ({ page }) => {",
    '  // TODO: write the steps for this test case',
    '});',
  ].join(nl);
  return src.replace(/\s*$/, '') + nl + nl + body + nl;
}

// ---- Postman collections ----

export type RequestField = 'name' | 'method' | 'url' | 'status';

export interface NewRequest {
  folder: string;   // folder indexes joined with dots, or empty for the top level
  method: string;
  name: string;
  url: string;
  status: string;   // expected status code, or empty for no test
}

function nodeAt(json: any, path: number[]): any {
  let items = json.item, node = null;
  for (const i of path) {
    node = items && items[i];
    items = node && node.item;
  }
  return node;
}

function requestOf(node: any): any {
  if (typeof node.request === 'string') node.request = { method: 'GET', url: node.request };
  return node.request;
}

const statusScript = (code: string) => ({
  listen: 'test',
  script: {
    type: 'text/javascript',
    exec: [`pm.test("Status code is ${code}", function () {`, `    pm.response.to.have.status(${code});`, '});'],
  },
});

const isTestEvent = (e: any) => e && e.listen === 'test';
const scriptText = (e: any) => [].concat(e.script?.exec ?? []).join('\n').trim();

function fieldProblem(field: RequestField, value: string): string {
  if (field === 'name') return !value ? 'The name cannot be empty' : value.length > 200 ? 'The name is too long (200 characters at most)' : /[\r\n]/.test(value) ? 'The name must be one line' : '';
  if (field === 'url') return !value ? 'The URL cannot be empty' : value.length > 2000 ? 'The URL is too long' : /[\r\n]/.test(value) ? 'The URL must be one line' : '';
  if (field === 'method') return METHODS.includes(value) ? '' : 'Choose a valid method';
  return value === '' || (/^\d{3}$/.test(value) && +value >= 100 && +value <= 599) ? '' : 'The status code must be between 100 and 599, or empty';
}

function applyField(node: any, field: RequestField, value: string) {
  const problem = fieldProblem(field, value);
  if (problem) throw new Error(problem);
  if (field === 'name') node.name = value;
  else if (field === 'method') requestOf(node).method = value;
  else if (field === 'url') requestOf(node).url = value;  // a plain string, which Postman and Newman both parse
  else {
    // The status check replaces any test script Verixa wrote, but never one the person wrote themselves
    const events: any[] = [].concat(node.event ?? []);
    const custom = events.filter(isTestEvent).some(e => scriptText(e) && !STATUS_RE.test(scriptText(e)));
    if (custom) throw new Error('This request has its own test script. Edit it in Postman');
    node.event = events.filter(e => !isTestEvent(e));
    if (value) node.event.push(statusScript(value));
    if (!node.event.length) delete node.event;
  }
}

export function editRequest(text: string, path: number[], field: RequestField, value: string): string {
  const json = JSON.parse(text), node = nodeAt(json, path);
  if (!node || !node.request) throw new Error('That request no longer exists');
  applyField(node, field, value.trim());
  return JSON.stringify(json, null, 2);
}

export function addRequest(text: string, row: NewRequest): string {
  const json = JSON.parse(text);
  const folder = row.folder ? row.folder.split('.').map(Number) : [];
  const items = folder.length ? (nodeAt(json, folder) || {}).item : json.item;
  if (!Array.isArray(items)) throw new Error('That folder no longer exists');
  const node = { name: '', request: { method: 'GET', header: [], url: '' } };
  applyField(node, 'name', row.name.trim());
  applyField(node, 'method', row.method);
  applyField(node, 'url', row.url.trim());
  applyField(node, 'status', row.status.trim());
  items.push(node);
  return JSON.stringify(json, null, 2);
}

export function deleteRequest(text: string, path: number[]): string {
  const json = JSON.parse(text);
  const parent = path.length > 1 ? (nodeAt(json, path.slice(0, -1)) || {}).item : json.item;
  const last = path[path.length - 1];
  if (!Array.isArray(parent) || !parent[last]) throw new Error('That request no longer exists');
  parent.splice(last, 1);
  return JSON.stringify(json, null, 2);
}

