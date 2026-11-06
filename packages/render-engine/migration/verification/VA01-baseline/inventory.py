import ast
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[5]
PKG=ROOT/'packages/render-engine'
OUT=Path(__file__).resolve().parent
manifest=json.loads((PKG/'migration/modules.json').read_text())['modules']
sigs=json.loads((PKG/'fixtures/functions/_signatures.json').read_text())
summary=json.loads((PKG/'fixtures/functions/_summary.json').read_text())
rows=[]
for item in manifest:
    module=item.get('python')
    if not module:continue
    source=ROOT/item.get('source',module.replace('.','/')+'.py')
    names=[]
    def collect(body,prefix=''):
        for node in body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                names.append(prefix+node.name)
            elif isinstance(node,ast.ClassDef):collect(node.body,prefix+node.name+'.')
    if source.exists():collect(ast.parse(source.read_text()).body)
    fixtures={f.stem:sum(1 for line in f.open() if line.strip()) for f in (PKG/'fixtures/functions'/module).glob('*.jsonl')}
    rp=PKG/'reports/functions'/f'{module}.json'
    report=json.loads(rp.read_text()).get('functions',{}) if rp.exists() else {}
    rows.append({**item,'source_exists':source.exists(),'ts_exists':(PKG/item['ts']).exists(),'declared_functions':names,'functions_with_vectors':list(fixtures),'no_function_vectors':[n for n in names if n not in fixtures],'vector_count':sum(fixtures.values()),'replayed':{k:v for k,v in report.items()},'summary_zero_vector':[k.split('/',1)[1] for k,v in summary.items() if k.startswith(module+'/') and not v.get('vectors')]})
totals={'mapped_python_modules':len(rows),'modules_with_function_vectors':sum(bool(r['functions_with_vectors']) for r in rows),'modules_without_function_vectors':sum(not r['functions_with_vectors'] for r in rows),'declared_functions':sum(len(r['declared_functions']) for r in rows),'fixture_functions':sum(len(r['functions_with_vectors']) for r in rows),'available_vectors':sum(r['vector_count'] for r in rows)}
for key in ['passed','failed','skipped','tolerated','keyOrder']:
    totals[key]=sum(v.get(key,0) for r in rows for v in r['replayed'].values())
totals['skipped_functions']=[{'module':r['python'],'function':f,'vectors':v.get('vectors'),'reason':v.get('skip')} for r in rows for f,v in r['replayed'].items() if v.get('skip')]
totals['zero_vector_modules']=[r['python'] for r in rows if not r['functions_with_vectors']]
(OUT/'coverage-inventory.json').write_text(json.dumps({'totals':totals,'modules':rows},ensure_ascii=False,indent=2)+'\n')
print(json.dumps(totals,ensure_ascii=False,indent=2))
