import { test, expect } from '@playwright/test';

// The wishlist page is not on staging until it is switched on at /demo.
// While it answers 404, Verixa marks this test "deployment pending" and does not call it a bug.
test('wishlist page lists saved items', async ({ page }) => {
  await page.goto('/wishlist');
  await expect(page.locator('h1')).toHaveText('Wishlist');
});
