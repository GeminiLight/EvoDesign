# WP25 acceptance-review script (see migration/PHASE2_REPORT.md §3).
import json, sys, copy
sys.path.insert(0, '/Users/zhanyi/Code/EvoDesign/packages/render-engine/tools')
from export_fixtures import encode
import evodesign.agentic_system.iterative_workflow as iw
from evodesign.agentic_system.refinement_stage import state as st
from evodesign.agentic_system.verification_stage.checks import finding as fm
FIX = '/Users/zhanyi/Code/EvoDesign/packages/render-engine/fixtures/functions/evodesign.agentic_system.iterative_workflow/'
OUT = sys.argv[1]
classes = {}
for mod in (st, fm, iw):
    for k, v in vars(mod).items():
        if isinstance(v, type): classes[k] = v
def dec(x):
    if isinstance(x, list): return [dec(i) for i in x]
    if isinstance(x, dict):
        if '__tuple__' in x: return tuple(dec(i) for i in x['__tuple__'])
        if '__model__' in x:
            return classes[x['__model__']].model_validate(dec(x['fields']))
        if '__dict__' in x: return {dec(k): dec(v) for k, v in x['__dict__']}
        return {k: dec(v) for k, v in x.items()}
    return x
def vec(args, kwargs, fn):
    a = copy.deepcopy(args); kw = copy.deepcopy(kwargs)
    try:
        r = fn(*a, **kw); out = {'result': encode(r)}
    except Exception as e:
        out = {'raises': type(e).__name__, 'message': str(e)}
    return {'args': encode(args), 'kwargs': encode(kwargs), **out, 'args_after': encode(a), 'kwargs_after': encode(kw), 'source': 'wp25'}
mc, ai = [], []
for line in open(FIX + '_mark_convergence.jsonl'):
    v = json.loads(line)
    args = dec(v['args']); kw = dec(v['kwargs'])
    state = args[0]
    # (a) stagnant: previous fingerprint equals the new one
    s2 = state.model_copy(deep=True); s2.prev_findings_fingerprint = iw._fingerprint_findings(kw['findings_after_iter'])
    mc.append(vec([s2], kw, iw._mark_convergence))
    # (b) stagnant with edits_applied flipped
    kw2 = dict(kw); kw2['edits_applied'] = not kw['edits_applied']
    mc.append(vec([s2.model_copy(deep=True)], kw2, iw._mark_convergence))
    # (c) after a mark, the conditional edge
    s3 = state.model_copy(deep=True); iw._mark_convergence(s3, **copy.deepcopy(kw))
    wf = iw.IterativeRefinerWorkflow.__new__(iw.IterativeRefinerWorkflow)
    for variant in range(4):
        s4 = s3.model_copy(deep=True)
        if variant == 1: s4.termination_reason = None; s4.converged = False; s4.current_iteration = s4.max_iterations
        if variant == 2: s4.termination_reason = None; s4.converged = False; s4.current_iteration = max(0, s4.max_iterations - 1)
        if variant == 3: s4.status = 'failed'
        ai.append(vec([s4], {}, lambda s: iw.IterativeRefinerWorkflow._after_iteration(wf, s)))
open(OUT + '/_mark_convergence.jsonl', 'w').write(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in mc))
open(OUT + '/_after_iteration.jsonl', 'w').write(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in ai))
import collections
print(len(mc), collections.Counter(json.dumps(x.get('args_after')[0]['fields'].get('termination_reason')) for x in mc))
print(len(ai), collections.Counter(x.get('result') for x in ai))
