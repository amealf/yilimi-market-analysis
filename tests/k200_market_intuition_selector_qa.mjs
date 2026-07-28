import fs from "node:fs";
import {createRequire} from "node:module";
import os from "node:os";
import path from "node:path";
import {spawn} from "node:child_process";

const require = createRequire(import.meta.url);
const playwright = (() => {
  try { return require("playwright"); }
  catch { return require(path.join(os.homedir(), ".cache", "codex-runtimes", "codex-primary-runtime", "dependencies", "node", "node_modules", "playwright")); }
})();
const suppliedBase = process.argv[2];
const base = suppliedBase || "http://127.0.0.1:8033";
const output = path.resolve(process.argv[3] || "k200-selector-qa");
fs.mkdirSync(output, {recursive: true});
const server = suppliedBase ? null : spawn(process.execPath,["tests/local_static_server.mjs"],{stdio:"ignore"});
if(server) await new Promise(resolve=>setTimeout(resolve,400));
const browser = await playwright.chromium.launch({headless:true});
const errors=[];
async function pageFor(viewport){
  const page=await browser.newPage({viewport});
  page.on("console", m=>{if(m.type()==="error")errors.push(m.text())});
  page.on("pageerror", e=>errors.push(e.message));
  return page;
}
const page=await pageFor({width:1440,height:900});
await page.goto(base+"/k200-market-intuition-selector.html",{waitUntil:"domcontentloaded",timeout:120000});
await page.waitForFunction(()=>window.MARKET_INTUITION_SELECTOR_READY&&window.MARKET_INTUITION_SELECTOR.data?.count===199200,{timeout:180000});
await page.waitForFunction(()=>document.querySelector("#chart .js-plotly-plot"),{timeout:60000});
await page.screenshot({path:path.join(output,"desktop-light.png"),fullPage:true});
await page.click("#dark");
await page.screenshot({path:path.join(output,"desktop-dark.png"),fullPage:true});
const requestCountBefore=await page.evaluate(()=>performance.getEntriesByType("resource").length);
await page.setInputFiles("#file",{name:"custom.tsv",mimeType:"text/tab-separated-values",buffer:Buffer.from("when\to\th\tl\tc\n2026-07-01 09:00:00\t10\t12\t9\t11\n2026-07-01 09:00:15\t11\t13\t10\t10\n")});
await page.waitForSelector("#mapping.show");
await page.click("#applyMap");
await page.waitForFunction(()=>window.MARKET_INTUITION_SELECTOR.data?.count===2,{timeout:30000});
const requestCountAfter=await page.evaluate(()=>performance.getEntriesByType("resource").length);
if(requestCountAfter!==requestCountBefore)throw new Error("user upload triggered a network request");
await page.setInputFiles("#file",{name:"invalid.csv",mimeType:"text/csv",buffer:Buffer.from("time,open,high,low,close\n2026-07-01 09:00:00,10,8,9,11\n")});
await page.waitForSelector("#mapping.show"); await page.click("#applyMap");
await page.waitForFunction(()=>document.querySelector("#status")?.textContent.includes("OHLC"),{timeout:30000});
await page.click("#restore");
await page.waitForFunction(()=>window.MARKET_INTUITION_SELECTOR.data?.count===199200,{timeout:180000});
await page.fill("#start","2026-07-20"); await page.fill("#end","2026-07-21"); await page.click("#apply");
await page.waitForFunction(()=>document.querySelector("#chart .js-plotly-plot"),{timeout:60000});
await page.evaluate(()=>Plotly.relayout("chart",{shapes:[{type:"rect",xref:"x",yref:"paper",x0:"2026-07-20T03:00:00",x1:"2026-07-20T09:00:00",y0:0,y1:1}]}));
await page.waitForFunction(()=>window.MARKET_INTUITION_SELECTOR.selections.length===1,{timeout:30000});
await page.reload({waitUntil:"domcontentloaded",timeout:120000});
await page.waitForFunction(()=>window.MARKET_INTUITION_SELECTOR_READY&&window.MARKET_INTUITION_SELECTOR.data?.count===199200,{timeout:180000});
const reset=await page.evaluate(()=>({selections:window.MARKET_INTUITION_SELECTOR.selections.length,storage:[localStorage.length,sessionStorage.length],overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth}));
if(reset.selections||reset.storage.some(Boolean)||reset.overflow)throw new Error("refresh did not reset the session cleanly");
const mobile=await pageFor({width:390,height:844});
await mobile.goto(base+"/k200-market-intuition-selector.html",{waitUntil:"domcontentloaded",timeout:120000});
await mobile.waitForFunction(()=>window.MARKET_INTUITION_SELECTOR_READY,{timeout:180000});
await mobile.waitForFunction(()=>document.querySelector("#chart .js-plotly-plot"),{timeout:60000});
await mobile.screenshot({path:path.join(output,"mobile-light.png"),fullPage:true});
const mobileOverflow=await mobile.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth);
if(mobileOverflow)throw new Error("mobile page has horizontal overflow");
await browser.close();
if(errors.length)throw new Error(errors.join("\n"));
fs.writeFileSync(path.join(output,"result.json"),JSON.stringify({passed:true,privacy:{uploadNetworkRequests:0,persistentStorage:"none"},reset,mobileOverflow},null,2));
