# WP25 acceptance-review script (see migration/PHASE2_REPORT.md §3).
import json, sys, pathlib
sys.path.insert(0, '/Users/zhanyi/Code/EvoDesign/packages/render-engine/tools')
from run_normalize import Normalizer
S = pathlib.Path(sys.argv[1]); RUNS = pathlib.Path('/Users/zhanyi/Code/EvoDesign/packages/render-engine/fixtures/runs')
summary = json.load(open(S / 'runs_out/summary.json'))
tot = same = 0; diffs = []
for r in summary:
    work = pathlib.Path(r['work']); norm = Normalizer(str(work))
    for e in json.load(open(RUNS / r['name'] / 'artifacts.json')):
        if e['kind'] not in ('json', 'text'): continue
        tot += 1
        ts = (work / 'out' / e['path']).read_text(encoding='utf-8')
        rec = (RUNS / r['name'] / 'artifacts' / e['path']).read_text(encoding='utf-8')
        if e['kind'] == 'json':
            mine = json.dumps(norm.value(json.loads(ts)), ensure_ascii=False, indent=1) + "\n"
        else:
            mine = norm.text(ts)
        if mine == rec: same += 1
        else:
            a, b = mine.splitlines(), rec.splitlines()
            i = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))
            diffs.append((r['name'], e['path'], i + 1, (a[i] if i < len(a) else None), (b[i] if i < len(b) else None)))
print(same, '/', tot)
for d in diffs[:30]: print(d)
