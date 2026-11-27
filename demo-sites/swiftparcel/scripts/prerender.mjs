import { readFile, readdir, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const root = process.cwd();
const serverBundle = pathToFileURL(resolve(root, ".prerender/entry-server.js"));

try {
  const { render } = await import(serverBundle.href);
  const output = resolve(root, "dist/index.html");
  let html = await readFile(output, "utf8");
  const markup = render();
  const stylesheet = (await readdir(resolve(root, "dist/assets")))
    .find((file) => file.endsWith(".css"));

  if (!stylesheet) throw new Error("Vite did not emit the app stylesheet.");
  const css = await readFile(resolve(root, "dist/assets", stylesheet), "utf8");
  html = html.replace('<div id="root"></div>', `<div id="root">${markup}</div>`);
  html = html.replace(/<link rel="stylesheet"[^>]*href="[^"]+"[^>]*>/, `<style>${css}</style>`);
  if (!html.includes(`<style>${css}</style>`) || !html.includes('id="root"><')
      || !html.includes("Good things") || !html.includes("SP-2048-7721")) {
    throw new Error("Prerender output did not include inline styles and landing page markup.");
  }
  await writeFile(output, html);
} finally {
  await rm(resolve(root, ".prerender"), { recursive: true, force: true });
}
