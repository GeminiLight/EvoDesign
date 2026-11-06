import { readFileSync,writeFileSync } from 'node:fs';
import { _coerce_critique } from '../../../src/verification_stage/critic/critic_agent.ts';
import { VerifierState } from '../../../src/verification_stage/state.ts';
import { EditOp,VerifierRefinerState } from '../../../src/refinement_stage/state.ts';
import { apply_edits } from '../../../src/refinement_stage/fixers/apply_edits.ts';
const all=JSON.parse(readFileSync(new URL('../VA04-quality/boundary-input.json',import.meta.url),'utf8'));
const selected=all.filter((c:any)=>(c.op==='critique'&&['7_','7__0','١'].includes(c.data.overall_score))||(c.op==='verifier_state'&&c.data.objective_summary.major==='oops')||(c.op==='edits'&&c.edits[0].payload.x==='1__0'));
const out=selected.map((c:any)=>{try{let value:any;
if(c.op==='critique')value=_coerce_critique(c.data,null).model_dump();
if(c.op==='verifier_state'){const s=new VerifierState(c.data);value={state:s.model_dump(),quality_passed:s.quality_passed,cli_exit_code:s.cli_exit_code};}
if(c.op==='edits'){const [m,o]=apply_edits(c.manifest,c.edits.map((e:any)=>new EditOp(e)),true);value={manifest:m,outcomes:o.map((e:any)=>e.model_dump())};}
return {input:c,ok:true,value};}catch(e:any){return {input:c,ok:false,error:e.name,message:e.message};}});
writeFileSync(new URL('./quality-focus.json',import.meta.url),JSON.stringify(out,null,2));console.log(JSON.stringify(out.map((x:any)=>({id:x.input.id,op:x.input.op,ok:x.ok,error:x.error,score:x.value?.overall_score,quality_passed:x.value?.quality_passed,applied:x.value?.outcomes?.[0]?.applied,x:x.value?.manifest?.elements?.[0]?.x})),null,2));
