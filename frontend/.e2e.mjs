import { chromium } from "playwright";
const EXE="/Users/geminilight/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell";
const b=await chromium.launch({executablePath:EXE});
const ctx=await b.newContext({viewport:{width:1440,height:900},deviceScaleFactor:2});
const p=await ctx.newPage();
const api=[], errs=[];
p.on("response",r=>{const u=r.url(); if(u.includes("/api/v1/")) api.push(`${r.status()} ${r.request().method()} ${u.split("/api/v1/")[1].slice(0,50)}`);});
p.on("pageerror",e=>errs.push(String(e).slice(0,90)));

await p.goto("http://localhost:5175/",{waitUntil:"load"}); await p.waitForTimeout(1200);
await p.click('text=Try as Guest'); await p.waitForTimeout(1200);
console.log("1. entered guest mode, auth_token =", await p.evaluate(()=>localStorage.getItem('auth_token')));

await p.fill('textarea','A three-tier web app: load balancer, two API servers, one database');
await p.waitForTimeout(300);
await p.click('button[aria-label*="enerate" i], button[title*="enerate" i]');
await p.waitForTimeout(1500);
console.log("2. reached", p.url());

// Confirm in the preflight dialog
const go = await p.$('text=Generate diagram');
if (go) { await go.click(); console.log("3. confirmed 'Generate diagram', waiting for the pipeline…"); }
else console.log("3. no preflight dialog found");

// The stream endpoint returns 200 the moment streaming starts, so completion
// has to be detected from actual state: a project landing in guest storage,
// or a terminal error toast.
let outcome = "timeout";
for (let i=0;i<40;i++){
  await p.waitForTimeout(5000);
  const st = await p.evaluate(()=>{
    let saved=0; try{saved=(JSON.parse(localStorage.getItem('evodiagram_guest_diagrams')||'[]')).length;}catch{}
    const toasts=[...document.querySelectorAll('[role="alert"],[role="status"]')].map(e=>e.textContent.trim()).filter(Boolean);
    const cv=document.querySelector('.excalidraw canvas');
    return {saved, toasts, canvas: cv?`${cv.width}x${cv.height}`:null};
  });
  if (i%3===0 || st.saved) console.log(`   t+${(i+1)*5}s saved=${st.saved} canvas=${st.canvas} ${JSON.stringify(st.toasts.slice(0,1))}`);
  if (st.saved>0) { outcome="generated"; console.log(`   ✅ 生成完成并落盘于 t+${(i+1)*5}s`); break; }
  if (st.toasts.some(t=>/stopped|failed|unavailable|错误|失败/i.test(t))) { outcome="failed"; console.log("   ❌ 失败:", st.toasts[0]); break; }
}
console.log("outcome:", outcome);
await p.screenshot({path:"/tmp/evoshots/guest-e2e-result.png"});
console.log("\n--- API calls ---"); console.log([...new Set(api)].join("\n")||"(none)");
console.log("--- page errors ---"); console.log([...new Set(errs)].join("\n")||"(none)");
console.log("--- guest diagrams saved locally ---");
console.log(await p.evaluate(()=>{const r=localStorage.getItem('evodiagram_guest_diagrams');
  try{const a=JSON.parse(r||'[]');return `${a.length} project(s): `+a.map(x=>x.summary||x.prompt?.slice(0,40)).join(" | ");}catch{return r;}}));
await b.close();
