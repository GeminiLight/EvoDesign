import { compare } from '../../../test/harness/compare.ts';
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
const probes=[
 {id:'large_number_relative_tolerance',expected:1e12,actual:1e12+500,result:compare(1e12,1e12+500)},
 {id:'different_map_keys',expected:[['expected_key',1]],actual:[['wrong_key',1]],result:compare(new Map([['expected_key',1]]),new Map([['wrong_key',1]]))},
 {id:'empty_object_vs_promise',expected:{},actual:'Promise.resolve({not_expected:true})',result:compare({},Promise.resolve({not_expected:true}))},
];
writeFileSync(fileURLToPath(new URL('./harness-results.json',import.meta.url)),JSON.stringify(probes,null,2));
console.log(JSON.stringify(probes,null,2));
