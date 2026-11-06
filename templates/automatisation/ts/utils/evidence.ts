// Step screenshots taken during a test. They are attached to the test result,
// so Allure shows them and utils/evidence-reporter.js copies them to evidence/.
import type { Locator, Page, TestInfo } from '@playwright/test';

export function slugify(text: string): string {
  return text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 80);
}

export async function captureStep(page: Page, testInfo: TestInfo, step: string, { mask = [] as Locator[] } = {}): Promise<void> {
  const index = testInfo.attachments.filter((a) => a.name.startsWith('step ')).length + 1;
  const file = testInfo.outputPath(`step-${String(index).padStart(2, '0')}-${slugify(step)}.png`);
  await page.screenshot({ path: file, fullPage: true, mask });
  await testInfo.attach(`step ${String(index).padStart(2, '0')} - ${step}`, {
    path: file,
    contentType: 'image/png',
  });
}
