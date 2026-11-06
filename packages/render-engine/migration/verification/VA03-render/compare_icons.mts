import {readFileSync,writeFileSync} from 'node:fs';
import {icon_file} from '../../../src/common/node_icons.ts';
const cases=JSON.parse(readFileSync(new URL('./icons-python.json',import.meta.url),'utf8'));
const mismatches=[];
for(const c of cases){
 const actual=icon_file(c.name,c.color);
 if(JSON.stringify(actual)!==JSON.stringify(c.result))mismatches.push({name:c.name,color:c.color,expected:c.result,actual});
}
const out={cases:cases.length,passed:cases.length-mismatches.length,mismatches};
writeFileSync(new URL('./icons-comparison.json',import.meta.url),JSON.stringify(out,null,2)+'\n');console.log(out);
