import {readFileSync,writeFileSync,existsSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {PNG} from 'pngjs';
import {_smart_crop} from '../../../src/render_engine/shared/image_cropper.ts';
const cases=JSON.parse(readFileSync(new URL('./crop-python.json',import.meta.url),'utf8'));
const rows=[];
for(const c of cases){
 const out=c.image.replace(/\.png$/,'.ts.png');let actual:any;
 try{
  const message=_smart_crop(c.image,out,c.padding,null,null,'excalidraw').replace(out,'<OUT>');
  actual={message};
  if(existsSync(out)){
   const png=PNG.sync.read(readFileSync(out));const rgb=new Uint8Array(png.width*png.height*3);
   for(let i=0,j=0;i<png.data.length;i+=4,j+=3)rgb.set(png.data.subarray(i,i+3),j);
   actual={message,size:[png.width,png.height],rgb_sha256:createHash('sha256').update(rgb).digest('hex')};
  }
 }catch(e:any){actual={error_type:e.name,error:e.message};}
 rows.push({name:c.name,expected:c.expected,actual,match:JSON.stringify(c.expected)===JSON.stringify(actual)});
}
writeFileSync(new URL('./crop-comparison.json',import.meta.url),JSON.stringify(rows,null,2)+'\n');console.log(rows.map(x=>({name:x.name,match:x.match})));
