"""Shell-friendly commands for the same document users edit in Web."""

import argparse
import json
from pathlib import Path
import sys
import time
from urllib.parse import quote, urlsplit
from uuid import uuid4
import webbrowser

from . import __version__
from .client import Client, CliError, server_origin
from .config import load_profile, remove_profile, save_profile


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CliError('invalid_arguments', message, 2)


def parser() -> Parser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--profile', default=argparse.SUPPRESS)
    common.add_argument('--json', action='store_true', default=argparse.SUPPRESS)
    root = Parser(prog='evodesign', parents=[common])
    root.add_argument('--version', action='version', version=__version__)
    commands = root.add_subparsers(dest='command', required=True, parser_class=Parser)
    connect = commands.add_parser('connect', parents=[common])
    connect.add_argument('--server', required=True)
    connect.add_argument('--name', default='Agent CLI')
    connect.add_argument('--no-browser', action='store_true')
    commands.add_parser('disconnect', parents=[common])
    groups = {
        'connection': ['status'], 'project': ['get', 'open'], 'document': ['get', 'preview'],
        'context': ['get'], 'proposal': ['create', 'get', 'wait', 'preview', 'commit', 'reject'],
        'history': ['list', 'restore'],
    }
    for name, actions in groups.items():
        group = commands.add_parser(name, parents=[common])
        sub = group.add_subparsers(dest='action', required=True, parser_class=Parser)
        for action in actions:
            cmd = sub.add_parser(action, parents=[common])
            if name == 'proposal' and action == 'create':
                cmd.add_argument('--file', required=True)
                cmd.add_argument('--operation-id', default=None)
            elif name == 'proposal':
                cmd.add_argument('proposal_id')
            if name == 'proposal' and action == 'wait':
                cmd.add_argument('--timeout', type=float, default=90)
            if name == 'proposal' and action == 'preview':
                cmd.add_argument('--output', required=True)
            if name == 'document' and action == 'preview':
                cmd.add_argument('--output', required=True)
                cmd.add_argument('--version', type=int)
            if name == 'history' and action == 'list':
                cmd.add_argument('--limit', type=int, default=20)
            if name == 'history' and action == 'restore':
                cmd.add_argument('snapshot_id')
                cmd.add_argument('--base-version', type=int, required=True)
                cmd.add_argument('--operation-id', default=None)
    return root


def pair(args, profile: str) -> dict:
    server = server_origin(args.server)
    client = Client(server)
    try:
        start = client.request('POST', '/agent/connections', body={'name': args.name})
        target = urlsplit(start['verification_url'])
        origin = urlsplit(start['web_origin'])
        if target.scheme not in {'http', 'https'} or (target.scheme, target.netloc) != (origin.scheme, origin.netloc):
            raise CliError('invalid_verification_url', 'Server returned an invalid verification URL')
        print(f"Approve in Web: {start['verification_url']}\nPairing code: {start['user_code']}", file=sys.stderr)
        if not args.no_browser:
            webbrowser.open(start['verification_url'])
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            status = client.request('POST', '/agent/connections/' + quote(start['connection_id'], safe='') + '/claim',
                                    body={'device_secret': start['device_secret']})
            if status['status'] == 'active':
                save_profile(profile, {'server': server, **{k: status[k] for k in ('project_id', 'connection_id', 'expires_at', 'can_commit')}}, status['access_token'])
                return {k: v for k, v in status.items() if k != 'access_token'}
            time.sleep(min(max(start.get('interval', 3), 1), 10))
        raise CliError('pairing_expired', 'Pairing timed out; start a new connection', 3)
    finally:
        client.close()


def execute(args) -> dict | list:
    profile = getattr(args, 'profile', 'default')
    if args.command == 'connect':
        return pair(args, profile)
    try:
        config, token = load_profile(profile)
    except ValueError as exc:
        raise CliError('not_connected', str(exc), 3) from exc
    client = Client(config['server'], token)
    prefix = '/projects/' + quote(config['project_id'], safe='')
    try:
        if args.command == 'document' and args.action == 'preview':
            version = args.version if args.version is not None else client.request('GET', prefix + '/document/head')['version']
            data = client.request('GET', prefix + '/document/preview?version=' + str(version), binary=True, timeout=50)
            target = Path(args.output).resolve()
            target.write_bytes(data)
            return {'project_id': config['project_id'], 'version': version, 'path': str(target), 'bytes': len(data)}
        if args.command == 'disconnect':
            try:
                result = client.request('DELETE', '/agent/connections/' + quote(config['connection_id'], safe=''))
            except CliError as exc:
                raise CliError('revocation_unconfirmed', 'Local credentials removed; server revocation could not be confirmed', 8) from exc
            finally:
                remove_profile(profile)
            return result
        if args.command == 'connection':
            return client.request('GET', '/agent/connections/' + quote(config['connection_id'], safe=''))
        if args.command in {'project', 'document'}:
            doc = client.request('GET', prefix + '/document')
            if args.command == 'project' and args.action == 'open':
                webbrowser.open(doc['web_url'])
                return {'project_id': doc['project_id'], 'web_url': doc['web_url']}
            return {k: v for k, v in doc.items() if args.command == 'document' or k not in {'schema', 'nodes'}}
        if args.command == 'context':
            return client.request('GET', prefix + '/agent-context')
        if args.command == 'history':
            if args.action == 'list':
                return client.request('GET', prefix + '/agent-history?limit=' + str(args.limit))
            return client.request('POST', prefix + '/restore-proposals', body={
                'snapshot_id': args.snapshot_id, 'base_version': args.base_version,
                'operation_id': args.operation_id or str(uuid4())})
        if args.action == 'create':
            body = json.loads(Path(args.file).read_text())
            if not isinstance(body, dict):
                raise CliError('invalid_input', 'Operations file must contain an object', 2)
            if args.operation_id and body.get('operation_id') not in {None, args.operation_id}:
                raise CliError('invalid_input', 'Operation ID differs between file and command', 2)
            body['operation_id'] = args.operation_id or body.get('operation_id') or str(uuid4())
            try:
                return client.request('POST', prefix + '/agent-proposals', body=body)
            except CliError as error:
                error.extra.setdefault('operation_id', body['operation_id'])
                raise
        path = prefix + '/agent-proposals/' + quote(args.proposal_id, safe='')
        if args.action == 'get':
            return client.request('GET', path, timeout=50)
        if args.action in {'commit', 'reject'}:
            return client.request('POST', path + '/' + args.action)
        if args.action == 'preview':
            data = client.request('GET', path + '/preview', binary=True)
            target = Path(args.output).resolve()
            target.write_bytes(data)
            return {'proposal_id': args.proposal_id, 'path': str(target), 'bytes': len(data)}
        if args.action == 'wait':
            if not 0 < args.timeout <= 600:
                raise CliError('invalid_timeout', 'Timeout must be between 0 and 600 seconds', 2)
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                data = client.request('GET', path, timeout=min(50, deadline-time.monotonic()))
                if data['status'] in {'ready', 'committed'}:
                    return data
                if data['status'] in {'failed', 'rejected', 'expired', 'conflicted'}:
                    raise CliError('proposal_' + data['status'], 'Candidate did not become ready', 7, proposal_id=args.proposal_id, report=data.get('report'))
                time.sleep(min(2, max(0, deadline-time.monotonic())))
            raise CliError('wait_timeout', 'Candidate may still be checking; query it again', 8, proposal_id=args.proposal_id)
        raise CliError('invalid_command', 'Unsupported command', 2)
    except CliError as error:
        if args.command == 'proposal' and args.action != 'create':
            error.extra.setdefault('proposal_id', args.proposal_id)
        raise
    finally:
        client.close()


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    json_mode = '--json' in argv
    try:
        args = parser().parse_args(argv)
        data = execute(args)
        output = {'ok': True, 'protocol_version': 1, 'data': data}
        print(json.dumps(output, ensure_ascii=False, indent=None if json_mode else 2))
    except (OSError, ValueError) as exc:
        error = CliError('invalid_input', str(exc), 2)
        print(json.dumps({'ok': False, 'protocol_version': 1, 'error': {'code': error.code, 'message': str(error)}}))
        raise SystemExit(error.exit_code) from exc
    except CliError as exc:
        print(json.dumps({'ok': False, 'protocol_version': 1, 'error': {'code': exc.code, 'message': str(exc), **exc.extra}}, ensure_ascii=False))
        raise SystemExit(exc.exit_code) from exc
    except KeyboardInterrupt:
        print('Interrupted; an existing candidate may still be available.', file=sys.stderr)
        raise SystemExit(130)
