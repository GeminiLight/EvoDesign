import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import httpx
import pytest

from evodesign_cli.client import Client, CliError, server_origin
from evodesign_cli.config import load_profile, remove_profile, save_profile
from evodesign_cli.main import main, parser


@pytest.fixture
def private_config(tmp_path, monkeypatch):
    directory = tmp_path / 'config'
    monkeypatch.setenv('EVODESIGN_CONFIG_DIR', str(directory))
    return directory


def test_profile_credentials_are_private_and_removed(private_config):
    save_profile('paper', {'server': 'https://example.org', 'project_id': 'p'}, 'private-token')
    assert stat.S_IMODE(private_config.stat().st_mode) == 0o700
    assert stat.S_IMODE((private_config / 'credentials.json').stat().st_mode) == 0o600
    assert 'private-token' not in (private_config / 'config.json').read_text()
    assert load_profile('paper')[1] == 'private-token'
    remove_profile('paper')
    with pytest.raises(ValueError, match='Not connected'):
        load_profile('paper')


@pytest.mark.parametrize('url', ['http://example.org', 'https://user:secret@example.org', 'https://example.org/api', 'file:///etc/passwd', 'http://localhost:wrong', 'https://example.org:99999'])
def test_never_sends_credentials_to_an_unsafe_server(url):
    with pytest.raises(CliError):
        server_origin(url)


def test_flags_work_before_and_after_subcommands():
    args = parser().parse_args(['--profile', 'paper', 'proposal', 'get', 'p', '--json'])
    assert args.profile == 'paper' and args.json
    args = parser().parse_args(['proposal', 'get', 'p', '--profile', 'paper', '--json'])
    assert args.profile == 'paper' and args.json


def test_cli_not_connected_returns_single_json_error(private_config, capsys):
    with pytest.raises(SystemExit) as error:
        main(['document', 'get', '--json'])
    assert error.value.code == 3
    output = json.loads(capsys.readouterr().out)
    assert not output['ok'] and output['error']['code'] == 'not_connected'


def test_conflict_preserves_proposal_id_and_exit_code():
    client = Client('https://example.org', 'private-token')
    client.http.close()
    client.http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(409,
        json={'error': {'code': 'version_conflict', 'message': 'Changed', 'proposal_id': 'keep-me', 'current_version': 3}})))
    try:
        with pytest.raises(CliError) as error:
            client.request('POST', '/projects/p/agent-proposals/proposal/commit')
        assert error.value.exit_code == 5
        assert error.value.extra['proposal_id'] == 'keep-me'
    finally:
        client.close()


def test_imports_do_not_load_engine_or_backend():
    script = 'import evodesign_cli.main,sys; assert not any(n.startswith(("evo_diagram", "app.", "torch", "langchain")) for n in sys.modules)'
    result = subprocess.run([sys.executable, '-c', script], text=True, capture_output=True,
        env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')})
    assert result.returncode == 0, result.stderr


def test_uncertain_create_returns_the_operation_id_for_an_exact_retry(private_config, monkeypatch, tmp_path, capsys):
    from evodesign_cli import main as cli_main
    save_profile('default', {'server':'https://example.org','project_id':'project','connection_id':'connection'}, 'private-token')
    path=tmp_path/'operations.json'
    path.write_text(json.dumps({'base_version':1,'constraints_hash':'hash','scope':{'kind':'project'},'operations':[]}))
    class OfflineClient:
        def __init__(self,*_args): pass
        def request(self,*_args,**_kwargs): raise CliError('network_error','Response was lost',8)
        def close(self): pass
    monkeypatch.setattr(cli_main,'Client',OfflineClient)
    with pytest.raises(SystemExit) as result:
        cli_main.main(['proposal','create','--file',str(path),'--json'])
    payload=json.loads(capsys.readouterr().out)
    assert result.value.code==8 and payload['error']['operation_id']
    assert 'private-token' not in json.dumps(payload)


def pairing_server(monkeypatch):
    """Stand-in server that starts a pairing and hands out its token on the first claim."""
    from evodesign_cli import main as cli_main
    requests = []
    class PairingServer:
        def __init__(self, *_args): pass
        def request(self, method, path, **_kwargs):
            requests.append(path)
            if path == '/agent/connections':
                return {'connection_id': 'c', 'device_secret': 's', 'user_code': 'CODE', 'interval': 1,
                        'verification_url': 'https://example.org/agent/connect?id=c', 'web_origin': 'https://example.org'}
            return {'status': 'active', 'access_token': 'private-token', 'project_id': 'p',
                    'connection_id': 'c', 'expires_at': 1, 'can_commit': False}
        def close(self): pass
    monkeypatch.setattr(cli_main, 'Client', PairingServer)
    return requests


def test_connect_saves_the_profile_in_a_new_private_directory(private_config, monkeypatch, capsys):
    pairing_server(monkeypatch)
    main(['connect', '--server', 'https://example.org', '--no-browser', '--json'])
    assert json.loads(capsys.readouterr().out)['ok']
    assert stat.S_IMODE(private_config.stat().st_mode) == 0o700
    assert load_profile('default')[1] == 'private-token'


@pytest.mark.parametrize('problem', ['shared_directory', 'read_only_directory', 'corrupt_profile'])
def test_connect_checks_profile_storage_before_claiming_a_pairing(private_config, monkeypatch, capsys, problem):
    if problem == 'read_only_directory' and os.geteuid() == 0:
        pytest.skip('root can write to any directory')
    private_config.mkdir(mode=0o700)
    if problem == 'shared_directory':
        private_config.chmod(0o755)
    elif problem == 'read_only_directory':
        private_config.chmod(0o500)
    else:
        (private_config / 'credentials.json').write_text('{')
        (private_config / 'credentials.json').chmod(0o600)
    requests = pairing_server(monkeypatch)
    try:
        with pytest.raises(SystemExit) as result:
            main(['connect', '--server', 'https://example.org', '--no-browser', '--json'])
    finally:
        private_config.chmod(0o700)
    payload = json.loads(capsys.readouterr().out)
    assert result.value.code == 2 and payload['error']['code'] == 'invalid_input'
    assert requests == []
