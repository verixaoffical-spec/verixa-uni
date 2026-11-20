import { test, expect } from '@playwright/test';

// The Docs page is not on staging until it is switched on at /demo.
// While /docs answers 404, Verixa marks this test "deployment pending" and does not call it a bug.
test('the documentation page explains how to add a task', async ({ page }) => {
  await page.goto('/docs');
  await expect(page.getByRole('heading', { name: 'Documentation' })).toBeVisible();
  await expect(page.getByText('add a task')).toBeVisible();
});
