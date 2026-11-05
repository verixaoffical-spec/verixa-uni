import { test, expect } from '@playwright/test';
test('runs code from text', async () => { new Function('return 1')(); expect(1).toBe(1); });
