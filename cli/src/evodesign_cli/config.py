"""Private, atomic local profiles; credentials never live in a repository."""

import json
import os
from pathlib import Path
import tempfile


def config_dir() -> Path:
    return Path(os.environ.get('EVODESIGN_CONFIG_DIR', Path.home() / '.config' / 'evodesign'))


def read(name: str) -> dict:
    path = config_dir() / name
    if not path.exists():
        return {}
    if path.stat().st_mode & 0o077:
        raise ValueError(f'Private configuration has unsafe permissions: {path}')
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('Invalid configuration')
    return value


def write(name: str, value: dict) -> None:
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.stat().st_mode & 0o077 or directory.stat().st_uid != os.getuid():
        raise ValueError('Use a private configuration directory owned by the current user')
    with tempfile.NamedTemporaryFile(mode='w', dir=directory, delete=False, encoding='utf-8') as output:
        temporary = Path(output.name)
        try:
            json.dump(value, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    temporary.replace(directory / name)


def load_profile(profile: str) -> tuple[dict, str]:
    config = read('config.json').get(profile)
    token = read('credentials.json').get(profile)
    if not isinstance(config, dict) or not isinstance(token, str):
        raise ValueError('Not connected. Run evodesign connect first.')
    return config, token


def save_profile(profile: str, config: dict, token: str) -> None:
    configs, credentials = read('config.json'), read('credentials.json')
    configs[profile], credentials[profile] = config, token
    write('credentials.json', credentials)
    write('config.json', configs)


def remove_profile(profile: str) -> None:
    for name in ('config.json', 'credentials.json'):
        data = read(name)
        data.pop(profile, None)
        write(name, data)
