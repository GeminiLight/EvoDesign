import { readFileSync,writeFileSync,existsSync } from 'node:fs';
import { join } from 'node:path';
import { PACKAGE_ROOT,listFunctionFixtures,loadVectors } from '../../../test/harness/fixtures.ts';
import { compare } from '../../../test/harness/compare.ts';
const modules=JSON.parse(readFileSync(join(PACKAGE_ROOT,'migration/modules.json'),'utf8')).modules;
const out:any={expected_throw_vectors:0,expected_map_vectors:0,expected_map_nodes:0,result_vectors:0,kwarg_mutation_vectors:0,args_mutation_vectors:0,mutation_disabled_vectors:0,max_number:0,relative_tolerance_numeric_nodes:0,relative_tolerance_examples:[],throws_examples:[]};
for(const m of modules){if(!m.python)continue;const ap=join(PACKAGE_ROOT,'test/adapters',m.python+'.ts');const a=existsSync(ap)?(await import(ap)).default:{};
for(const fn of listFunctionFixtures(m.python)){for(const v of loadVectors(m.python,fn)){
 if(v.raises){out.expected_throw_vectors++;if(out.throws_examples.length<6)out.throws_examples.push({module:m.python,fn,line:v.line,raises:v.raises,message:v.message});}
 if(v.kwargs_after)out.kwarg_mutation_vectors++;
 if(v.args_after)out.args_mutation_vectors++;
 if(a[fn]?.checkMutation===false)out.mutation_disabled_vectors++;
 let hasMap=false;function walk(x:any,path:string){if(x instanceof Map){hasMap=true;out.expected_map_nodes++;for(const [k,val]of x){walk(k,path+'.key');walk(val,path+'.value');}return;}if(x instanceof Set){for(const val of x)walk(val,path+'.set');return;}if(typeof x==='number'&&Number.isFinite(x)){out.max_number=Math.max(out.max_number,Math.abs(x));if(Math.abs(x)>1000){const delta=Math.max(1.1e-6,Math.abs(x)*5e-10);const r=compare(x,x+delta);if(!r.diffs.length&&!r.tolerated){out.relative_tolerance_numeric_nodes++;if(out.relative_tolerance_examples.length<10)out.relative_tolerance_examples.push({module:m.python,fn,line:v.line,path,expected:x,undetected_delta:delta});}}}else if(x&&typeof x==='object')for(const [k,val]of Object.entries(x))walk(val,path+'.'+k);}
 if(Object.prototype.hasOwnProperty.call(v,'result')){out.result_vectors++;walk(v.result,'$.result');if(hasMap)out.expected_map_vectors++;}
}}
}
out.seed_probe=compare(2000000000,2000000001);writeFileSync(new URL('./vector-domains.json',import.meta.url),JSON.stringify(out,null,2));console.log(JSON.stringify(out,null,2));
