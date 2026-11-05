import { test, expect } from '@playwright/test';
import { execSync } from 'child_process';
test('runs a program', async () => { execSync('whoami'); expect(1).toBe(1); });
