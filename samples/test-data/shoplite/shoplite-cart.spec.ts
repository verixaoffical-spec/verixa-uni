import { test, expect } from '@playwright/test';

async function logIn(page) {
  await page.goto('/');
  await page.getByTestId('email_input').fill('customer@shoplite.test');
  await page.getByTestId('password_input').fill('Customer123!');
  await page.getByTestId('login_button').click();
  await expect(page.getByTestId('user_label')).toHaveText('customer@shoplite.test');
}

test('logged in customer sees their email after login', async ({ page }) => {
  await logIn(page);
});

test('adding a product updates the cart total', async ({ page }) => {
  await logIn(page);
  await page.getByTestId('add_to_cart_1').click();
  await expect(page.getByTestId('cart_total')).toHaveText('24.99');
});

test('checkout places the order', async ({ page }) => {
  await logIn(page);
  await page.getByTestId('add_to_cart_1').click();
  await page.getByTestId('checkout_button').click();
  await expect(page.getByTestId('message')).toContainText('Order placed');
});

test('wrong password does not log in', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('email_input').fill('customer@shoplite.test');
  await page.getByTestId('password_input').fill('Wrong-password-1');
  await page.getByTestId('login_button').click();
  await expect(page.getByTestId('user_label')).not.toHaveText('customer@shoplite.test');
});
