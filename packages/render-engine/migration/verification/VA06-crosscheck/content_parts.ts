import { createOpenAIChatModel } from '../../../src/models/openai_chat.ts';
import { writeFileSync } from 'node:fs';
const content=[{type:'reasoning',text:null},{type:'text',text:'[]'}];
const model=createOpenAIChatModel({model:'fake',api_key:'audit-placeholder',base_url:'https://example.invalid/v1',streaming:false,max_retries:0},{browser:true,fetch:async()=>Response.json({id:'audit',choices:[{index:0,message:{role:'assistant',content},finish_reason:'stop'}]})});
const response=await model.invoke('test');
const result={sent_content:content,received_content:response.content};
writeFileSync(new URL('./content-parts-transport.json',import.meta.url),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
