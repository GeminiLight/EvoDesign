"""Prepare a two-node candidate on a connected blank project, without committing."""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', default='paper')
    parser.add_argument('--output', default='agent-quickstart-preview.png')
    args = parser.parse_args()

    def cli(*command: str):
        result = subprocess.run(['evodesign', *command, '--profile', args.profile, '--json'],
                                capture_output=True, text=True, timeout=120)
        payload = json.loads(result.stdout)
        if result.returncode:
            print(json.dumps(payload, ensure_ascii=False))
            raise SystemExit(result.returncode)
        return payload['data']

    document = cli('document', 'get')
    cli('context', 'get')
    if any(not element.get('isDeleted') for element in document['schema'].get('elements', [])):
        parser.error('Choose a blank project; this example does not modify existing diagrams')
    prefix = 'quickstart-' + uuid4().hex[:8]
    body = {'protocol_version': 1, 'operation_id': str(uuid4()),
        'base_version': document['version'], 'constraints_hash': document['constraints']['constraints_hash'],
        'scope': {'kind': 'project'}, 'operations': [
            {'op': 'add_node', 'id': prefix+'-idea', 'x': 0, 'y': 0, 'width': 200, 'height': 100, 'text': 'Your idea'},
            {'op': 'add_node', 'id': prefix+'-canvas', 'x': 340, 'y': 0, 'width': 200, 'height': 100, 'text': 'Editable diagram'},
            {'op': 'connect', 'id': prefix+'-link', 'from': prefix+'-idea', 'to': prefix+'-canvas'},
        ]}
    with tempfile.TemporaryDirectory(prefix='evodesign-quickstart-') as directory:
        path = Path(directory)/'operations.json'
        path.write_text(json.dumps(body), encoding='utf-8')
        proposal = cli('proposal', 'create', '--file', str(path))
    ready = cli('proposal', 'wait', proposal['proposal_id'], '--timeout', '90')
    preview = cli('proposal', 'preview', proposal['proposal_id'], '--output', args.output)
    print(json.dumps({'status': ready['status'], 'proposal_id': proposal['proposal_id'],
        'preview': preview['path'], 'web_url': document['web_url'], 'committed': False}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
