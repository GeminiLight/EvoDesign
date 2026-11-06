"""Rename every structure id to an integer-like string and record Python stage snapshots."""
import json, re, sys, pathlib, logging
from copy import deepcopy
logging.disable(logging.CRITICAL)
from evodesign.agentic_system.render_engine.state import WorkflowState
from evodesign.agentic_system.render_engine.workflow import RenderWorkflow
FX = pathlib.Path('/Users/zhanyi/Code/EvoDesign/packages/render-engine/fixtures/stages')
OUT = pathlib.Path(sys.argv[1]); OUT.mkdir(exist_ok=True)
only = sys.argv[2:]
wf = RenderWorkflow(canvas_library="excalidraw")
def collect_ids(s):
    s = s.get('structure_instantiation', s) if isinstance(s, dict) else s
    ids = []
    for key in ('nodes', 'groups', 'edges'):
        for item in s.get(key) or []:
            if isinstance(item, dict) and isinstance(item.get('id'), str): ids.append(item['id'])
    return ids
summary = []
for f in sorted(FX.glob('*.json')):
    if f.name.startswith('_'): continue
    d = json.loads(f.read_text())
    if only and not any(o in d['case'] for o in only): continue
    ids = sorted(set(collect_ids(d['input']['structure_instantiation'])), key=len, reverse=True)
    ids = [i for i in ids if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_\-]*', i)]
    PREFIX = __import__("os").environ.get("IDPREFIX", "")
    order = []
    for k in d["input"]["layout_instantiation"]:
        for i2 in ids:
            if i2 == k and i2 not in order: order.append(i2)
    order += [i2 for i2 in collect_ids(d["input"]["structure_instantiation"]) if i2 in ids and i2 not in order]
    mapping = {old: PREFIX + str(n + 1) for n, old in enumerate(order if __import__("os").environ.get("IDORDER") == "layout" else sorted(ids))}
    if not mapping: continue
    pat = re.compile(r'(?<![A-Za-z0-9_])(' + '|'.join(map(re.escape, ids)) + r')(?![A-Za-z0-9_])')
    def tr(v):
        if isinstance(v, str): return pat.sub(lambda m: mapping[m.group(1)], v)
        if isinstance(v, list): return [tr(x) for x in v]
        if isinstance(v, dict): return {tr(k): tr(x) for k, x in v.items()}
        return v
    inputs = tr(d['input'])
    state = WorkflowState(**deepcopy(inputs), canvas_library="excalidraw")
    snaps, err = [], None
    for node, run in wf._excalidraw_nodes():
        try: state = run(state)
        except Exception as e: err = {"node": node, "raises": type(e).__name__, "message": str(e)[:300]}; break
        snaps.append({"node": node, "layout_instantiation": deepcopy(state.layout_instantiation), "diagram_manifest": deepcopy(state.diagram_manifest), "validation_report": deepcopy(state.validation_report)})
    (OUT / f.name).write_text(json.dumps({"case": d['case'], "input": inputs, "snapshots": snaps, "error": err}, ensure_ascii=False))
    summary.append((d['case'], len(mapping), len(snaps), err and err['node']))
print(len(summary), 'cases;', sum(1 for s in summary if s[3]), 'python errors')
for s in summary:
    if s[3]: print('  py error', s)
