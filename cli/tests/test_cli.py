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


@pytest.mark.parametrize('url', ['http://example.org', 'https://user:secret@example.org', 'https://example.org/api', 'file:///etc/passwd'])
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
