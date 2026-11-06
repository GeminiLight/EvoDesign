import {readFileSync,writeFileSync} from 'node:fs';
import {VerifierCriticAgent} from '../../../src/verification_stage/critic/critic_agent.ts';
import {RefinerLLMAgent} from '../../../src/refinement_stage/agent/llm_agent.ts';
import {compare_rendered_diagrams} from '../../../src/verification_stage/critic/comparison.ts';
const dir=new URL('.',import.meta.url).pathname;
const input=JSON.parse(readFileSync(dir+'retry-input.json','utf8'));
const results=[];
for(const c of input){
 let calls=0;const model={invoke:async()=>{calls++;return {content:c.content};}} as any;
 try{
  let value:any;
  if(c.role==='critic'){
   const a=new VerifierCriticAgent(model,3,0);a._build_messages=()=>[];
   value=(await a.critique('unused.png')).overall_score;
  }else if(c.role==='refiner'){
   const a=new RefinerLLMAgent(model,3,0);const edits=await a.propose_edits(dir+'original.png',null,[],null,[]);
   value={edits:edits.length,exhaustion:a.last_exhaustion_error};
  }else{
   value=await compare_rendered_diagrams(dir+'original.png',dir+(c.identical?'original.png':'candidate.png'),'🙂'.repeat(12001),model);
  }
  results.push({id:c.id,calls,ok:true,value});
 }catch(e:any){results.push({id:c.id,calls,ok:false,error:e.name,message:e.message});}
}
writeFileSync(dir+'retry-ts.json',JSON.stringify(results,null,1)+'\n');
