// Independent audit runner. Does not modify the legacy harness, adapters or fixtures.
import { existsSync,readFileSync,writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { setImmediate as yieldLoop } from 'node:timers/promises';
import { compare } from '../../../test/harness/compare.ts';
import { installPytestFiles } from '../../../test/harness/pytest_files.ts';
import { PACKAGE_ROOT,bindArguments,listFunctionFixtures,loadVectors,signatureOf } from '../../../test/harness/fixtures.ts';
const modules=JSON.parse(readFileSync(join(PACKAGE_ROOT,'migration/modules.json'),'utf8')).modules;
function strict(a:any,b:any,path='$',diffs:string[]=[]):string[]{
 if(diffs.length>=8)return diffs;
 const fail=(s:string)=>{diffs.push(path+': '+s);return diffs;};
 if(typeof a==='number'&&typeof b==='number'){
   if(a===b||(Number.isNaN(a)&&Number.isNaN(b)))return diffs;
   const delta=Math.abs(a-b);
   if(!Number.isInteger(a)&&!Number.isInteger(b)&&delta<=1e-6)return diffs;
   return fail(`number ${a} != ${b}`);
 }
 if(a===null||typeof a!=='object'){if(a!==b)fail(`value ${String(a)} != ${String(b)}`);return diffs;}
 if(b===null||typeof b!=='object')return fail('object/type mismatch');
 if(typeof b.then==='function')return fail('unexpected promise');
 if(a instanceof Map){
   const entries=b instanceof Map?[...b]:Object.entries(b);if(a.size!==entries.length)fail('map size mismatch');
   for(const [k,v]of a){const match=entries.find(([other])=>!strict(k,other).length);if(!match)fail('missing map key '+JSON.stringify(k));else strict(v,match[1],path+'[map]',diffs);}return diffs;
 }
 if(a instanceof Set){if(!(b instanceof Set)&&!Array.isArray(b))return fail('set/type mismatch');const entries=[...b];if(a.size!==entries.length)fail('set size mismatch');for(const v of a)if(!entries.some(x=>!strict(v,x).length))fail('missing set entry');return diffs;}
 if(Array.isArray(a)){if(!Array.isArray(b))return fail('array/type mismatch');if(a.length!==b.length)fail('array size mismatch');for(let i=0;i<Math.min(a.length,b.length);i++)strict(a[i],b[i],path+'['+i+']',diffs);return diffs;}
 if(Array.isArray(b))return fail('object/array mismatch');
 const ak=Object.keys(a),bk=Object.keys(b).filter(k=>b[k]!==undefined);
 for(const k of ak){if(!Object.prototype.hasOwnProperty.call(b,k)||b[k]===undefined)fail('missing own key '+k);else strict(a[k],b[k],path+'.'+k,diffs);}
 for(const k of bk)if(!Object.prototype.hasOwnProperty.call(a,k))fail('extra own key '+k);
 return diffs;
}
const report:any={definition:'Fresh replay with original adapters; integer exact, float absolute<=1e-6, Map keys mandatory, own object keys, await promises, exception name and message recorded. Adapter scopes/disabled mutation remain explicit limitations.',modules:[],totals:{vectors:0,passed:0,skipped:0,value_or_mutation_differences:0,exception_type_differences:0,exception_message_differences:0,legacy_compare_blindspots:0,keyword_mutation_checked:0,keyword_mutation_differences:0,unexpected:0}};
for(const m of modules){if(!m.python||!existsSync(join(PACKAGE_ROOT,m.ts)))continue;const mod=await import(join(PACKAGE_ROOT,m.ts));const ap=join(PACKAGE_ROOT,'test/adapters',m.python+'.ts');const adapters=existsSync(ap)?(await import(ap)).default:{};
 const row:any={module:m.python,vectors:0,passed:0,skipped:0,value_or_mutation_differences:0,exception_type_differences:0,exception_message_differences:0,legacy_compare_blindspots:0,keyword_mutation_checked:0,keyword_mutation_differences:0,unexpected:0,examples:[]};
 for(const fn of listFunctionFixtures(m.python)){const adapter=adapters[fn]??{},vectors=loadVectors(m.python,fn);for(const v of vectors){row.vectors++;if(adapter.skip){row.skipped++;continue;}await yieldLoop();const restore=installPytestFiles(m.python,fn,v,vectors);try{
  const params=signatureOf(m.python,fn);let args=bindArguments(params!,v);if(adapter.args)args=adapter.args(args,v);let actual:any,thrown:any;try{actual=await mod[adapter.exportName??fn](...args);}catch(e){thrown=e;}
  const sample:any={function:fn,line:v.line};
  if(thrown){if(v.raises){const name=thrown.name==='PyTypeError'?'TypeError':thrown.name;let different=false;if(name!==v.raises){row.exception_type_differences++;sample.expected_type=v.raises;sample.actual_type=name;different=true;}if(thrown.message!==v.message){row.exception_message_differences++;sample.expected_message=v.message;sample.actual_message=thrown.message;different=true;}if(!different)row.passed++;else if(row.examples.length<8)row.examples.push(sample);}else{row.unexpected++;if(row.examples.length<8)row.examples.push({...sample,unexpected_error:String(thrown)});}continue;}
  if(v.raises){row.unexpected++;if(row.examples.length<8)row.examples.push({...sample,expected_error:v.raises});continue;}
  const adjusted=adapter.result?adapter.result(actual,v):actual;
  const diffs=strict(v.result,adjusted);const legacy=compare(v.result,adjusted).diffs;
  if(adapter.checkMutation!==false&&v.args_after){const before=v.args_after.slice(0,Math.min(v.args_after.length,args.length)),after=args.slice(0,v.args_after.length);diffs.push(...strict(before,after,'$.args_after'));legacy.push(...compare(before,after).diffs);}
  if(adapter.checkMutation!==false&&!adapter.args&&v.kwargs_after&&params){row.keyword_mutation_checked++;const afterBound=bindArguments(params,{...v,args:v.args_after??v.args,kwargs:v.kwargs_after});const kd=strict(afterBound,args,'$.bound_after');if(kd.length){row.keyword_mutation_differences++;diffs.push(...kd);}}
  if(diffs.length){row.value_or_mutation_differences++;if(!legacy.length)row.legacy_compare_blindspots++;if(row.examples.length<8)row.examples.push({...sample,diffs:diffs.slice(0,8),legacy_diffs:legacy});}else row.passed++;
 }finally{restore();}}
 }
 for(const k of Object.keys(report.totals))report.totals[k]+=row[k]??0;report.modules.push(row);
}
writeFileSync(new URL('./strict-replay.json',import.meta.url),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({totals:report.totals,difference_modules:report.modules.filter((m:any)=>m.value_or_mutation_differences||m.exception_type_differences||m.exception_message_differences||m.unexpected).map((m:any)=>({module:m.module,diffs:m.value_or_mutation_differences,type:m.exception_type_differences,message:m.exception_message_differences,unexpected:m.unexpected,legacy_blindspots:m.legacy_compare_blindspots,examples:m.examples.slice(0,1)}))},null,2));
