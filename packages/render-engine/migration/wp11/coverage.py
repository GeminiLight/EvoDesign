import json, ast, pathlib, re
PKG = pathlib.Path('/Users/zhanyi/Code/EvoDesign/packages/render-engine')
mods = json.loads((PKG/'migration/modules.json').read_text())['modules']
summary = json.loads((PKG/'fixtures/functions/_summary.json').read_text())
never = []; missing_ts = []; total = 0
for m in mods:
    py = m['python']
    if not py: continue
    src = pathlib.Path('/Users/zhanyi/Code/EvoDesign')/(py.replace('.', '/')+'.py')
    tree = ast.parse(src.read_text())
    ts = (PKG/m['ts']).read_text()
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): names.append(node.name)
        elif isinstance(node, ast.ClassDef):
            names.append(node.name)
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and not sub.name.startswith('__'): names.append(f'{node.name}.{sub.name}')
    for n in names:
        total += 1
        key = f'{py}/{n}'
        base = n.split('.')[-1]
        if not re.search(r'\b' + re.escape(base) + r'\b', ts): missing_ts.append(key)
        if '.' in n or n[0].isupper() and key not in summary:
            if key not in summary and '.' in n: never.append(key)
            continue
        if key not in summary: never.append(key)
print('total defs', total)
print('never called (no summary entry):', len(never)); [print('  ', k) for k in never]
print('name not found in TS file:', len(missing_ts)); [print('  ', k) for k in missing_ts]
