import { test, expect } from '@playwright/test';

// Runs against Playwright's public TodoMVC demo, so it works without any setup
const APP = 'https://demo.playwright.dev/todomvc/';

test.beforeEach(async ({ page }) => {
  await page.goto(APP);
});

test('shows the todo app', async ({ page }) => {
  await expect(page).toHaveTitle(/TodoMVC/);
  await expect(page.getByPlaceholder('What needs to be done?')).toBeVisible();
});

test('adds a todo', async ({ page }) => {
  const input = page.getByPlaceholder('What needs to be done?');
  await input.fill('Write Playwright tests');
  await input.press('Enter');

  await expect(page.getByTestId('todo-title')).toHaveText(['Write Playwright tests']);
  await expect(page.getByTestId('todo-count')).toContainText('1');
});

test('completes a todo', async ({ page }) => {
  const input = page.getByPlaceholder('What needs to be done?');
  await input.fill('Review pull request');
  await input.press('Enter');

  await page.getByTestId('todo-item').getByRole('checkbox').check();
  await expect(page.getByTestId('todo-item')).toHaveClass(/completed/);
});

test('filters active todos', async ({ page }) => {
  const input = page.getByPlaceholder('What needs to be done?');
  for (const title of ['Buy milk', 'Fix bug']) {
    await input.fill(title);
    await input.press('Enter');
  }
  await page.getByTestId('todo-item').first().getByRole('checkbox').check();

  await page.getByRole('link', { name: 'Active' }).click();
  await expect(page.getByTestId('todo-title')).toHaveText(['Fix bug']);
});
