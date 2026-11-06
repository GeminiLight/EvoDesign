import json, hashlib, sys, pathlib
from PIL import Image, ImageChops
root = pathlib.Path('/Users/zhanyi/Code/EvoDesign/packages/render-engine/reports/visual')
res = json.loads((root/'results.json').read_text())
print('results.json type', type(res).__name__, len(res))
cases = sorted(p for p in root.iterdir() if p.is_dir())
stats = dict(n=0, json_equal=0, png_bytes_equal=0, pixel_equal=0, blank=0, missing=0)
bad=[]
for c in cases:
    stats['n']+=1
    pj, tj = c/'python.json', c/'ts.json'
    if json.loads(pj.read_text()) == json.loads(tj.read_text()): stats['json_equal']+=1
    else: bad.append(('json', c.name))
    pp, tp = c/'python.png', c/'ts.png'
    if not (pp.exists() and tp.exists()): stats['missing']+=1; bad.append(('png-missing', c.name)); continue
    if pp.read_bytes()==tp.read_bytes(): stats['png_bytes_equal']+=1
    a=Image.open(pp).convert('RGBA'); b=Image.open(tp).convert('RGBA')
    if a.size==b.size and ImageChops.difference(a,b).getbbox() is None: stats['pixel_equal']+=1
    else: bad.append(('pixel', c.name))
    ex = a.convert('L').getextrema()
    if ex[0]==ex[1]: stats['blank']+=1; bad.append(('blank', c.name))
print(stats); print(bad[:20])
# also the python.json equals fixture last snapshot?
fx = pathlib.Path('/Users/zhanyi/Code/EvoDesign/packages/render-engine/fixtures/stages')
mism=0
for c in cases:
    f = json.loads((fx/f'{c.name}.json').read_text())
    if f['snapshots'][-1]['diagram_manifest'] != json.loads((c/'python.json').read_text()): mism+=1
print('python.json != fixture last snapshot:', mism)
