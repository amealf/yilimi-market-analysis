import assert from "node:assert/strict";
import http from "node:http";
import { mkdir, readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { extname, join, normalize } from "node:path";
import os from "node:os";

const require = createRequire(import.meta.url);
function loadPlaywright() {
  try { return require("playwright"); }
  catch {
    return require(join(os.homedir(), ".cache", "codex-runtimes", "codex-primary-runtime", "dependencies", "node", "node_modules", "playwright"));
  }
}
const { chromium } = loadPlaywright();

const [root, screenshotDir] = process.argv.slice(2);
if (!root) throw new Error("Usage: node tests/market_intuition_selector_privacy_qa.mjs <site-directory> [screenshot-directory]");
const types = { ".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8", ".csv": "text/csv; charset=utf-8" };
const server = http.createServer(async (request, response) => {
  try {
    const relative = decodeURIComponent(new URL(request.url, "http://local").pathname).replace(/^\/+/, "") || "index.html";
    const file = normalize(join(root, relative));
    if (!file.startsWith(normalize(root))) throw new Error("outside site");
    response.writeHead(200, { "content-type": types[extname(file)] || "application/octet-stream" });
    response.end(await readFile(file));
  } catch { response.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const port = server.address().port;
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
const page = await context.newPage();
const url = `http://127.0.0.1:${port}/charts/intraday-analysis/k200-market-intuition-selector.html`;
const validCsv = "time,open,high,low,close\n2026-07-28 09:00:00,100,102,99,101\n2026-07-28 09:00:15,101,103,100,102\n";
const invalidCsv = "time,open,high,low,close\nnot-a-time,100,102,99,101\n";
try {
  await page.goto(url, { waitUntil: "networkidle", timeout: 120000 });
  await page.waitForFunction(() => window.MARKET_INTUITION_SELECTOR_READY === true, { timeout: 120000 });
  assert.match(await page.locator("#chartTitle").textContent(), /K200/);
  assert.equal(await page.locator("#body tr").count(), 0);

  const uploadRequests = [];
  page.on("request", request => uploadRequests.push(request.url()));
  await page.locator("#file").setInputFiles({ name: "local.csv", mimeType: "text/csv", buffer: Buffer.from(validCsv) });
  await page.waitForSelector("#mapping.show");
  await page.locator("#applyMap").click();
  await page.waitForFunction(() => document.querySelector("#chartTitle").textContent.includes("local.csv"), { timeout: 30000 });
  assert.equal(uploadRequests.length, 0, "upload must not issue a network request");
  const plot = await page.locator("#chart .nsewdrag").boundingBox();
  assert.ok(plot, "custom-data chart must render");
  await page.mouse.move(plot.x + plot.width * 0.25, plot.y + plot.height * 0.3);
  await page.mouse.down();
  await page.mouse.move(plot.x + plot.width * 0.75, plot.y + plot.height * 0.7, { steps: 8 });
  await page.mouse.up();
  await page.waitForFunction(() => document.querySelectorAll("#body tr").length === 1, { timeout: 30000 });
  assert.match(await page.locator("#body tr").first().textContent(), /行情 1/);
  const persistence = await page.evaluate(async () => ({ local: localStorage.length, session: sessionStorage.length, cookies: document.cookie, indexed: (await indexedDB.databases()).length }));
  assert.deepEqual(persistence, { local: 0, session: 0, cookies: "", indexed: 0 });

  await page.locator("#file").setInputFiles({ name: "invalid.csv", mimeType: "text/csv", buffer: Buffer.from(invalidCsv) });
  await page.waitForSelector("#mapping.show");
  await page.locator("#applyMap").click();
  await page.waitForFunction(() => document.querySelector("#status").textContent.includes("不是有效数值"), { timeout: 30000 });
  assert.match(await page.locator("#chartTitle").textContent(), /local\.csv/, "invalid input must not replace the active in-memory dataset");

  await page.locator("#dark").click();
  assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), "dark");
  assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth)), 0);
  if (screenshotDir) { await mkdir(screenshotDir, { recursive: true }); await page.screenshot({ path: join(screenshotDir, "market-intuition-mobile-dark.png"), fullPage: true }); }

  await page.reload({ waitUntil: "networkidle", timeout: 120000 });
  await page.waitForFunction(() => window.MARKET_INTUITION_SELECTOR_READY === true, { timeout: 120000 });
  assert.match(await page.locator("#chartTitle").textContent(), /K200/);
  assert.equal(await page.locator("#body tr").count(), 0, "reload must restore an empty selection state");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.waitForTimeout(300);
  assert.equal(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth)), 0);
  if (screenshotDir) await page.screenshot({ path: join(screenshotDir, "market-intuition-desktop-default.png"), fullPage: true });
  console.log("market-intuition privacy QA passed");
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
