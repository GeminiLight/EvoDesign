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


def scripted_pairing_server(monkeypatch, claims, verification_url='https://example.org/agent/connect?id=c',
                            web_origin='https://example.org'):
    """Pairing server whose claim answers come from *claims* (dicts or exceptions)."""
    from evodesign_cli import main as cli_main
    requests, opened = [], []
    class PairingServer:
        def __init__(self, *_args): pass
        def request(self, method, path, **_kwargs):
            requests.append(path)
            if path == '/agent/connections':
                return {'connection_id': 'c', 'device_secret': 's', 'user_code': 'CODE', 'interval': 1,
                        'verification_url': verification_url, 'web_origin': web_origin}
            answer = claims.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        def close(self): pass
    monkeypatch.setattr(cli_main, 'Client', PairingServer)
    monkeypatch.setattr(cli_main.time, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(cli_main.webbrowser, 'open', opened.append)
    return requests, opened


ACTIVE = {'status': 'active', 'access_token': 'private-token', 'project_id': 'p',
          'connection_id': 'c', 'expires_at': 1, 'can_commit': False}


def _http_error(status):
    error = CliError('server_error', 'boom', 8)
    error.http_status = status
    return error


def test_claim_polling_retries_transient_failures(private_config, monkeypatch, capsys):
    requests, _ = scripted_pairing_server(monkeypatch, [
        CliError('network_error', 'dropped', 8), _http_error(503), {'status': 'pending'}, dict(ACTIVE)])
    main(['connect', '--server', 'https://example.org', '--no-browser', '--json'])
    assert json.loads(capsys.readouterr().out)['ok']
    assert len([path for path in requests if path.endswith('/claim')]) == 4
    assert load_profile('default')[1] == 'private-token'


def test_claim_polling_stops_on_client_errors(private_config, monkeypatch, capsys):
    error = CliError('pairing_expired', 'gone', 4)
    error.http_status = 404
    requests, _ = scripted_pairing_server(monkeypatch, [error, dict(ACTIVE)])
    with pytest.raises(SystemExit) as result:
        main(['connect', '--server', 'https://example.org', '--no-browser', '--json'])
    assert result.value.code == 4
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'pairing_expired'
    assert len([path for path in requests if path.endswith('/claim')]) == 1


def test_client_marks_5xx_as_transient_and_4xx_as_final():
    for status, transient in ((502, True), (404, False)):
        client = Client('https://example.org')
        client.http.close()
        client.http = httpx.Client(transport=httpx.MockTransport(lambda _request, status=status: httpx.Response(status, json={})))
        try:
            with pytest.raises(CliError) as error:
                client.request('POST', '/agent/connections/c/claim', body={})
            assert error.value.http_status == status
            assert error.value.transient is transient
        finally:
            client.close()


def test_malformed_server_payload_returns_the_json_error_contract(private_config, monkeypatch, capsys):
    scripted_pairing_server(monkeypatch, [{'unexpected': True}])
    with pytest.raises(SystemExit) as result:
        main(['connect', '--server', 'https://example.org', '--no-browser', '--json'])
    payload = json.loads(capsys.readouterr().out)
    assert result.value.code == 8
    assert payload['ok'] is False and payload['error']['code'] == 'invalid_response'


@pytest.mark.parametrize('url', ['https://evil.example/agent/connect?id=c', 'http://example.org/agent/connect',
                                 'javascript:alert(1)', 'https://example.org:8443/agent/connect'])
def test_verification_url_must_match_the_server_origin_not_the_server_claim(private_config, monkeypatch, capsys, url):
    # The server also claims web_origin=evil; only the user's --server is trusted.
    requests, opened = scripted_pairing_server(monkeypatch, [dict(ACTIVE)], verification_url=url,
                                               web_origin='https://evil.example')
    with pytest.raises(SystemExit) as result:
        main(['connect', '--server', 'https://example.org', '--json'])
    assert result.value.code == 8
    assert json.loads(capsys.readouterr().out)['error']['code'] in {'untrusted_web_url', 'invalid_verification_url'}
    assert opened == []
    assert not any(path.endswith('/claim') for path in requests)


def test_explicit_web_origin_and_local_dev_origins_are_trusted(private_config, monkeypatch, capsys):
    _, opened = scripted_pairing_server(monkeypatch, [dict(ACTIVE)], verification_url='https://app.example.org/agent/connect?id=c')
    main(['connect', '--server', 'https://api.example.org', '--web-origin', 'https://app.example.org', '--json'])
    assert opened == ['https://app.example.org/agent/connect?id=c']
    capsys.readouterr()

    _, opened = scripted_pairing_server(monkeypatch, [dict(ACTIVE)], verification_url='http://localhost:5175/agent/connect?id=c')
    main(['connect', '--server', 'http://localhost:3010', '--json'])
    assert opened == ['http://localhost:5175/agent/connect?id=c']
