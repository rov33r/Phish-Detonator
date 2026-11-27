// Launches Chromium as a "bot" (plain headless) or a "victim" (headful, de-automated),
// records the fingerprint signals phishing kits check, runs BotD, takes a screenshot.
import { chromium } from 'playwright';
import { writeFileSync } from 'node:fs';

const [mode = 'bot', rt = 'unknown'] = process.argv.slice(2);
const victim = mode === 'victim';

const browser = await chromium.launch({
  headless: !victim,
  // --no-sandbox: Chrome's own sandbox is replaced by the container runtime (gVisor).
  args: ['--no-sandbox', ...(victim ? ['--disable-blink-features=AutomationControlled', '--window-size=1920,1080'] : [])],
  ignoreDefaultArgs: victim ? ['--enable-automation'] : [],
});

const ctx = await browser.newContext(
  victim ? { viewport: { width: 1920, height: 1080 }, locale: 'sv-SE', timezoneId: 'Europe/Stockholm' } : {},
);
const page = await ctx.newPage();

if (victim) {
  try {
    const cdp = await ctx.newCDPSession(page);
    await cdp.send('Emulation.setHardwareConcurrencyOverride', { hardwareConcurrency: 8 });
  } catch (e) {
    console.error('hardwareConcurrency override failed:', e.message);
  }
}

await page.goto('https://example.com', { waitUntil: 'load' });

const fp = await page.evaluate(async () => {
  let webgl = null;
  try {
    const gl = document.createElement('canvas').getContext('webgl');
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    webgl = gl.getParameter(ext.UNMASKED_RENDERER_WEBGL);
  } catch {}
  let botd;
  try {
    const m = await import('https://openfpcdn.io/botd/v1');
    botd = await (await m.load()).detect();
  } catch (e) {
    botd = 'error: ' + e.message;
  }
  return {
    webdriver: navigator.webdriver,
    userAgent: navigator.userAgent,
    hardwareConcurrency: navigator.hardwareConcurrency,
    deviceMemory: navigator.deviceMemory,
    plugins: navigator.plugins.length,
    languages: navigator.languages,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    screen: [screen.width, screen.height],
    windowChrome: !!window.chrome,
    webglRenderer: webgl,
    botd,
  };
});

await page.screenshot({ path: `/out/${rt}-${mode}.png` });
writeFileSync(`/out/${rt}-${mode}.json`, JSON.stringify(fp, null, 2));
console.log(JSON.stringify({ runtime: rt, mode, ...fp }));
await browser.close();
