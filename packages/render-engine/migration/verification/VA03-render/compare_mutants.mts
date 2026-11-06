import {readFileSync,writeFileSync} from 'node:fs';
import {createWorkflowState,excalidrawNodes} from '../../../src/render_engine/workflow.ts';
import {compare} from '../../../test/harness/compare.ts';
const cases=JSON.parse(readFileSync(new URL('./mutants-python.json',import.meta.url),'utf8'));
const reports=[];
for(const c of cases){
 let state:any;let first:any=null;
 try {state=createWorkflowState(structuredClone(c.input));}
 catch(e:any){first={node:'createWorkflowState',error:e.message};}
 if(!first)for(const [i,[node,run]]of excalidrawNodes().entries()){
  try{state=run(state);}catch(e:any){first={node,error:e.stack};break;}
  const expected=c.snapshots[i];
  const actual={node,layout_instantiation:state.layout_instantiation,diagram_manifest:state.diagram_manifest,validation_report:state.validation_report??null};
  const diff=compare(expected,actual);
  if(diff.diffs.length){first={node,diffs:diff.diffs.slice(0,5)};break;}
 }
 reports.push({case:c.case,python_error:c.error,ts_first_divergence:first});
}
const text=JSON.stringify(reports,null,2)+'\n';
writeFileSync(new URL('./mutants-comparison.json',import.meta.url),text);console.log(text);
