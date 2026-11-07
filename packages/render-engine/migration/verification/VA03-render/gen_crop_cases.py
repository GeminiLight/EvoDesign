import hashlib,json,logging
from pathlib import Path
from PIL import Image,ImageDraw
from evodesign.agentic_system.render_engine.shared.image_cropper import smart_crop
logging.disable(logging.CRITICAL)
OUT=Path(__file__).resolve().parent/'crop-cases';OUT.mkdir(exist_ok=True)
cases=[]
for name,mode,bg,ink,padding in [('rgb','RGB','white','black',0),('faint','RGB',(250,250,250),(246,250,250),4),('alpha','RGBA',(255,255,255,0),(20,40,60,100),3),('dark','RGB',(20,20,20),(30,50,60),0),('gray','L',255,100,0),('onebit','1',1,0,0),('palette','P',255,0,0),('negative-padding','RGB','white','black',-12)]:
 im=Image.new(mode,(100,80),bg);d=ImageDraw.Draw(im);d.rectangle((10,15,70,60),fill=ink);d.line((8,5,85,5),fill=ink,width=1)
 src=OUT/(name+'.png');im.save(src)
 target=OUT/(name+'.py.png')
 try:
  msg=smart_crop.invoke({'image_path':str(src),'output_path':str(target),'padding':padding,'canvas_engine':'excalidraw'})
  if target.exists():
   result=Image.open(target).convert('RGB');expected={'message':msg.replace(str(target),'<OUT>'),'size':result.size,'rgb_sha256':hashlib.sha256(result.tobytes()).hexdigest()}
  else:expected={'message':msg}
 except Exception as e:expected={'error_type':type(e).__name__,'error':str(e)}
 cases.append({'name':name,'image':str(src),'padding':padding,'expected':expected})
(OUT.parent/'crop-python.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(cases,ensure_ascii=False,indent=1))
