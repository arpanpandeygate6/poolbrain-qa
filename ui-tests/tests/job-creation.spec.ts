import { randomBytes } from 'node:crypto';
import { expect, test } from '@playwright/test';
import { accounts } from '../playwright.config';
import { JobFormPage, type NewJob } from '../pages/JobFormPage';
import { JobListPage } from '../pages/JobListPage';
import { LoginPage } from '../pages/LoginPage';
import { qaAutoName } from '../support/naming';

// A customer from the testing company's seeded baseline data.
const SEEDED_CUSTOMER = 'QA Testing Co - Customer A';

test.describe('Job creation', () => {
  test('office admin creates a job', { tag: '@flow:job-creation' }, async ({ page }) => {
    const { email, password } = accounts.officeAdmin;
    test.skip(!email || !password, 'OFFICE_ADMIN_EMAIL and OFFICE_ADMIN_PASSWORD are not set');

    const inAWeek = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
    const job: NewJob = {
      name: qaAutoName(`job-${randomBytes(3).toString('hex')}`),
      customer: SEEDED_CUSTOMER,
      jobType: 'Repair',
      scheduledDate: inAWeek,
    };

    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.signIn(email, password);
    const jobList = new JobListPage(page);
    await jobList.goto();
    await jobList.newJobButton.click();
    await new JobFormPage(page).createJob(job);

    await expect(jobList.successMessage).toContainText(job.name);
    // JOB-1: the job appears with the entered values. JOB-2: it starts as Scheduled.
    await expect(jobList.cellsFor(job.name), 'the new job should be listed with the entered values').toHaveText([
      job.name,
      job.customer,
      job.jobType,
      job.scheduledDate,
      'Scheduled',
    ]);
  });
});
