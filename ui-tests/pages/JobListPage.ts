import type { Locator, Page } from '@playwright/test';

export class JobListPage {
  readonly newJobButton: Locator;
  readonly successMessage: Locator;

  constructor(readonly page: Page) {
    this.newJobButton = page.getByRole('link', { name: /new job/i });
    this.successMessage = page.getByRole('status');
  }

  async goto(): Promise<void> {
    await this.page.goto('/jobs');
  }

  /** The table row for one job, found by its name. */
  rowFor(jobName: string): Locator {
    return this.page.getByRole('row').filter({ hasText: jobName });
  }

  /** The cells of a job's row: name, customer, type, scheduled date, status. */
  cellsFor(jobName: string): Locator {
    return this.rowFor(jobName).getByRole('cell');
  }
}
