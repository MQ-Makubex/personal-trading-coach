import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const playwrightPath = process.env.CODEX_PLAYWRIGHT_MJS;
if (!playwrightPath) throw new Error('CODEX_PLAYWRIGHT_MJS is required');
const {chromium} = await import(pathToFileURL(playwrightPath).href);
const baseUrl = process.argv[2] || 'http://127.0.0.1:8766';
const outputDir = process.argv[3] || 'reports/personal_site/qa-local';
fs.mkdirSync(outputDir, {recursive: true});
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
const browser = await chromium.launch(Object.assign({headless: true}, executablePath ? {executablePath} : {}));
const page = await browser.newPage({viewport: {width: 1440, height: 1080}});

await page.goto(`${baseUrl}/mode-validation.html`, {waitUntil: 'networkidle'});
await page.waitForFunction(() => document.querySelector('[data-mode-validation-surface]')?.textContent?.trim() === '本机可写');
const localSurfaceReady = await page.locator('[data-local-write]').count() > 0;
const tokenNotPersisted = await page.evaluate(() => (
  !location.href.includes('token') && localStorage.length === 0 && sessionStorage.length === 0
));

const createTask = page.getByRole('button', {name: '建立验证任务'});
if (await createTask.count()) {
  await createTask.click();
  await page.waitForFunction(() => document.querySelectorAll('.mode-validation-proposition').length === 4);
}
await page.getByRole('tab', {name: '模式命题'}).click();
const propositionCount = await page.locator('.mode-validation-proposition').count();
const confirm = page.getByRole('button', {name: '确认命题'}).first();
if (await confirm.count()) {
  await confirm.click();
  await page.waitForFunction(() => document.querySelectorAll('button').length > 0 && !Array.from(document.querySelectorAll('button')).some(button => button.disabled));
}
await page.getByRole('tab', {name: '验证运行'}).click();
const runComposerVisible = await page.locator('.mode-validation-composer').first().isVisible();
const noHorizontalScroll = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
await page.screenshot({path: path.join(outputDir, 'mode-validation-local-desktop.png'), fullPage: true});

const mobile = await browser.newPage({viewport: {width: 390, height: 844}});
await mobile.goto(`${baseUrl}/mode-validation.html?tab=runs`, {waitUntil: 'networkidle'});
await mobile.waitForFunction(() => document.querySelector('[data-mode-validation-surface]')?.textContent?.trim() === '本机可写');
const mobileNoHorizontalScroll = await mobile.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
const mobileRunComposerVisible = await mobile.locator('.mode-validation-composer').first().isVisible();
await mobile.screenshot({path: path.join(outputDir, 'mode-validation-local-mobile.png'), fullPage: true});

await browser.close();
const report = {
  localSurfaceReady,
  tokenNotPersisted,
  propositionCountIsFour: propositionCount === 4,
  runComposerVisible,
  noHorizontalScroll,
  mobileNoHorizontalScroll,
  mobileRunComposerVisible
};
console.log(JSON.stringify(report, null, 2));
const failures = Object.entries(report).filter(([, value]) => value !== true).map(([key]) => key);
if (failures.length) {
  console.error(`QA_LOCAL_FAILED: ${failures.join(', ')}`);
  process.exitCode = 1;
}
