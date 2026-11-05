import { test, expect } from '@playwright/test';

test('customer can log in, add a product and check out', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('email_input').fill('customer@shoplite.test');
  await page.getByTestId('password_input').fill('Customer123!');
  await page.getByTestId('login_button').click();
  await expect(page.getByTestId('user_label')).toHaveText('customer@shoplite.test');

  await page.getByTestId('add_to_cart_1').click();
  await expect(page.getByTestId('cart_total')).toHaveText('24.99');

  await page.getByTestId('checkout_button').click();
  await expect(page.getByTestId('message')).toContainText('Order placed');
});

test('guest is asked to log in before adding to cart', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('add_to_cart_1').click();
  await expect(page.getByTestId('message')).toHaveText('Please login first');
});
