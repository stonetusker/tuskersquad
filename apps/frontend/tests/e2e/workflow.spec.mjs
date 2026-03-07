import { test, expect } from '@playwright/test';

test('start workflow and approve via UI', async ({ page }) => {
  // Open the frontend app
  await page.goto('/');

  // Fill control panel
  await page.fill('input[placeholder="Repository"], input:nth-of-type(1)', 'example/hello').catch(()=>{});
  await page.fill('input[type="number"]', '42').catch(()=>{});

  // Click Start Workflow
  await page.click('button:has-text("Start Workflow")');

  // Wait for status update in workflows
  await page.waitForSelector('.workflow-list li', { timeout: 10000 });

  // Select first workflow
  const first = await page.$('.workflow-list li');
  await first.click();

  // Wait for detail panel to show
  await page.waitForSelector('.panel.detail .wf-id');

  // Approve workflow
  await page.click('.wf-actions button:has-text("Approve")');

  // Expect status to be completed (UI polled)
  await page.waitForSelector('.wf-status:has-text("COMPLETED")', { timeout: 10000 });
  const status = await page.locator('.wf-status').innerText();
  expect(status).toContain('COMPLETED');
});
