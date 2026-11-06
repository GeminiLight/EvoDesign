import datetime
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
PREFIXES = ['evodesign/agentic_system', 'evodesign/core', 'evodesign/config', 'evodesign/utils', 'evodesign/canvas_environment', 'evodesign/canvas_runtime.py', 'backend/app', 'packages/render-engine/src', 'packages/render-engine/test', 'packages/render-engine/tools', 'frontend/src/services', 'frontend/src/components/BrowserModelSettings.tsx', 'frontend/src/components/StageProgress.tsx', 'shared']
EXTS = {'.py', '.ts', '.tsx', '.mjs', '.js', '.json', '.yaml', '.yml', '.md', '.txt', '.svg', '.html'}
def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()
def files():
    result = {}
    for prefix in PREFIXES:
        path = ROOT / prefix
        for file in ([path] if path.is_file() else path.rglob('*')):
            if file.is_file() and file.suffix in EXTS and not {'node_modules', '__pycache__', '.pytest_cache'}.intersection(file.parts):
                result[str(file.relative_to(ROOT))] = hashlib.sha256(file.read_bytes()).hexdigest()
    return dict(sorted(result.items()))
if __name__ == '__main__':
    import sys
    current = files()
    if '--verify' in sys.argv:
        frozen = json.loads((OUT/'baseline.json').read_text())['sha256']
        diff = {key: {'before':frozen.get(key), 'after':current.get(key)} for key in sorted(frozen.keys() | current.keys()) if frozen.get(key) != current.get(key)}
        (OUT/'drift.json').write_text(json.dumps(diff, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps({'verified_files':len(current),'drift_count':len(diff)}))
    else:
        manifest=json.loads((ROOT/'packages/render-engine/migration/modules.json').read_text())
        data={'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'repo':str(ROOT),'baseline_A':git('rev-parse','1ac838f'),'head':git('rev-parse','HEAD'),'status':git('status','--short'),'python_backend_diff_vs_A':git('diff','--name-only','1ac838f','--','evodesign','backend'),'modules':manifest['modules'],'sha256':current}
        (OUT/'baseline.json').write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps({'frozen_files':len(current),'mapped_modules':len(manifest['modules']),'python_backend_diff_vs_A':data['python_backend_diff_vs_A']}))
