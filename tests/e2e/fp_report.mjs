// Builds FORGOT_PASSWORD_QA_REPORT.md from the last Playwright run (test-results/results.json).
// Every status comes from the run itself: nothing is marked PASS unless Playwright saw it pass.
//     node tests/e2e/fp_report.mjs
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const results = JSON.parse(fs.readFileSync(path.join(here, 'test-results', 'results.json'), 'utf-8'));
const out = path.resolve(here, '../../FORGOT_PASSWORD_QA_REPORT.md');

const rows = [];
(function walk(suites, category = '') {
  for (const suite of suites ?? []) {
    const cat = /^\d+\. /.test(suite.title) ? suite.title : category;
    for (const spec of suite.specs ?? []) {
      if (!/^FP-/.test(spec.title)) continue;
      for (const t of spec.tests) {
        const last = t.results[t.results.length - 1] ?? {};
        const note = (type) => t.annotations.find(a => a.type === type)?.description ?? '';
        const skip = t.annotations.find(a => a.type === 'skip')?.description ?? '';
        const status = last.status === 'passed' ? 'PASS'
          : last.status === 'skipped' ? (skip.startsWith('BLOCKED') ? 'BLOCKED' : 'NOT EXECUTED')
          : 'FAIL';
        const error = (last.error?.message ?? '').replace(/\u001b\[[0-9;]*m/g, '').split('\n').slice(0, 3).join(' ').trim();
        const shot = (last.attachments ?? []).find(a => a.name === 'screenshot')?.path;
        const [id, ...words] = spec.title.split(' ');
        rows.push({ id, scenario: words.join(' '), category: cat, status, steps: note('steps'), expected: note('expected'),
                    severity: note('severity'), error, skip, shot, ms: last.duration ?? 0 });
      }
    }
    walk(suite.suites, cat);
  }
})(results.suites);

const count = (s) => rows.filter(r => r.status === s).length;
const executed = rows.length - count('NOT EXECUTED') - count('BLOCKED');
const pct = executed ? ((count('PASS') / executed) * 100).toFixed(1) : '0';
const cell = (s) => String(s ?? '').replace(/\|/g, '\\|').replace(/\n/g, ' ');
const actual = (r) => r.status === 'PASS' ? 'As expected' : r.status === 'BLOCKED' ? r.skip.replace(/^BLOCKED: /, '') : r.error || 'Did not run';

let md = `# Forgot Password: QA Test Report

**Feature:** Forgot Password and Reset Password
**Run:** ${new Date(results.stats?.startTime ?? Date.now()).toISOString().slice(0, 16).replace('T', ' ')} UTC, Playwright ${results.config?.version ?? ''}, Chromium
**Where:** the real Verixa app and agents on port 8011 with its own throwaway SQLite database (\`tests/e2e/server.py\`). Your real database in \`.env\` was never used.
**How to run again:** \`cd tests/e2e\` then \`npx playwright test --project=forgot\`, then \`node fp_report.mjs\`

Every status below comes from an actual run. A test is PASS only when Playwright checked the expected result.

## Summary

| Measure | Result |
|---|---|
| Test cases | ${rows.length} |
| Passed | ${count('PASS')} |
| Failed | ${count('FAIL')} |
| Blocked | ${count('BLOCKED')} |
| Not executed | ${count('NOT EXECUTED')} |
| Pass rate (of executed) | ${pct}% |

`;

const failed = rows.filter(r => r.status === 'FAIL');
md += `## Critical and high severity defects\n\n`;
md += failed.filter(r => ['Critical', 'High'].includes(r.severity)).length
  ? failed.filter(r => ['Critical', 'High'].includes(r.severity)).map(r => `- **${r.id}** (${r.severity}): ${r.scenario}. ${r.error}`).join('\n') + '\n\n'
  : 'None found.\n\n';

const cats = [...new Set(rows.map(r => r.category))];
for (const cat of cats) {
  md += `## ${cat}\n\n| ID | Scenario | Steps | Expected | Actual | Status | Severity if failed |\n|---|---|---|---|---|---|---|\n`;
  for (const r of rows.filter(x => x.category === cat)) {
    md += `| ${r.id} | ${cell(r.scenario)} | ${cell(r.steps)} | ${cell(r.expected)} | ${cell(actual(r))} | **${r.status}** | ${r.severity} |\n`;
  }
  md += '\n';
}

if (failed.length) {
  md += `## Failures in detail\n\n`;
  for (const r of failed) md += `### ${r.id} ${r.scenario}\n\n- **Failure:** ${r.error}\n- **Severity:** ${r.severity}\n- **Evidence:** ${r.shot ? '`' + path.relative(path.resolve(here, '../..'), r.shot) + '`' : 'see the Playwright trace in tests/e2e/test-results'}\n\n`;
}

fs.writeFileSync(out, md + fs.readFileSync(path.join(here, 'fp_report_notes.md'), 'utf-8'));
console.log(`wrote ${out}: ${rows.length} tests, ${count('PASS')} pass, ${count('FAIL')} fail, ${count('BLOCKED')} blocked`);
