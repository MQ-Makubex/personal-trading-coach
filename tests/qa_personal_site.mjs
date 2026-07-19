import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const playwrightPath = process.env.CODEX_PLAYWRIGHT_MJS;
if (!playwrightPath) throw new Error('CODEX_PLAYWRIGHT_MJS is required');
const {chromium} = await import(pathToFileURL(playwrightPath).href);
const baseUrl = process.argv[2] || 'http://127.0.0.1:8765';
const outputDir = process.argv[3] || 'reports/personal_site/qa';
fs.mkdirSync(outputDir, {recursive: true});
const browser = await chromium.launch({headless: true});

async function inspect(name, viewport) {
  const page = await browser.newPage({viewport});
  await page.goto(`${baseUrl}/index.html`, {waitUntil: 'networkidle'});
  const totalBefore = await page.locator('[data-account-total]').textContent();
  const home = await page.evaluate(() => {
    const root = document.documentElement;
    const pool = document.querySelector('[data-pool-scroll]');
    const discipline = document.querySelector('[data-discipline-feed]');
    return {
      noHorizontalScroll: root.scrollWidth <= root.clientWidth + 1,
      poolRows: document.querySelectorAll('[data-pool-row]').length,
      poolInternalScroll: pool ? pool.scrollHeight >= pool.clientHeight : false,
      disciplineContained: discipline ? discipline.scrollHeight >= discipline.clientHeight : false,
      headingsDoNotOverlap: Array.from(document.querySelectorAll('h1,h2,h3')).every(node => node.scrollWidth <= node.parentElement.scrollWidth + 1)
    };
  });
  await page.screenshot({path: path.join(outputDir, `home-${name}.png`), fullPage: true});
  const disciplineStart = await page.locator('[data-discipline-feed]').evaluate(node => node.scrollTop);
  await page.waitForTimeout(6500);
  const disciplineEnd = await page.locator('[data-discipline-feed]').evaluate(node => node.scrollTop);
  home.disciplineAutoScrolls = disciplineEnd > disciplineStart;

  await page.goto(`${baseUrl}/ledger.html?grain=month&period=2026-07`, {waitUntil: 'networkidle'});
  const ledgerAccountFact = () => page.locator('[data-current-account-facts] .metric-primary > strong').textContent();
  const ledgerTotal = await ledgerAccountFact();
  await page.locator('[data-ledger-grain="custom"]').click();
  await page.locator('#ledgerFrom').fill('2026-07-01');
  await page.locator('#ledgerTo').fill('2026-07-10');
  await page.locator('[data-ledger-apply-custom]').click();
  const customUrlUpdated = page.url().includes('grain=custom') && page.url().includes('from=2026-07-01') && page.url().includes('to=2026-07-10');
  const ledgerTotalAfterCustom = await ledgerAccountFact();
  await page.reload({waitUntil: 'networkidle'});
  const ledgerTotalAfterCustomReload = await ledgerAccountFact();
  const customRestored = (await page.locator('#ledgerFrom').inputValue()) === '2026-07-01' && (await page.locator('#ledgerTo').inputValue()) === '2026-07-10';
  await page.goto(`${baseUrl}/ledger.html?grain=month&period=2026-07`, {waitUntil: 'networkidle'});
  const ledgerTotalBeforeNavigation = await ledgerAccountFact();
  const monthLabel = await page.locator('[data-ledger-period-label]').textContent();
  await page.locator('[data-ledger-prev]').click();
  const urlChanged = page.url().includes('grain=month') && !page.url().includes('period=2026-07');
  const ledgerTotalAfterPeriodNavigation = await ledgerAccountFact();
  await page.goBack();
  const historyRestored = (await page.locator('[data-ledger-period-label]').textContent()) === monthLabel;
  const ledgerTotalAfterHistoryRestore = await ledgerAccountFact();
  await page.locator('#ledgerSearch').fill('300260');
  await page.waitForFunction(() => new URLSearchParams(location.search).get('q') === '300260');
  const searchUrlUpdated = page.url().includes('q=300260');
  await page.screenshot({path: path.join(outputDir, `ledger-${name}.png`), fullPage: true});

  await page.goto(`${baseUrl}/stories.html?status=all`, {waitUntil: 'networkidle'});
  const storyLink = page.locator('a[href^="stocks/"]').first();
  const storyExists = await storyLink.count() > 0;
  let cycleUrlUpdated = false;
  if (storyExists) {
    await storyLink.click();
    const cycleButtons = page.locator('[data-cycle-option]');
    const cycleCount = await cycleButtons.count();
    if (cycleCount > 1) {
      await cycleButtons.nth(1).click();
      cycleUrlUpdated = page.url().includes('cycle=');
    } else {
      cycleUrlUpdated = cycleCount === 1;
    }
  }
  await page.goto(`${baseUrl}/modes.html`, {waitUntil: 'networkidle'});
  await page.locator('[data-mode-filter="validating"]').click();
  const modeUrlUpdated = page.url().includes('status=validating');
  await page.goto(`${baseUrl}/mentor.html`, {waitUntil: 'networkidle'});
  const mentorSkipLinkHidden = await page.locator('.skip-link').evaluate(node => node.getBoundingClientRect().bottom <= 0);
  const mentorModeCountCorrect = await page.locator('[data-mentor-item]').count() === 13;
  await page.locator('[data-mentor-filter="short_term"]').click();
  const mentorUrlUpdated = page.url().includes('horizon=short_term');
  const mentorVisibleCards = await page.locator('[data-mentor-item]:visible').count();
  const mentorFilterWorks = mentorVisibleCards === 4;
  await page.locator('#mentorSearch').fill('做T');
  const mentorSearchWorks = await page.locator('[data-mentor-item]:visible').count() === 1;
  await page.screenshot({path: path.join(outputDir, `mentor-${name}.png`), fullPage: true});
  const fixedAccountFacts = [
    totalBefore,
    ledgerTotal,
    ledgerTotalAfterCustom,
    ledgerTotalAfterCustomReload,
    ledgerTotalBeforeNavigation,
    ledgerTotalAfterPeriodNavigation,
    ledgerTotalAfterHistoryRestore
  ];
  return Object.assign({}, home, {
    accountFactsFixed: fixedAccountFacts.every(value => value === totalBefore),
    customUrlUpdated,
    customRestored,
    urlChanged,
    historyRestored,
    searchUrlUpdated,
    storyExists,
    cycleUrlUpdated,
    modeUrlUpdated,
    mentorSkipLinkHidden,
    mentorModeCountCorrect,
    mentorUrlUpdated,
    mentorFilterWorks,
    mentorSearchWorks
  });
}

const results = {
  desktop: await inspect('desktop', {width: 1440, height: 1080}),
  mobile: await inspect('mobile', {width: 390, height: 844})
};
await browser.close();
const reportJson = JSON.stringify(results, null, 2);
fs.writeFileSync(path.join(outputDir, 'report.json'), `${reportJson}\n`);
console.log(reportJson);
const failures = Object.entries(results).flatMap(([viewport, report]) =>
  Object.entries(report).filter(([, value]) => value !== true && value !== 15).map(([key]) => `${viewport}.${key}`)
);
if (results.desktop.poolRows !== 15 || results.mobile.poolRows !== 15) failures.push('poolRows');
if (failures.length) {
  console.error(`QA_FAILED: ${failures.join(', ')}`);
  process.exitCode = 1;
}
