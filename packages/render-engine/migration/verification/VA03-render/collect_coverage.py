import ast,hashlib,json,subprocess
from pathlib import Path
OUT=Path(__file__).resolve().parent
PKG=OUT.parents[2]
REPO=PKG.parents[1]
mods=json.loads((PKG/'migration/modules.json').read_text())['modules']
summary=json.loads((PKG/'fixtures/functions/_summary.json').read_text())
selected=[m for m in mods if int(m['wp'][2:])<=10 and m.get('python')]
extra=['evodesign.agentic_system.render_engine.canvas_render','evodesign.agentic_system.render_engine.service','evodesign.agentic_system.render_engine.shared.image_cropper','evodesign.agentic_system.render_engine.shared.png_validation']
selected += [m for m in mods if m.get('python') in extra]
manual={
'common.semantic_ids':'ID suffixes, bare integer gate, __proto__ admissibility',
'common.node_icons':'trusted SVG loading, ownership, grouping, sync geometry',
'common.layout_contract':'numeric coordinate contract and node/edge entry classification',
'generation_stage.layout.element_shape_estimator':'CJK codepoints, label/icon size footprint',
'render_engine.shared.label_geometry':'hypot and min/max, segment-box distance',
'render_engine.shared.image_cropper':'PNG channel/depth interpretation, threshold, morph, slicing, output encoding',
'render_engine.excalidraw.converter':'stable hashes, z-layer stable sorting, classification buckets, icon embedding',
'render_engine.excalidraw.group_fitter':'Python addition semantics, min/max bounds and containment policy',
'render_engine.excalidraw.arrow_routing.grid_router':'heap tie ordering, grid construction, Dijkstra cost, crossing memo, signed zero',
'render_engine.excalidraw.radial_concept_compactor':'permutations, source-order churn and cost tuple comparisons',
'render_engine.workflow':'stage order and workflow state boundary',
'render_engine.canvas_render':'render scale/margin/timeout configuration and PNGRenderer dispatch',
}
rows=[]
for m in selected:
 py=m['python'];source=m.get('source',py.replace('.','/')+'.py');ts=PKG/m['ts']
 origin=subprocess.check_output(['git','show','1ac838f:'+source],cwd=REPO)
 same=origin==(REPO/source).read_bytes()
 fx={k.split('/',1)[1]:v for k,v in summary.items() if k.startswith(py+'/')}
 vecs=sum(v['vectors'] for v in fx.values());calls=sum(v['calls'] for v in fx.values())
 functions=[n.name for n in ast.parse((REPO/source).read_text()).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
 missing=[n for n in functions if n not in fx]
 suffix=py.removeprefix('evodesign.agentic_system.')
 rows.append({**m,'A_B_source_identical':same,'ts_exists':ts.exists(),'recorded_calls':calls,'recorded_vectors':vecs,'vector_functions':sum(v['vectors']>0 for v in fx.values()),'recorded_zero_vector_functions':[k for k,v in fx.items() if v['vectors']==0],'top_level_functions_not_recorded':missing,'manual_review':manual.get(suffix),'evidence':'112-case stage replay and available function fixtures; per-function exhaustive review not claimed'})
runtime=['src/py/number.ts','src/py/sort.ts','src/py/str.ts','src/py/json.ts','src/py/math.ts','src/py/unicodedata.ts','src/py/dict.ts','src/py/truthy.ts','src/py/float_marks.ts']
report={'mapped_scope_modules':len(rows),'A_B_unchanged':sum(r['A_B_source_identical'] for r in rows),'recorded_vectors':sum(r['recorded_vectors'] for r in rows),'vector_functions':sum(r['vector_functions'] for r in rows),'manual_key_path_modules':sum(bool(r['manual_review']) for r in rows),'modules':rows,'runtime_helpers_reviewed':runtime,'frontend_additional':'frontend/src/services/browser/pipelineRenderer.ts','limits':['stage replay demonstrates sampled inputs, not a proof for every valid input','manual review covers named key paths; other module functions inherit fixture/stage evidence only','tldraw rendering excluded by migration plan','service/browser pixel replay refreshed one case with product+analysis; historical224 image pairs not all regenerated']}
(OUT/'coverage.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print({k:v for k,v in report.items() if k not in ('modules','runtime_helpers_reviewed','limits')})
