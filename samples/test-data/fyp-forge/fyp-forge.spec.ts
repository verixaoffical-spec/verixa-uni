import { test, expect } from '@playwright/test';

// Read-only tests for the live website https://fypmate-ai.lovable.app (FYP Forge).
// They only look and click. They never create an account and never sign in with a real one.

test('the home page sends a visitor to the sign in page', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/auth$/);
  await expect(page).toHaveTitle(/FYP Forge/);
  await expect(page.getByRole('heading', { name: 'Welcome Back' })).toBeVisible();
});

test('the sign in form has an email and a password field', async ({ page }) => {
  await page.goto('/auth');
  await expect(page.getByPlaceholder('you@university.edu')).toBeVisible();
  await expect(page.getByPlaceholder('Min 6 chars, letters & numbers')).toBeVisible();
});

test('an empty form says what is required', async ({ page }) => {
  await page.goto('/auth');
  await page.getByRole('button', { name: /^Sign In/ }).click();
  await expect(page.getByText('Email is required')).toBeVisible();
  await expect(page.getByText('Password is required')).toBeVisible();
});

test('a wrong password is refused and the visitor stays on the sign in page', async ({ page }) => {
  await page.goto('/auth');
  await page.getByPlaceholder('you@university.edu').fill('verixa.check@example.invalid');
  await page.getByPlaceholder('Min 6 chars, letters & numbers').fill('Wrong-password-1');
  await page.getByRole('button', { name: /^Sign In/ }).click();
  await expect(page.getByText('Invalid email or password')).toBeVisible();
  await expect(page).toHaveURL(/\/auth$/);
});

test('the Sign Up tab shows the account form', async ({ page }) => {
  await page.goto('/auth');
  await page.getByRole('button', { name: 'Sign Up' }).click();
  await expect(page.getByRole('heading', { name: 'Create Your Account' })).toBeVisible();
});

test('the page fits a phone without sideways scrolling', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto('/auth');
  await expect(page.getByRole('heading', { name: 'Welcome Back' })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test('the sign in page loads without a console error', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto('/auth');
  await expect(page.getByRole('heading', { name: 'Welcome Back' })).toBeVisible();
  expect(errors).toEqual([]);
});
