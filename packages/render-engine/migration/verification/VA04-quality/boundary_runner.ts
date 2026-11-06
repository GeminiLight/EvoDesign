import { readFileSync, writeFileSync } from 'node:fs';
import * as q from '../../../src/agentic_system/quality_policy.ts';
import { _coerce_critique } from '../../../src/verification_stage/critic/critic_agent.ts';
import { VerifierState, Critique } from '../../../src/verification_stage/state.ts';
import { VerifierRefinerState, IterationLog, EditOp } from '../../../src/refinement_stage/state.ts';
import { IterativeRefinerWorkflow, _mark_convergence } from '../../../src/agentic_system/iterative_workflow.ts';
import { run_all_checks } from '../../../src/verification_stage/checks/aggregator.ts';
import { apply_edits } from '../../../src/refinement_stage/fixers/apply_edits.ts';
const dir = new URL('.', import.meta.url).pathname;
const cases = JSON.parse(readFileSync(dir+'boundary-input.json','utf8'));
const out = cases.map((c:any) => {
  try {
    let value:any;
    if (c.op === 'quality') value = (q as any)[c.fn](...c.args);
    else if (c.op === 'critique') value = _coerce_critique(c.data, null).model_dump();
    else if (c.op === 'refiner_state') value = new VerifierRefinerState(c.data).model_dump();
    else if (c.op === 'verifier_state') { const state = new VerifierState(c.data); value = {state:state.model_dump(),quality_passed:state.quality_passed,cli_exit_code:state.cli_exit_code}; }
    else if (c.op === 'after_iteration') {const state=new VerifierRefinerState(c.data);const workflow=Object.create(IterativeRefinerWorkflow.prototype);value={route:workflow._after_iteration(state),state:state.model_dump()};}
    else if (c.op === 'convergence') {
      const s = new VerifierRefinerState(c.data);
      const l = new IterationLog({iteration:c.iteration,findings_before:c.before});
      const findings = c.findings.map((x:any) => ({...x, to_dict(){return x;}}));
      _mark_convergence(s,l,findings,c.edits,c.iteration);
      if(c.repeat) _mark_convergence(s,new IterationLog({iteration:2,findings_before:c.before}),findings,c.edits,2);
      value=s.model_dump();
    } else if(c.op==='checks') value=run_all_checks(c.manifest,c.structure??null,c.layout??null,'excalidraw',c.skip??null).map(x=>x.to_dict());
    else if(c.op==='edits') {
      const [m,o]=apply_edits(c.manifest,c.edits.map((e:any)=>new EditOp(e)),c.allow_icons??true);
      value={manifest:m,outcomes:o.map((x:any)=>x.model_dump())};
    }
    return {id:c.id,ok:true,value};
  } catch(e:any){return {id:c.id,ok:false,error:e.name,message:e.message};}
});
function encode(x:any):any { if(typeof x==='number'&&!Number.isFinite(x)) return {__nonfinite__:String(x)}; if(Array.isArray(x)) return x.map(encode); if(x&&typeof x==='object') return Object.fromEntries(Object.entries(x).map(([k,v])=>[k,encode(v)])); return x; }
writeFileSync(dir+'boundary-ts.json',JSON.stringify(encode(out),null,1)+'\n');
