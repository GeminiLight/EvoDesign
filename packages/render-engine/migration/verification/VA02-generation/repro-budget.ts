import { writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setPlatform } from '../../../src/py/platform.ts';
import { platform as browserPlatform } from '../../../src/py/platform_browser.ts';
import { AIMessage } from '@langchain/core/messages';
const mode=process.argv[2]??'node';
if(mode==='browser')setPlatform({createAsyncContext:browserPlatform.createAsyncContext});
// All import of BaseAgent must follow host context selection.
const { BaseAgent, LLMResponseError, _set_clock, _CALL_BUDGET }=await import('../../../src/core/base_agent.ts');
const { sample_and_vote }=await import('../../../src/common/self_consistency.ts');
const { _unwrap_and_validate_structure_sample }=await import('../../../src/generation_stage/structure/structure_agent.ts');
_set_clock({monotonic:()=>0,sleep:async()=>{}});
let releaseFirst!:()=>void,releaseSecond!:()=>void;
const first=new Promise<void>(r=>releaseFirst=r),second=new Promise<void>(r=>releaseSecond=r);
let firstCalls=0,secondCalls=0,nextSample=0;
const attempts=[0,0,0],events:any[]=[];
const agent:any=Object.create(BaseAgent.prototype);
Object.assign(agent,{_tools:[],jsonalize_output:true,strict_json_output:true,json_retry_attempts:2,exclude_think:true,transport_attempts:2,call_deadline_seconds:0});
agent._model={invoke:async(messages:any[])=>{
 const sample=Number(messages[0].content);const attempt=++attempts[sample];
 events.push({sample,attempt,budget_retries:_CALL_BUDGET.getStore()?.retries_left});
 if(attempt===1){if(++firstCalls===3)releaseFirst();await first;return new AIMessage('malformed JSON');}
 if(attempt===2){if(++secondCalls===3)releaseSecond();await second;throw new LLMResponseError('malformed provider response');}
 return new AIMessage(JSON.stringify({specification:{sample},instantiation:{chart_type:sample===0?'flowchart':'architecture',nodes:[{id:'a',label:'A',class:'step'}],edges:[],groups:[]}}));
}};
const result=await sample_and_vote(()=>agent.invoke_with_history([{role:'user',content:String(nextSample++)}]),{},3,'chart_type',_unwrap_and_validate_structure_sample);
const output={mode,attempts,total_model_requests:attempts.reduce((a,b)=>a+b),winner:result,events};
const dir=dirname(fileURLToPath(import.meta.url));
writeFileSync(resolve(dir,`budget-${mode}.json`),JSON.stringify(output,null,2)+'\n');
console.log(JSON.stringify(output));
