// Headless screenshot of the running viewer. Usage: node screenshot.mjs [url] [out.png]
// Waits WAIT_MS (default 9000) so the 3 s warm-up and the 1.5 s delay pass, prints what the screen shows.
import fs from 'node:fs';
import path from 'node:path';
import puppeteer from 'puppeteer-core';

const url = process.argv[2] || 'http://localhost:8000/';
const out = process.argv[3] || path.join(path.dirname(new URL(import.meta.url).pathname), 'out', 'screen.png');
const waitMs = Number(process.env.WAIT_MS || 9000);
const chrome = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

fs.mkdirSync(path.dirname(out), { recursive: true });
const browser = await puppeteer.launch({
  executablePath: chrome,
  headless: true,
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--no-sandbox', '--hide-scrollbars'],
});
try {
  const page = await browser.newPage();
  await page.setViewport({ width: Number(process.env.W || 1920), height: Number(process.env.H || 1080), deviceScaleFactor: 1 });
  page.on('console', (m) => console.log('[page]', m.text()));
  page.on('pageerror', (e) => console.log('[pageerror]', e.message));
  await page.goto(url, { waitUntil: 'load' });
  await new Promise((r) => setTimeout(r, waitMs));
  const info = await page.evaluate(() => ({
    header: document.getElementById('conn')?.textContent,
    bpm: document.getElementById('bpm')?.textContent,
    rr: document.getElementById('rr')?.textContent,
    modelMissing: !document.getElementById('heart-missing')?.hidden,
  }));
  console.log(JSON.stringify(info));
  await page.screenshot({ path: out });
  console.log('saved', out);
} finally {
  await browser.close();
}
