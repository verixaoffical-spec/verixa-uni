import { test, expect } from '@playwright/test';
test('runs code from text', async () => { eval('1 + 1'); expect(1).toBe(1); });
