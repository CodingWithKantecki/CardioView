// Headless screenshot of the running viewer. Usage: node screenshot.mjs [url] [out.png]
// Waits WAIT_MS (default 9000) so the 3 s warm-up and the 1.5 s delay pass, prints what the screen shows.
// ASK="a question" opens the chat and asks it first (this calls Gemini for real); ASK=1 only opens it.
import fs from 'node:fs';
import path from 'node:path';
import puppeteer from 'puppeteer-core';

const url = process.argv[2] || 'http://localhost:8000/';
const out = process.argv[3] || path.join(path.dirname(new URL(import.meta.url).pathname), 'out', 'screen.png');
const waitMs = Number(process.env.WAIT_MS || 9000);
const chrome = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const ask = process.env.ASK || '';
const keys = (process.env.KEYS || '').split(',').filter(Boolean);   // KEYS="w,c" presses keys before the shot
const drag = process.env.DRAG === '1';   // DRAG=1 orbits the heart with a mouse drag first

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
  if (drag) {
    const st = await page.$eval('.stage', (el) => el.getBoundingClientRect().toJSON());
    await page.mouse.move(st.left + st.width * 0.5, st.top + st.height * 0.5);
    await page.mouse.down();
    await page.mouse.move(st.left + st.width * 0.75, st.top + st.height * 0.35, { steps: 12 });
    await page.mouse.up();
    await new Promise((r) => setTimeout(r, 1200));   // damping settles
  }
  for (const k of keys) { await page.keyboard.press(k); await new Promise((r) => setTimeout(r, 300)); }
  if (ask) {
    await page.click('#chat-open');
    if (ask !== '1') {
      await page.type('#chat-input', ask);
      await page.keyboard.press('Enter');
      await page.waitForFunction(() => !document.querySelector('.msg.pending'), { timeout: 45000 }).catch(() => {});
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  const info = await page.evaluate(() => ({
    chat: [...document.querySelectorAll('.msg')].map((m) => m.textContent),
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
