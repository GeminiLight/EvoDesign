# WP25 acceptance-review script (see migration/PHASE2_REPORT.md §3).
import json, sys, copy, random, pathlib, collections
sys.path.insert(0, '/Users/zhanyi/Code/EvoDesign/packages/render-engine/tools')
from export_fixtures import encode
from evodesign.agentic_system.refinement_stage.fixers import deterministic as dt, primitives as pr
from evodesign.agentic_system.verification_stage.checks.aggregator import run_all_checks
RUNS = pathlib.Path('/Users/zhanyi/Code/EvoDesign/packages/render-engine/fixtures/runs')
OUT = pathlib.Path(sys.argv[1]); rnd = random.Random(25)
vecs = collections.defaultdict(list)
def vec(name, fn, args):
    a = copy.deepcopy(args)
    try: out = {'result': encode(fn(*a))}
    except Exception as e: out = {'raises': type(e).__name__, 'message': str(e)}
    vecs[name].append({'args': encode(args), 'kwargs': {}, **out, 'args_after': encode(a), 'kwargs_after': {}, 'source': 'wp25'})
def corrupt(m, kind):
    els = [e for e in m['elements'] if not e.get('isDeleted')]
    shapes = [e for e in els if e['type'] in ('rectangle', 'ellipse', 'diamond')]
    arrows = [e for e in els if e['type'] == 'arrow']
    if kind == 'backref':
        for e in rnd.sample(shapes, min(3, len(shapes))): e['boundElements'] = []
    elif kind == 'dangling' and arrows:
        a = rnd.choice(arrows); a['startBinding'] = {'elementId': 'ghost123', 'focus': 0, 'gap': 4}
    elif kind == 'move':
        for e in rnd.sample(shapes, min(2, len(shapes))): e['x'] += rnd.choice([-3000, 900, 2500]); e['y'] += rnd.choice([-2000, 600])
    elif kind == 'overlap' and len(shapes) > 2:
        a, b = rnd.sample(shapes, 2); b['x'] = a['x'] + 5; b['y'] = a['y'] + 5
    elif kind == 'contrast':
        for e in rnd.sample(els, min(4, len(els))):
            if e['type'] == 'text': e['strokeColor'] = '#f8f8f8'
            else: e['backgroundColor'] = '#111111'
    elif kind == 'zorder':
        m['elements'].reverse()
for run in sorted(p for p in RUNS.iterdir() if p.is_dir() and not p.name.startswith('_')):
    mf = next((run / 'artifacts' / p for p in ['8_final/final_diagram_manifest.json'] if (run / 'artifacts' / p).exists()), None)
    if mf is None:
        c = sorted((run / 'artifacts').rglob('*diagram_manifest.json'))
        if not c: continue
        mf = c[-1]
    base = json.loads(mf.read_text()); structure = None
    s = list((run / 'artifacts').rglob('structure_instantiation.json'))
    if s: structure = json.loads(s[0].read_text())
    for kind in ['backref', 'dangling', 'move', 'overlap', 'contrast', 'zorder']:
        m = copy.deepcopy(base); corrupt(m, kind)
        try: findings = run_all_checks(m, structure, canvas_library='excalidraw')
        except Exception as e: print('checks failed', run.name, kind, e); continue
        for name, fixer in dt._FIXERS:
            vec('deterministic/' + fixer.__name__, fixer, [m, findings, structure])
        vec('deterministic/run_all_deterministic_fixers', dt.run_all_deterministic_fixers, [m, findings, structure])
    # primitives
    els = [e for e in base['elements'] if not e.get('isDeleted')]
    for e in rnd.sample(els, min(6, len(els))):
        eid = e['id']
        for op, payload in [('op_set_text', {'text': 'Hello 世界\n第二行'}), ('op_set_text', {'text': 5}), ('op_set_style', {'strokeColor': '#ff0000', 'backgroundColor': '#00ff00', 'bogus': 1}),
                         ('op_delete_element', {}), ('op_set_index', {'index': 'a0'}), ('op_set_index', {}), ('op_set_icon', {'icon': 'database'}),
                         ('op_clear_arrow_binding', {'end': 'start'}), ('op_clear_arrow_binding', {'end': 'end'}), ('op_clear_container_binding', {}),
                         ('op_append_bound_element', {'bound_id': 'xyz', 'type': 'arrow'}), ('op_append_bound_element', {'bound_id': els[0]['id']}),
                         ('op_remove_bound_element', {'bound_id': 'xyz'}), ('op_remove_bound_element', {'bound_id': (e.get('boundElements') or [{'id': 'q'}])[0]['id']})]:
            fn = getattr(pr, op); a = [copy.deepcopy(base), eid, payload]
            vec('primitives/' + op, fn, a)
for k, v in vecs.items():
    d = OUT / k.split('/')[0]; d.mkdir(parents=True, exist_ok=True)
    (d / (k.split('/')[1] + '.jsonl')).write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in v))
    print(k, len(v), sum(1 for x in v if 'raises' in x), sum(1 for x in v if x.get('result') not in ([], None)))
