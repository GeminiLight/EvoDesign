#!/usr/bin/env python3
"""Publish only the built browser application to the EvoDesign Studio."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
STUDIO = 'GeminiLight/EvoDesign'


def api(path, body=None, method=None):
    request = urllib.request.Request(
        f'https://modelscope.cn/openapi/v1/studios/{STUDIO}{path}',
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={'Authorization': f'Bearer {os.environ["MODELSCOPE_API_KEY"]}',
                 'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(request, timeout=40) as response:
        result = json.load(response)
    if not result.get('success'):
        raise RuntimeError(f'ModelScope rejected {path}')
    return result.get('data', {})


def run(*args, cwd, env):
    # No credentials in argv, remote URLs, log output or the application tree.
    subprocess.run(args, cwd=cwd, env=env, check=True, stdout=subprocess.DEVNULL)


def main():
    if not os.environ.get('MODELSCOPE_API_KEY'):
        raise SystemExit('Set MODELSCOPE_API_KEY in the environment.')
    remote = subprocess.check_output(['git', 'remote', 'get-url', 'origin'], cwd=ROOT, text=True).strip().lower().removesuffix('.git')
    if not (remote.endswith('github.com/geminilight/evodesign') or remote.endswith('github.com:geminilight/evodesign')):
        raise SystemExit('Publish from the public GeminiLight/EvoDesign checkout, not a private development repository.')
    if not (ROOT / 'frontend/dist/index.html').is_file():
        raise SystemExit('Run npm --prefix frontend run build:browser first.')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    with tempfile.TemporaryDirectory(prefix='evodesign-studio-') as directory:
        temporary = Path(directory)
        askpass = temporary / 'askpass'
        askpass.write_text('#!/bin/sh\ncase "$1" in *Username*) echo oauth2;; *) printf "%s" "$MODELSCOPE_API_KEY";; esac\n')
        askpass.chmod(0o700)
        env = {**os.environ, 'GIT_ASKPASS': str(askpass), 'GIT_TERMINAL_PROMPT': '0', 'GIT_LFS_SKIP_SMUDGE': '1'}
        checkout = temporary / 'studio'
        run('git', 'clone', '--depth=1', f'https://modelscope.cn/studios/{STUDIO}.git', str(checkout), cwd=ROOT, env=env)
        # This is a fresh, isolated clone. Preserve its history; replace only
        # the release's allowlisted paths, never sync a development checkout.
        for name in ['static', 'api', 'shared', 'deploy']:
            target = checkout / name
            if target.exists(): shutil.rmtree(target)
        shutil.copytree(ROOT / 'frontend/dist', checkout / 'static')
        # Keep notices with redistributed fonts, SDKs and the icon catalog.
        notices = checkout / 'static/licenses'
        shutil.copytree(ROOT / 'licenses', notices, dirs_exist_ok=True)
        for name in ['MATERIAL_ICONS_LICENSE.txt', 'LUCIDE_ICONS_LICENSE.txt']:
            shutil.copyfile(ROOT / 'evodesign/agentic_system/common/assets' / name, notices / name)
        for package in ['@dagrejs/dagre', 'lucide-react', '@tldraw/tldraw']:
            source = ROOT / 'frontend/node_modules' / package
            for name in ['LICENSE', 'LICENSE.md']:
                if (source / name).is_file():
                    shutil.copyfile(source / name, notices / f'{package.replace("/", "-")}-{name}')
        for name in ['api/model.mjs', 'shared/diagram-prompts.mjs', 'shared/edge-identity.mjs', 'deploy/modelscope/server.mjs', 'LICENSE']:
            target = checkout / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        shutil.copyfile(ROOT / 'deploy/modelscope/Dockerfile', checkout / 'Dockerfile')
        shutil.copyfile(ROOT / 'deploy/modelscope/README.md', checkout / 'README.md')
        (checkout / '.gitattributes').write_text('* -filter -diff -merge -text\n')
        (checkout / '.dockerignore').write_text('*\n!static/\n!static/**\n!api/\n!api/**\n!shared/\n!shared/**\n!deploy/\n!deploy/**\n!LICENSE\n')
        (checkout / 'release.json').write_text(json.dumps({'source': 'GeminiLight/EvoDesign', 'revision': revision}) + '\n')
        run('git', 'config', 'user.name', 'EvoDesign release', cwd=checkout, env=env)
        run('git', 'config', 'user.email', 'release@users.noreply.github.com', cwd=checkout, env=env)
        run('git', 'add', '.', cwd=checkout, env=env)
        changed = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=checkout).returncode
        if changed:
            run('git', 'commit', '-m', f'Publish EvoDesign browser {revision[:12]}', cwd=checkout, env=env)
            run('git', 'push', 'origin', 'HEAD:master', cwd=checkout, env=env)
        variables = api('/variables')
        if isinstance(variables, dict): variables = variables.get('variables', [])
        method = 'PUT' if any(item.get('key') == 'APP_REVISION' for item in variables) else 'POST'
        api('/variables', {'key': 'APP_REVISION', 'value': revision}, method=method)
        api('/deploy', {})
        print(f'Deploying {STUDIO} from {revision[:12]}', flush=True)
        previous = None
        for _ in range(180):
            detail = api('')
            status = detail.get('status')
            if status != previous:
                print(f'Studio: {status}', flush=True)
                previous = status
            if status == 'Running':
                # Status can still refer to the previous process after a deploy.
                try:
                    request = urllib.request.Request(
                        'https://studio-geminilight-evodesign.api-inference.modelscope.net/api/health',
                        headers={'Authorization': f'Bearer {os.environ["MODELSCOPE_API_KEY"]}'},
                    )
                    with urllib.request.urlopen(request, timeout=15) as response:
                        health = json.load(response)
                    if health.get('revision') == revision:
                        print(f'https://modelscope.cn/studios/{STUDIO}?mode=full', flush=True)
                        return
                except (OSError, ValueError):
                    pass
            if status in {'BuildError', 'BuildFailed', 'DeployFailed', 'RuntimeError', 'Failed', 'Error'}:
                raise SystemExit('Studio failed; inspect the build/run logs before routing traffic.')
            time.sleep(5)
        raise SystemExit('Studio did not become ready; automatic routing must remain disabled.')


if __name__ == '__main__':
    main()
