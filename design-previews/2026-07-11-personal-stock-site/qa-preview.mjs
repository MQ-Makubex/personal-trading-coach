import {chromium} from '/Users/makubex/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const target = pathToFileURL(path.join(root, 'index.html')).href;
const browser = await chromium.launch({headless: true});

async function inspect(name, viewport) {
  const page = await browser.newPage({viewport});
  await page.goto(target, {waitUntil: 'load'});
  await page.evaluate(() => document.fonts.ready);

  const report = await page.evaluate(() => {
    const doc = document.documentElement;
    const options = Array.from(document.querySelectorAll('.option'));
    const roots = ['.dir-a', '.dir-b', '.dir-c', '.dir-d'].map(selector => document.querySelector(selector));
    const mockBounds = Array.from(document.querySelectorAll('.mock')).map(mock => {
      const rect = mock.getBoundingClientRect();
      const stage = mock.querySelector('.stage-scale').getBoundingClientRect();
      return {
        mock: [Math.round(rect.width), Math.round(rect.height)],
        stage: [Math.round(stage.width), Math.round(stage.height)],
        delta: [Math.round(Math.abs(rect.width - stage.width)), Math.round(Math.abs(rect.height - stage.height))],
        covers: stage.width >= rect.width - 2 && stage.height >= rect.height - 2,
        centered: Math.abs((stage.left + stage.width / 2) - (rect.left + rect.width / 2)) <= 2
      };
    });
    return {
      noHorizontalScroll: doc.scrollWidth <= doc.clientWidth + 1,
      optionCount: options.length,
      pickButtonCount: document.querySelectorAll('.qmdp-pick-button').length,
      directionRootsPresent: roots.every(Boolean),
      mockBounds
    };
  });

  await page.locator('[data-qmdp-dial="variance"]').evaluate(input => {
    input.value = '7';
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
  report.dialOutputUpdates = await page.locator('[data-qmdp-output="variance"]').textContent() === '7';
  await page.locator('[data-qmdp-dial="variance"]').evaluate(input => {
    input.value = '5';
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });

  await page.locator('.qmdp-pick-button').first().click();
  report.clickOpensConfirm = await page.locator('#confirm').evaluate(node => node.classList.contains('open'));
  report.confirmFocus = await page.evaluate(() => document.activeElement?.id === 'adjustments');
  await page.locator('#cancelPick').click();

  await page.keyboard.press('4');
  report.keyboardOpensD = (await page.locator('#confirmMeta').textContent()).includes('选 D');
  await page.locator('#cancelPick').click();
  await page.evaluate(() => document.querySelectorAll('.option.selected').forEach(node => node.classList.remove('selected')));

  await page.screenshot({path: path.join(root, `qa-${name}.png`), fullPage: true});
  await page.close();
  return report;
}

const results = {
  desktop: await inspect('desktop', {width: 1440, height: 1080}),
  mobile: await inspect('mobile', {width: 390, height: 844})
};

await browser.close();
console.log(JSON.stringify(results, null, 2));

const failures = Object.entries(results).flatMap(([name, report]) => {
  const required = ['noHorizontalScroll', 'directionRootsPresent', 'dialOutputUpdates', 'clickOpensConfirm', 'confirmFocus', 'keyboardOpensD'];
  const bad = required.filter(key => report[key] !== true).map(key => `${name}.${key}`);
  if (report.optionCount !== 4) bad.push(`${name}.optionCount`);
  if (report.pickButtonCount !== 4) bad.push(`${name}.pickButtonCount`);
  if (name === 'desktop' && report.mockBounds.some(item => item.delta[0] > 2 || item.delta[1] > 2)) bad.push(`${name}.mockFit`);
  if (name === 'mobile' && report.mockBounds.some(item => !item.covers || !item.centered)) bad.push(`${name}.mockCrop`);
  return bad;
});

if (failures.length) {
  console.error(`QA_FAILED: ${failures.join(', ')}`);
  process.exitCode = 1;
}
