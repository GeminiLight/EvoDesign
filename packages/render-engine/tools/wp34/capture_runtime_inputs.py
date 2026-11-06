import base64,json,sys
from pathlib import Path
import pytest
out={}
functions={'_input_fingerprint','_node_load_inputs','_infer_canvas_library_from_manifest'}
def capture(frame,event,arg):
 if event!='call' or frame.f_code.co_name not in functions: return
 if 'evodesign/agentic_system' not in frame.f_code.co_filename:return
 paths=[]
 state=frame.f_locals.get('state')
 if state is not None:
  for key in ['manifest_path','image_path','structure_path','layout_path','verifier_report_path']:
   value=getattr(state,key,None)
   if value:paths.append(str(value))
 else:
  paths=[str(v) for v in frame.f_locals.values() if isinstance(v,(str,Path))]
 if not paths:return
 test=Path(paths[0]).parent.name
 files={Path(p).name:base64.b64encode(Path(p).read_bytes()).decode() for p in paths if Path(p).is_file()}
 out.setdefault(frame.f_code.co_name,{}).setdefault(test,[]).append(files)
sys.setprofile(capture)
code=pytest.main(['-q','evodesign/tests/refinement','--disable-warnings'])
sys.setprofile(None)
Path('packages/render-engine/test/fixtures/runtime_inputs.json').write_text(json.dumps(out,indent=1)+'\n')
print('captured', {k:len(v) for k,v in out.items()},'pytest exit',code)
