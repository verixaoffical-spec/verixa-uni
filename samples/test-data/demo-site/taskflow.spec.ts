import { test, expect } from '@playwright/test';

// Screen tests for the TaskFlow demo site (staging/server.py). They use roles and labels, the way a visitor reads a page.

test('the home page shows the headline and leads to pricing', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Plan less. Finish more.' })).toBeVisible();
  await page.getByRole('link', { name: 'See pricing' }).click();
  await expect(page).toHaveURL(/\/pricing$/);
});

test('the pricing page shows the monthly prices and the discounted yearly prices', async ({ page }) => {
  await page.goto('/pricing');
  await expect(page.getByText('$10 / month')).toBeVisible();
  await page.getByRole('button', { name: /Yearly/ }).click();
  await expect(page.getByText('$96 / year')).toBeVisible();  // Pro: 12 months with 20% off
  await expect(page.getByText('$240 / year')).toBeVisible(); // Team
});

test('the contact form asks for every field, then sends the message', async ({ page }) => {
  await page.goto('/contact');
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page.getByText('Please fill in every field')).toBeVisible();
  await page.getByLabel('Name').fill('Ada Lovelace');
  await page.getByLabel('Email').fill('ada@example.com');
  await page.getByLabel('Message').fill('Hello, I would like a demo.');
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page.getByText('Thanks, we got your message')).toBeVisible();
});

test('a wrong password does not sign in', async ({ page }) => {
  await page.goto('/signin');
  await page.getByLabel('Email').fill('demo@taskflow.test');
  await page.getByLabel('Password').fill('Wrong-password-1');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('alert')).toHaveText('Email or password is incorrect');
});

test('a signed in user can add a task and sees it in the list', async ({ page }) => {
  await page.goto('/signin');
  await page.getByLabel('Email').fill('demo@taskflow.test');
  await page.getByLabel('Password').fill('Taskflow123!');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('heading', { name: 'Your tasks' })).toBeVisible();
  const title = 'Book the venue ' + Date.now();
  await page.getByLabel('New task').fill(title);
  await page.getByRole('button', { name: 'Add task' }).click();
  await expect(page.getByRole('listitem').filter({ hasText: title })).toBeVisible();
});
