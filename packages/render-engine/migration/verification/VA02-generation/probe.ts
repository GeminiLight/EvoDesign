import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
const dir=dirname(fileURLToPath(import.meta.url));
const root=resolve(dir,'../../../../..');
const data=JSON.parse(readFileSync(resolve(dir,'probes.json'),'utf8'));
const mods:Record<string,any>={};
for (const m of data.modules) mods[m.python]=await import(resolve(root,'packages/render-engine',m.ts));
function normalized(x:any):any {if(x===undefined)return null;if(typeof x==='number'&&!Number.isFinite(x))return{__number__:Number.isNaN(x)?'nan':x>0?'inf':'-inf'};if(Array.isArray(x))return x.map(normalized);if(x&&typeof x==='object')return Object.fromEntries(Object.keys(x).sort().map(k=>[k,normalized(x[k])]));return x;}
function eq(a:any,b:any):boolean{return JSON.stringify(normalized(a))===JSON.stringify(normalized(b));}
const failures:any[]=[];const rows:any[]=[];
for(const c of data.cases){
 const args=structuredClone(c.args);let actual:any;
 try{
  let result:any;const mod=mods[c.module];
  if(c.function==='StylingAgent._postprocess_styling_json')result=mod.StylingAgent.prototype._postprocess_styling_json.call(Object.create(mod.StylingAgent.prototype),...args);
  else if(c.function==='StylingAgent.postprocess_validate'){
   const processed=mod.StylingAgent.prototype._postprocess_styling_json.call(Object.create(mod.StylingAgent.prototype),args[0]);
   result=mods['evodesign.agentic_system.generation_stage.styling.schemas'].validate_styling_instantiation(processed,args[1],'excalidraw');
  }else result=await mod[c.function](...args);
  actual={result:result??null,args_after:args};
 }catch(e:any){actual={error:{type:e.name,message:e.message},args_after:args};}
 const resultOk=eq(c.expected.result,actual.result)&&eq(c.expected.error,actual.error);
 const mutationOk=eq(c.expected.args_after,actual.args_after);
 rows.push({id:c.id,module:c.module,function:c.function,tag:c.tag,ok:resultOk&&mutationOk});
 if(!resultOk||!mutationOk)failures.push({id:c.id,module:c.module,function:c.function,tag:c.tag,args:c.args,expected:c.expected,actual,resultOk,mutationOk});
}
const constants=data.constants.map((c:any)=>{const value=mods[c.module][c.name];const hash=typeof value==='string'?createHash('sha256').update(value).digest('hex'):null;return{...c,actual_sha256:hash,actual_characters:typeof value==='string'?[...value].length:null,ok:hash===c.sha256};});
writeFileSync(resolve(dir,'probe-results.json'),JSON.stringify({total:rows.length,passed:rows.filter(r=>r.ok).length,failed:failures.length,failures,constants,rows},null,1)+'\n');
console.log(JSON.stringify({cases:rows.length,passed:rows.filter(r=>r.ok).length,failed:failures.length,constants:constants.length,constantFailures:constants.filter((r:any)=>!r.ok).length}));
for(const f of failures.slice(0,12))console.log(JSON.stringify(f));
