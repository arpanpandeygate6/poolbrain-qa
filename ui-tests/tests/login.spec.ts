import { expect, test } from '@playwright/test';
import { accounts } from '../playwright.config';
import { LoginPage } from '../pages/LoginPage';

test.describe('Login', () => {
  test('office admin signs in', { tag: '@flow:login' }, async ({ page }) => {
    const { email, password } = accounts.officeAdmin;
    test.skip(!email || !password, 'OFFICE_ADMIN_EMAIL and OFFICE_ADMIN_PASSWORD are not set');

    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.signIn(email, password);

    await expect(loginPage.signedInUser, 'the signed-in user should be shown after login').toContainText(email);
  });
});
