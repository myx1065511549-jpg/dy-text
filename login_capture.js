const path = require('path');

const BASE = __dirname;
const AUTH_STATE = path.join(BASE, 'auth_state.local.json');
process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(BASE, '_internal', 'ms-playwright');
const { chromium } = require(path.join(BASE, '_internal', 'playwright', 'driver', 'package'));

(async () => {
  let browser;
  try {
    console.log('正在打开抖音登录页，请在浏览器中完成登录。');
    browser = await chromium.launch({ headless: false });
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto('https://www.douyin.com/', { waitUntil: 'domcontentloaded', timeout: 60000 });
    for (let i = 0; i < 600; i += 1) {
      const cookies = await context.cookies();
      const names = new Set(cookies.map(cookie => cookie.name));
      if (['sessionid', 'sessionid_ss', 'sid_guard'].some(name => names.has(name))) {
        await context.storageState({ path: AUTH_STATE });
        console.log(`登录态已保存：${AUTH_STATE}`);
        await new Promise(resolve => setTimeout(resolve, 2000));
        return;
      }
      await page.waitForTimeout(1000);
    }
    console.log('在限定时间内未检测到登录态。');
    process.exitCode = 2;
  } catch (error) {
    console.error(`登录窗口已关闭或登录失败：${error.message}`);
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
  }
})();
