import { readFileSync, writeFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { chromium } from 'playwright';
const dir=dirname(fileURLToPath(import.meta.url));
const sourceDir=resolve(dir,'../VA02-generation');
let source=readFileSync(resolve(sourceDir,'repro-budget.ts'),'utf8');
source=source.replace(/^import .* from 'node:.*';\n/gm,'');
source=source.replace("const mode=process.argv[2]??'node';","const mode='browser';");
source="import { installBrowserRuntime } from '../../../src/browser.ts';\ninstallBrowserRuntime();\n"+source;
source=source.slice(0,source.indexOf('const dir=dirname('))+ '\n(globalThis as any).__auditResult=output;';
const bundled=await build({stdin:{contents:source,resolveDir:sourceDir,sourcefile:'budget-browser-audit.ts',loader:'ts'},bundle:true,platform:'browser',conditions:['browser'],format:'esm',target:'es2022',write:false});
writeFileSync(resolve(dir,'budget-browser-bundle.js'),bundled.outputFiles[0].text);
const browser=await chromium.launch({headless:true});
try{
 const page=await browser.newPage();
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.addScriptTag({type:'module',content:bundled.outputFiles[0].text});
 try { await page.waitForFunction(()=>Boolean((globalThis as any).__auditResult),null,{timeout:15000}); } catch(error) { writeFileSync(resolve(dir,'budget-real-chromium-errors.json'),JSON.stringify({errors,message:String(error)},null,2)); throw error; }
 const result=await page.evaluate(()=>(globalThis as any).__auditResult);
 writeFileSync(resolve(dir,'budget-real-chromium.json'),JSON.stringify({result,errors},null,2)+'\n');
 console.log(JSON.stringify({attempts:result.attempts,winner:result.winner[1].chart_type,errors}));
}finally{await browser.close();}
