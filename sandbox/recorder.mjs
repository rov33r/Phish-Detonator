// Records what the victim visit does and applies the visit profile (docs/SPEC.md 5.5, 6A.4).
// It must stay connected: CDP overrides last only as long as the session that set them.
import { appendFileSync, writeFileSync } from 'node:fs';
import { chromium } from 'playwright';

const OUT = process.env.PD_OUT || '/out';
const PROFILE = process.env.PD_PROFILE || 'victim';

const log = (name, item) => appendFileSync(`${OUT}/${name}.jsonl`, JSON.stringify({ ts: Date.now() / 1000, ...item }) + '\n');
const hostOf = (url) => { try { return new URL(url).hostname; } catch { return ''; } };

// Absent properties go on the prototype: bot detectors list the window's and document's own properties.
const probeScript = () => {
  const report = (name) => console.debug('__PD_PROBE', name);
  const wrap = (target, name, label, value) => Object.defineProperty(target, name, {
    configurable: true,
    get() { report(label); return value; },
  });
  wrap(Navigator.prototype, 'webdriver', 'navigator.webdriver', false);
  for (const name of ['_selenium', 'callPhantom', '__nightmare']) {
    wrap(Window.prototype, name, `window.${name}`, undefined);
  }
  for (const name of ['$cdc_asdjflasutopfhvcZLmcfl_', '$chrome_asyncScriptInfo', '__webdriver_evaluate']) {
    wrap(Document.prototype, name, `document.${name}`, undefined);
  }
};

// A CDP override on a new tab races the first navigation, so what a page checks at load is also set here.
const deviceScript = (mobile) => {
  const fix = (name, value) => Object.defineProperty(Navigator.prototype, name, { configurable: true, get: () => value });
  fix('hardwareConcurrency', 8);
  if (!mobile) return;
  fix('maxTouchPoints', 5);
  if (!('ontouchstart' in window)) window.ontouchstart = null;
};

const ANDROID_UA = (major) =>
  `Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${major}.0.0.0 Mobile Safari/537.36`;

const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
const context = browser.contexts()[0];
const major = browser.version().split('.')[0];

async function applyProfile(page) {
  const cdp = await context.newCDPSession(page);
  await cdp.send('Emulation.setHardwareConcurrencyOverride', { hardwareConcurrency: 8 });
  await cdp.send('Emulation.setTimezoneOverride', { timezoneId: 'Europe/Stockholm' });
  if (PROFILE !== 'victim_mobile') return;
  await cdp.send('Emulation.setUserAgentOverride', {
    userAgent: ANDROID_UA(major),
    acceptLanguage: 'sv-SE',
    platform: 'Android',
    userAgentMetadata: {
      platform: 'Android', platformVersion: '10.0.0', architecture: '', model: 'K', mobile: true,
      brands: [{ brand: 'Chromium', version: major }, { brand: 'Google Chrome', version: major }],
    },
  });
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 412, height: 915, deviceScaleFactor: 2.625, mobile: true });
  await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
}

function watch(page) {
  page.on('framenavigated', (frame) => {
    if (frame === page.mainFrame()) log('navigations', { url: frame.url() });
  });
  page.on('console', async (message) => {
    if (!message.text().startsWith('__PD_PROBE') || message.args().length < 2) return;
    try { log('probes', { name: await message.args()[1].jsonValue() }); } catch { /* page already gone */ }
  });
  page.on('crash', () => log('crash', { url: page.url() }));
  return applyProfile(page).catch((error) => console.error('profile failed:', error.message));
}

context.on('request', (request) => log('network', {
  method: request.method(), url: request.url(), host: hostOf(request.url()),
  resourceType: request.resourceType(), postData: request.postData()?.slice(0, 4096) ?? null,
}));
context.on('requestfailed', (request) => log('blocked', {
  url: request.url(), host: hostOf(request.url()), error: request.failure()?.errorText ?? '',
}));

await context.addInitScript(probeScript);
await context.addInitScript(deviceScript, PROFILE === 'victim_mobile');
context.on('page', watch);
await Promise.all(context.pages().map(watch));

writeFileSync('/tmp/recorder.ready', PROFILE);
console.log(`recorder ready (${PROFILE})`);
browser.on('disconnected', () => process.exit(0));
