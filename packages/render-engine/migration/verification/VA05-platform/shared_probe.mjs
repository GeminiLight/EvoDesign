import { sanitizeRunChat } from '../../../../../shared/model-runs.mjs';
import { writeFileSync } from 'node:fs';
const input={model:'requested-model',messages:[{role:'user',content:'test'}],max_completion_tokens:40000,stream:true,temperature:0,reasoning_effort:'high',thinking:{type:'enabled'},tools:[{type:'function',function:{name:'tool',description:'test',parameters:{type:'object',properties:{}},strict:true}}]};
const output=sanitizeRunChat(input,'shared-server-model');
const result={input,output,note:'Hosted model policy intentionally changes model, output cap, streaming and thinking; tool strict is omitted by allowlist. Do not infer same-model algorithm equivalence for hosted defaults.'};
writeFileSync(new URL('./shared-policy.json',import.meta.url),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result,null,2));
