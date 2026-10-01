import type { Locator, Page } from '@playwright/test';

export interface NewJob {
  name: string;
  customer: string;
  jobType: string;
  /** YYYY-MM-DD */
  scheduledDate: string;
}

export class JobFormPage {
  readonly name: Locator;
  readonly customer: Locator;
  readonly jobType: Locator;
  readonly scheduledDate: Locator;
  readonly createButton: Locator;
  readonly error: Locator;

  constructor(readonly page: Page) {
    this.name = page.getByPlaceholder(/job name/i);
    this.customer = page.getByRole('combobox', { name: 'Customer' });
    this.jobType = page.getByRole('combobox', { name: 'Job type' });
    this.scheduledDate = page.getByLabel('Scheduled date');
    this.createButton = page.getByRole('button', { name: /create job/i });
    this.error = page.getByRole('alert');
  }

  async createJob(job: NewJob): Promise<void> {
    await this.name.fill(job.name);
    await this.customer.selectOption({ label: job.customer });
    await this.jobType.selectOption({ label: job.jobType });
    await this.scheduledDate.fill(job.scheduledDate);
    await this.createButton.click();
  }
}
