// Checks for uploaded Playwright specs and Postman collections. Pure functions, no React.
// The same rules live in backend/validators.py, and the two must stay in step. The server has the final say.

import { plural } from './format';

export const LIMITS = { specBytes: 500 * 1024, collectionBytes: 5 * 1024 * 1024, maxSpecs: 50 };
export const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'];

const TEST_RE = /(?<![\w.$])test(?:\.(only|skip|fixme))?\s*\(\s*(['"`])((?:\\.|(?!\2)[^\\\n])*)\2/g;
const SECRET_RE = /ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[bp]-[A-Za-z0-9]+-[A-Za-z0-9-]+/;
const SECRET_WARN = 'Possible API key or token found. Move secrets to environment variables';
const BAD_NAME = /[\u0000-\u001f<>:"\/\\|?*]/;
const RESERVED = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/i;
// The test script Verixa writes for an expected status code
export const STATUS_RE = /^pm\.test\("Status code is (\d{3})", function \(\) \{\s*pm\.response\.to\.have\.status\(\1\);\s*\}\);$/;

export type RunMode = '' | 'only' | 'skip' | 'fixme';

export interface TestCase {
  title: string;   // as written in the file, so escaped quotes keep their backslash
  line: number;
  mode: RunMode;
  at: number;      // where "test" starts in the file
  end: number;     // just after the closing quote of the title
  quote: string;   // the quote character around the title
}

export interface SpecAnalysis {
  errors: string[];
  warnings: string[];
  tests: TestCase[];
}

export type Check = { kind: 'none' } | { kind: 'status'; code: string } | { kind: 'custom' };

export interface RequestRow {
  folder: string;    // "Folder / Subfolder", or empty at the top level
  method: string;
  name: string;
  url: string;
  hasTests: boolean;
  check: Check;
  path: number[];    // index of the item at each level of the collection
}

export interface FolderOption {
  label: string;
  idx: number[];
}

export interface CollectionAnalysis {
  errors: string[];
  warnings: string[];
  json: any;         // the parsed Postman collection
  schema: string;    // "v2.0" or "v2.1"
  folders: number;
  folderList: FolderOption[];
  requests: RequestRow[];
}

// Returns why a file name is unsafe on some operating system, or an empty string when it is fine.
export function invalidName(name: string): string {
  if (!name || name !== name.trim()) return 'File name cannot start or end with a space';
  if (name.length > 200) return 'File name is too long';
  if (BAD_NAME.test(name)) return 'File name cannot contain / \\ : * ? " < > | or control characters';
  if (name.endsWith('.')) return 'File name cannot end with a dot';
  if (RESERVED.test(name.split('.')[0])) return 'That file name is reserved by Windows';
  return '';
}

// Blanks out comments (keeping line breaks) and checks that brackets and quotes are closed.
export function scan(src: string): { clean: string; balanced: boolean } {
  const pairs: Record<string, string> = { ')': '(', ']': '[', '}': '{' };
  const stack: string[] = [];
  let out = '', quote: string | null = null;
  for (let i = 0; i < src.length; i++) {
    const c = src[i], n = src[i + 1];
    if (quote) {
      out += c;
      if (c === '\\') { out += n ?? ''; i++; }
      else if (c === quote) quote = null;
      else if (c === '\n' && quote !== '`') return { clean: out + src.slice(i + 1), balanced: false };
      continue;
    }
    if (c === '/' && n === '/') {  // line comment
      while (i < src.length && src[i] !== '\n') { out += ' '; i++; }
      i--;
      continue;
    }
    if (c === '/' && n === '*') {  // block comment
      const end = src.indexOf('*/', i + 2);
      const stop = end < 0 ? src.length : end + 2;
      out += src.slice(i, stop).replace(/[^\n]/g, ' ');
      if (end < 0) return { clean: out, balanced: false };
      i = stop - 1;
      continue;
    }
    if (c === '\\') { out += c + (n ?? ''); i++; continue; }
    if (c === '"' || c === "'" || c === '`') quote = c;
    else if ('([{'.includes(c)) stack.push(c);
    else if (')]}'.includes(c) && stack.pop() !== pairs[c]) return { clean: out + src.slice(i), balanced: false };
    out += c;
  }
  return { clean: out, balanced: !quote && !stack.length };
}

export function analyseSpec(text: string): SpecAnalysis {
  const { clean, balanced } = scan(text);
  const errors: string[] = [], warnings: string[] = [];
  const lineOf = (i: number) => text.slice(0, i).split('\n').length;

  if (!/\bfrom\s+['"]@playwright\/test['"]/.test(clean)) errors.push("Missing import from '@playwright/test'");
  if (/child_process/.test(clean)) errors.push('Uses child_process, which is not allowed in uploaded tests');
  if (!balanced) errors.push('File looks incomplete. A bracket or quote is not closed');

  const tests: TestCase[] = [...clean.matchAll(TEST_RE)].map(m => ({
    title: m[3], line: lineOf(m.index!), mode: (m[1] || '') as RunMode,
    at: m.index!, end: m.index! + m[0].length, quote: m[2],
  }));
  if (!tests.length) errors.push('No tests found. Add at least one test("title", async ({ page }) => { ... })');
  if (tests.some(t => t.mode === 'only')) warnings.push('test.only found. The runner would skip every other test');
  if (!/\bexpect\s*\(/.test(clean)) warnings.push('No assertions found. A test without expect() cannot fail');
  if (SECRET_RE.test(text)) warnings.push(SECRET_WARN);
  return { errors, warnings, tests };
}

// ---- Postman collections ----

const failed = (errors: string[]): CollectionAnalysis =>
  ({ errors, warnings: [], json: null, schema: '', folders: 0, folderList: [], requests: [] });

const asList = (v: any): any[] => [].concat(v ?? []);

function urlOf(request: any): string {
  if (typeof request === 'string') return request;
  if (typeof request.url === 'string') return request.url;
  const url = request.url;
  if (!url) return '';
  return url.raw || asList(url.host).join('.') + '/' + asList(url.path).join('/');
}

// The test scripts of a request that actually contain code
const testEvents = (item: any): any[] =>
  asList(item?.event).filter(e => e && e.listen === 'test' && asList(e.script?.exec).join('').trim());

// What a request checks: nothing, a status code (the kind Verixa writes), or a custom script
function checkOf(item: any): Check {
  const found = testEvents(item);
  if (!found.length) return { kind: 'none' };
  const m = found.length === 1 && STATUS_RE.exec(asList(found[0].script.exec).join('\n').trim());
  return m ? { kind: 'status', code: m[1] } : { kind: 'custom' };
}

export function analyseCollection(text: string): CollectionAnalysis {
  let json: any;
  try { json = JSON.parse(text); } catch (e) { return failed(['Not valid JSON. ' + (e as Error).message]); }
  if (!json || typeof json !== 'object' || Array.isArray(json)) return failed(['Expected a Postman collection object at the top level']);
  if (Array.isArray(json.values) && !json.item) return failed(['This is a Postman environment file. Export the collection instead']);

  const errors: string[] = [], warnings: string[] = [], info = json.info || {};
  const version = /schema\.getpostman\.com\/json\/collection\/v(2\.[01])\.0\//.exec(info.schema || '');
  if (!version) errors.push('Unsupported or missing schema. Export as Collection v2.0 or v2.1');
  if (typeof info.name !== 'string' || !info.name.trim()) errors.push('Collection has no name');
  if (!Array.isArray(json.item) || !json.item.length) return failed([...errors, 'Collection has no items']);

  const requests: RequestRow[] = [], bad: string[] = [], folderList: FolderOption[] = [];

  // Walks folders and requests in order, remembering where each one sits
  function walk(items: any[], path: string[], idx: number[]) {
    items.forEach((item, i) => {
      const name = item?.name || `Item ${i + 1}`;
      if (item && Array.isArray(item.item)) {
        folderList.push({ label: [...path, name].join(' / '), idx: [...idx, i] });
        walk(item.item, [...path, name], [...idx, i]);
        return;
      }
      const r = item?.request;
      if (!r) { bad.push(`"${name}" is neither a folder nor a request`); return; }
      const method = typeof r === 'string' ? 'GET' : String(r.method || 'GET').toUpperCase();
      const url = urlOf(r);
      if (!METHODS.includes(method)) bad.push(`"${name}" uses unsupported method ${method}`);
      if (!url.replace(/\//g, '').trim()) bad.push(`"${name}" has no URL`);
      const check = checkOf(item);
      requests.push({ folder: path.join(' / '), method, name, url, hasTests: check.kind !== 'none', check, path: [...idx, i] });
    });
  }
  walk(json.item, [], []);

  if (!requests.length) errors.push('Collection has no requests');
  errors.push(...bad.slice(0, 5));
  if (bad.length > 5) errors.push(`and ${bad.length - 5} more request problems`);
  const bare = requests.filter(r => !r.hasTests).length;
  if (bare) warnings.push(`${plural(bare, 'request')} without a test script. Newman will only check that they respond`);
  if (SECRET_RE.test(text)) warnings.push(SECRET_WARN);
  return { errors, warnings, json, schema: version ? 'v' + version[1] : '', folders: folderList.length, folderList, requests };
}
