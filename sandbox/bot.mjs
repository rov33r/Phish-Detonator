// Robot visit (docs/SPEC.md 5.3): what an automated scanner sees. Default flags, no evasion, no clicks.
// Usage: node bot.mjs <url>. Exits 1 when the page could not be loaded; robot.json is written either way.
import { appendFileSync, writeFileSync } from 'node:fs';
import { chromium } from 'playwright';
import { isLockBlock } from './netlock.mjs';

const OUT = process.env.PD_OUT || '/out';
const url = process.argv[2];
if (!url) {
  console.error('usage: node bot.mjs <url>');
  process.exit(2);
}

const log = (name, item) => appendFileSync(`${OUT}/${name}.jsonl`, JSON.stringify({ ts: Date.now() / 1000, ...item }) + '\n');
const hostOf = (link) => { try { return new URL(link).hostname; } catch { return ''; } };
// A hostile page can hang or lack a body; every read has a fallback so robot.json is still written.
const attempt = (promise, fallback) => Promise.race([
  promise.catch(() => fallback),
  new Promise((resolve) => setTimeout(resolve, 5000, fallback).unref()),
]);

const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
const context = await browser.newContext();
const page = await context.newPage();
let status = null;

context.on('request', (request) => log('network', {
  method: request.method(), url: request.url(), host: hostOf(request.url()),
  resourceType: request.resourceType(), postData: request.postData()?.slice(0, 4096) ?? null,
}));
context.on('requestfailed', (request) => {
  const error = request.failure()?.errorText ?? '';
  log(isLockBlock(request.url(), error) ? 'blocked' : 'failed', { url: request.url(), host: hostOf(request.url()), error });
});
page.on('framenavigated', (frame) => {
  if (frame === page.mainFrame()) log('navigations', { url: frame.url() });
});
page.on('response', (response) => {
  if (response.request().isNavigationRequest() && response.frame() === page.mainFrame()) status = response.status();
});
page.on('crash', () => log('crash', { url: page.url() }));

let error = null;
try {
  await page.goto(url, { waitUntil: 'load', timeout: 20000 });
} catch (failure) {
  error = failure.message.split('\n')[0];
}
await new Promise((resolve) => setTimeout(resolve, 5000));

await attempt(page.screenshot({ path: `${OUT}/final.png`, timeout: 5000 }), null);
const robot = {
  final_url: page.url(),
  title: await attempt(page.title(), ''),
  text: (await attempt(page.innerText('body', { timeout: 5000 }), '')).slice(0, 4000),
  status,
  has_password_field: await attempt(page.locator('input[type=password]').count(), 0) > 0,
  error,
};
writeFileSync(`${OUT}/robot.json`, JSON.stringify(robot, null, 2));
console.log(JSON.stringify({ final_url: robot.final_url, title: robot.title, status, has_password_field: robot.has_password_field, error }));
await attempt(browser.close(), null);
process.exit(error ? 1 : 0);
