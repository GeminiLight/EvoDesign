import {writeFileSync} from 'node:fs';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {StylingAgent} from '../../../src/generation_stage/styling/styling_agent.ts';
import {validate_structure_instantiation} from '../../../src/generation_stage/structure/schemas.ts';
import {validate_styling_instantiation} from '../../../src/generation_stage/styling/schemas.ts';
const structure=validate_structure_instantiation({chart_type:'flowchart',nodes:[{id:'__proto__',label:'A',class:'step'}],edges:[],groups:[]});
// Parse JSON, rather than a JS literal, to retain the model-authored own key.
const raw=JSON.parse('{"__proto__":{"shape":"rectangle","label":{"text":"A"},"strokeColor":"#333333","backgroundColor":"#ffffff"}}');
const agent=Object.create(StylingAgent.prototype);
const processed=agent._postprocess_styling_json(raw);
let validation:any;
try{validation={result:validate_styling_instantiation(processed,structure,'excalidraw')};}catch(e:any){validation={error:{type:e.name,message:e.message}};}
const result={structure_accepted:true,input_keys:Object.keys(raw),processed_keys:Object.keys(processed),processed_has_own_node:Object.hasOwn(processed,'__proto__'),validation};
writeFileSync(resolve(dirname(fileURLToPath(import.meta.url)),'prototype-ts.json'),JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify(result));
if(!result.structure_accepted||result.processed_has_own_node||!validation.error)throw new Error('Expected frozen migration deviation did not reproduce');
