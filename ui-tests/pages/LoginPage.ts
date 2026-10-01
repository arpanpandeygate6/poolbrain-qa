import type { Locator, Page } from '@playwright/test';

// Locators follow what a person sees: PoolBrain's forms show hint text inside
// the boxes instead of labels. Check them against real UAT when it is available.
export class LoginPage {
  readonly email: Locator;
  readonly password: Locator;
  readonly signInButton: Locator;
  readonly error: Locator;
  readonly signedInUser: Locator;

  constructor(readonly page: Page) {
    this.email = page.getByPlaceholder(/email/i);
    this.password = page.getByPlaceholder(/password/i);
    this.signInButton = page.getByRole('button', { name: /sign in|log ?in/i });
    this.error = page.getByRole('alert');
    this.signedInUser = page.getByTestId('signed-in-user');
  }

  async goto(): Promise<void> {
    await this.page.goto('/login');
  }

  async signIn(email: string, password: string): Promise<void> {
    await this.email.fill(email);
    await this.password.fill(password);
    await this.signInButton.click();
  }
}
