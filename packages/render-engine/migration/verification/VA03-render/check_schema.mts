import {readFileSync} from 'node:fs';
import {validate_structure_instantiation} from '../../../src/generation_stage/structure/schemas.ts';
const c=JSON.parse(readFileSync(new URL('./mutants-python.json',import.meta.url),'utf8'));
for(const x of c)try{validate_structure_instantiation(x.input.structure_instantiation);console.log(x.case,'accepted');}catch(e:any){console.log(x.case,e.message);}
