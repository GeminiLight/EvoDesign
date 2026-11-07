import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import { validate_diagram_generate_request } from '../../../src/web_runtime/diagram_generate.ts';
const here=dirname(fileURLToPath(import.meta.url));
const root=resolve(here,'../../../../..');
const base={context:'test',canvas_library:'excalidraw'};
const cases=[
  ...[null,1,1.0,'1','1.0',true,false,1.5].map((base_version,index)=>({id:`base_version_${index}`,body:{...base,base_version}})),
  ...[{},false,[],{name:'outline_globe'}].map((evoDesignIcon,index)=>({id:`icon_marker_${index}`,body:{...base,current_schema:{elements:[{id:'node',type:'image',customData:{evoDesignIcon}}]}}})),
  {id:'deleted_empty_array',body:{...base,current_schema:{elements:[{id:'node',type:'rectangle',isDeleted:[]}]}}},
  {id:'false_icon',body:{...base,use_icons:false}},
  {id:'true_icon',body:{...base,use_icons:true}},
  {id:'automated',body:{...base,diagram_type:'automated'}},
];
writeFileSync(resolve(here,'schema-inputs.json'),JSON.stringify(cases,null,2));
const python=JSON.parse(execFileSync(resolve(root,'.venv/bin/python'),[resolve(here,'schema_probe.py'),resolve(here,'schema-inputs.json')],{cwd:root,encoding:'utf8'}));
const typescript=cases.map(({id,body})=>{
 try{return {id,ok:true,value:validate_diagram_generate_request(body)};}
 catch(exc:any){return {id,ok:false,errors:exc.errors};}
});
const rows=cases.map((input,index)=>({input,python:python[index],typescript:typescript[index],same:JSON.stringify(python[index].ok?python[index].value:python[index].ok)===JSON.stringify(typescript[index].ok?typescript[index].value:typescript[index].ok)}));
// Compare values independent of dict insertion order.
for(const row of rows){if(row.python.ok&&row.typescript.ok)row.same=Object.entries(row.python.value).every(([k,v])=>JSON.stringify(v)===JSON.stringify((row.typescript as any).value[k]));}
writeFileSync(resolve(here,'schema-results.json'),JSON.stringify(rows,null,2));
console.log(JSON.stringify({cases:rows.length,different:rows.filter(x=>!x.same).map(x=>({id:x.input.id,python:x.python,typescript:x.typescript}))},null,2));
