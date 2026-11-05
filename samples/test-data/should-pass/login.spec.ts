import { test, expect } from '@playwright/test';

test('login page shows the form', async ({ page }) => {
  await page.goto('https://example.com/login');
  await expect(page.locator('form')).toBeVisible();
});

test('title and address use regular expressions', async ({ page }) => {
  await page.goto('https://example.com');
  await expect(page).toHaveTitle(/Bob's [(]shop/);
  await expect(page).toHaveURL(/https?:\/\/example/);
});

test('page.$eval is a normal Playwright call', async ({ page }) => {
  const text = await page.$eval('h1', el => el.textContent);
  expect(text).toBeTruthy();
});
