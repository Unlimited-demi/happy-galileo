/**
 * Playwright Headless Visual & Diagnostic Test Runner
 * Analyzes pages, collects console logs, network errors, and captures full-page & mobile screenshots.
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

async function runTest(targetUrl, outputDir, options = {}) {
  const result = {
    url: targetUrl,
    timestamp: new Date().toISOString(),
    success: false,
    httpStatus: null,
    loadTimeMs: 0,
    pageTitle: '',
    consoleErrors: [],
    consoleWarnings: [],
    networkFailures: [],
    screenshots: {
      desktop: null,
      mobile: null,
    },
    criticalIssues: [],
  };

  fs.mkdirSync(outputDir, { recursive: true });

  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  const startTime = Date.now();

  try {
    // 1. Desktop Test & Screenshot
    const contextDesktop = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      ignoreHTTPSErrors: true,
    });
    const page = await contextDesktop.newPage();

    // Listen for console events
    page.on('console', (msg) => {
      const type = msg.type();
      const text = msg.text();
      if (type === 'error') {
        result.consoleErrors.push(text);
      } else if (type === 'warning') {
        result.consoleWarnings.push(text);
      }
    });

    // Listen for page errors (unhandled exceptions)
    page.on('pageerror', (err) => {
      result.consoleErrors.push(`Uncaught Exception: ${err.message}\n${err.stack || ''}`);
    });

    // Listen for failed network requests
    page.on('requestfailed', (req) => {
      result.networkFailures.push({
        url: req.url(),
        method: req.method(),
        failure: req.failure() ? req.failure().errorText : 'Failed',
      });
    });

    page.on('response', (res) => {
      const status = res.status();
      if (status >= 400) {
        result.networkFailures.push({
          url: res.url(),
          method: res.request().method(),
          status: status,
          statusText: res.statusText(),
        });
      }
    });

    // Navigate
    const response = await page.goto(targetUrl, {
      waitUntil: 'networkidle',
      timeout: 30000,
    }).catch(async () => {
      // Fallback to load event if networkidle times out
      return await page.goto(targetUrl, { waitUntil: 'load', timeout: 15000 });
    });

    result.loadTimeMs = Date.now() - startTime;
    if (response) {
      result.httpStatus = response.status();
    }
    result.pageTitle = await page.title().catch(() => '');

    // Take Desktop Screenshot
    const desktopPath = path.join(outputDir, 'desktop.png');
    await page.screenshot({ path: desktopPath, fullPage: true });
    result.screenshots.desktop = desktopPath;

    await contextDesktop.close();

    // 2. Mobile Viewport Test (iPhone 14 standard: 390x844)
    const contextMobile = await browser.newContext({
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
      userAgent:
        'Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1',
      ignoreHTTPSErrors: true,
    });
    const mobilePage = await contextMobile.newPage();
    await mobilePage.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 20000 }).catch(() => {});
    
    const mobilePath = path.join(outputDir, 'mobile.png');
    await mobilePage.screenshot({ path: mobilePath, fullPage: true });
    result.screenshots.mobile = mobilePath;

    await contextMobile.close();

    // Evaluate success criteria
    const isStatusOk = result.httpStatus !== null && result.httpStatus < 400;
    const noCrashErrors = result.consoleErrors.length === 0;
    result.success = isStatusOk && noCrashErrors;

    if (!isStatusOk) {
      result.criticalIssues.push(`HTTP status returned ${result.httpStatus || 'CONNECTION_FAILED'}`);
    }
    if (result.consoleErrors.length > 0) {
      result.criticalIssues.push(`Found ${result.consoleErrors.length} uncaught console errors.`);
    }
    if (result.networkFailures.length > 0) {
      result.criticalIssues.push(`Found ${result.networkFailures.length} failed sub-resource/API requests.`);
    }

  } catch (err) {
    result.success = false;
    result.criticalIssues.push(`Test execution crashed: ${err.message}`);
  } finally {
    await browser.close();
  }

  // Write output report JSON
  const reportPath = path.join(outputDir, 'report.json');
  fs.writeFileSync(reportPath, JSON.stringify(result, null, 2));

  console.log(JSON.stringify(result));
}

// CLI args: node runner.js <url> <outputDir>
const args = process.argv.slice(2);
if (args.length < 2) {
  console.error('Usage: node runner.js <url> <outputDir>');
  process.exit(1);
}

runTest(args[0], args[1]);
