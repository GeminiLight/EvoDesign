import {readFileSync,writeFileSync} from 'node:fs';
import {compare} from '../../../test/harness/compare.ts';
import {loadVectors,bindArguments,signatureOf} from '../../../test/harness/fixtures.ts';
import {_assign_port_ranks} from '../../../src/render_engine/excalidraw/arrow_routing/ports.ts';
import {_branch_interactions,_dependency_layers} from '../../../src/render_engine/excalidraw/radial_concept_compactor.ts';
const expected=2000000000;
const probes={seed_plus_one:compare(expected,expected+1),seed_plus_two:compare(expected,expected+2),seed_plus_three:compare(expected,expected+3),bad_map:compare(new Map([['wanted',1]]),new Map([['wrong',1]])),bad_promise:compare({},Promise.resolve({not_expected:true}))};
const mod='evodesign.agentic_system.render_engine.excalidraw.radial_concept_compactor';
const rows=[];
for(const [name,fn]of [['_branch_interactions',_branch_interactions],['_dependency_layers',_dependency_layers],['_assign_port_ranks',_assign_port_ranks]]as const){
 let checked=0,missingKeys=0;
 const pyMod=name==='_assign_port_ranks'?'evodesign.agentic_system.render_engine.excalidraw.arrow_routing.ports':mod;
 for(const v of loadVectors(pyMod,name)){
  if(!(v.result instanceof Map)&&name!=='_assign_port_ranks')continue;
  const actual=(fn as Function)(...bindArguments(signatureOf(pyMod,name)!,v));
  checked++;
  const pairs=v.result instanceof Map?[[v.result,actual]]:['corridor_counts','source_port_counts','target_port_counts'].map(k=>[v.result[k],actual[k]]);
  for(const [e,a]of pairs)if(e instanceof Map)for(const key of e.keys())if(!(a instanceof Map)||![...a.keys()].some(k=>JSON.stringify(k)===JSON.stringify(key)))missingKeys++;
 }
 rows.push({name,map_result_vectors:checked,strictly_missing_keys:missingKeys});
}
const out={probes,map_key_crosscheck:rows};writeFileSync(new URL('./crosscheck-harness-results.json',import.meta.url),JSON.stringify(out,null,2)+'\n');console.log(JSON.stringify(out,null,2));
