#!/usr/bin/env node
// Capture full-page screenshots of the Storybook screen stories for visual review.
// Usage: node scripts/screenshot-stories.mjs [--port 6006] [--start] [--out .screenshots/<label>]
//        [--only '^modelanvil-(screens|states)--'] [--widths 1440,768] [--themes light,dark] [--compare <dir>]
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, existsSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i === -1 ? fallback : process.argv[i + 1]; };
const flag = (name) => process.argv.includes(`--${name}`);
const port = Number(arg('port', '6006'));
const origin = `http://127.0.0.1:${port}`;
const out = resolve(arg('out', `.screenshots/${new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-')}`));
const only = new RegExp(arg('only', '^modelanvil-(screens|states)--'));
const widths = arg('widths', '1440,768').split(',').map(Number);
const themes = arg('themes', 'light,dark').split(',');
const compare = arg('compare', '');

let server;
if (flag('start')) {
  server = spawn('npx', ['storybook', 'dev', '--host', '127.0.0.1', '-p', String(port), '--ci', '--no-open'], { stdio: 'ignore' });
  process.on('exit', () => server?.kill());
}
for (let attempt = 0; ; attempt += 1) {
  try { if ((await fetch(`${origin}/index.json`)).ok) break; } catch { /* not ready */ }
  if (attempt > 120) throw new Error(`Storybook did not answer on ${origin}`);
  await new Promise((done) => setTimeout(done, 1000));
}

const index = await (await fetch(`${origin}/index.json`)).json();
const ids = Object.keys(index.entries).filter((id) => only.test(id));
mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const rows = [];
for (const width of widths) {
  for (const theme of themes) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: theme === 'dark' ? 'dark' : 'light', reducedMotion: 'reduce' });
    const page = await context.newPage();
    for (const id of ids) {
      const file = `${id}--${width}-${theme}.png`;
      let verified = true;
      await page.goto(`${origin}/iframe.html?id=${id}&viewMode=story`, { waitUntil: 'networkidle', timeout: 45000 });
      await page.evaluate((value) => { document.documentElement.dataset.theme = value; }, theme);
      await page.waitForSelector('#storybook-root[data-demo-verified="passed"]', { timeout: 20000 }).catch(() => { verified = false; });
      await page.waitForTimeout(400);
      await page.screenshot({ path: join(out, file), fullPage: true });
      rows.push({ id, width, theme, file, verified });
      console.log(`${verified ? 'ok     ' : 'unverif'} ${id} ${width} ${theme}`);
    }
    await context.close();
  }
}
await browser.close();
server?.kill();

if (compare) {
  const base = resolve(compare);
  const html = rows.map(({ file, id, width, theme }) => {
    const before = join(base, file);
    return `<section><h2>${id} · ${width} · ${theme}</h2><div class="pair">` +
      `<figure><figcaption>before</figcaption>${existsSync(before) ? `<img src="${relative(out, before)}">` : '<p>missing</p>'}</figure>` +
      `<figure><figcaption>after</figcaption><img src="${file}"></figure></div></section>`;
  }).join('\n');
  writeFileSync(join(out, 'index.html'), `<!doctype html><meta charset="utf-8"><title>Screenshot comparison</title>` +
    `<style>body{font:14px system-ui;margin:16px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}img{width:100%;border:1px solid #ccc}figcaption{font-weight:600;margin-bottom:4px}</style>${html}`);
  console.log(`comparison: ${join(out, 'index.html')}`);
}
console.log(`${rows.length} screenshots in ${out}${rows.some((row) => !row.verified) ? ' (some stories did not report demoVerified)' : ''}`);
