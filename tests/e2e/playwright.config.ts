import { defineConfig } from '@playwright/test';
import path from 'node:path';

const python = path.resolve(__dirname, '../../.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const live = process.argv.includes('--project=live');

export default defineConfig({
  testDir: __dirname,
  workers: 1,               // one server and one database, and a pull request number means one situation
  timeout: 60_000,
  reporter: [['list'], ['json', { outputFile: 'test-results/results.json' }]],
  use: { screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  projects: [
    { name: 'controlled', testMatch: 'agents.spec.ts', use: { baseURL: 'http://localhost:8011', browserName: 'chromium' } },
    { name: 'live', testMatch: 'agents.live.spec.ts', timeout: 300_000, use: { baseURL: 'http://localhost:8012', browserName: 'chromium' } },
    { name: 'forgot', testMatch: 'forgot_password.spec.ts', use: { baseURL: 'http://localhost:8011', browserName: 'chromium', screenshot: 'only-on-failure' } },
    { name: 'signup', testMatch: 'signup.spec.ts', use: { baseURL: 'http://localhost:8011', browserName: 'chromium', screenshot: 'only-on-failure' } },
    { name: 'profile', testMatch: 'profile.spec.ts', use: { baseURL: 'http://localhost:8011', browserName: 'chromium', screenshot: 'only-on-failure' } },
  ],
  webServer: {
    command: `"${python}" tests/e2e/server.py${live ? ' --live' : ''}`,
    cwd: path.resolve(__dirname, '../..'),
    url: `http://localhost:${live ? 8012 : 8011}/login`,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: 'pipe',
  },
});
