"""HTTP and structured failures with no engine or browser dependencies."""

import time
from urllib.parse import urlsplit

import httpx


class CliError(Exception):
    def __init__(self, code: str, message: str, exit_code: int = 8, **extra):
        self.code, self.exit_code, self.extra = code, exit_code, extra
        super().__init__(message)


def server_origin(value: str) -> str:
    parsed = urlsplit(value.rstrip('/'))
    local = parsed.hostname in {'localhost', '127.0.0.1', '::1'}
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'}:
        raise CliError('invalid_server', 'Use a server origin without credentials, path or query', 2)
    if parsed.scheme != 'https' and not (local and parsed.scheme == 'http'):
        raise CliError('invalid_server', 'Use HTTPS, or HTTP on a local loopback address', 2)
    if not parsed.netloc:
        raise CliError('invalid_server', 'Server hostname is required', 2)
    return value.rstrip('/')


class Client:
    def __init__(self, server: str, token: str | None = None):
        self.server = server_origin(server)
        self.http = httpx.Client(headers={'Authorization': 'Bearer ' + token} if token else {},
            timeout=httpx.Timeout(10, connect=5), follow_redirects=False)

    def close(self) -> None:
        self.http.close()

    def request(self, method: str, path: str, *, body=None, timeout: float = 10, binary: bool = False):
        attempts = 2 if method == 'GET' else 1
        deadline = time.monotonic() + max(timeout, 0.1)
        for attempt in range(attempts):
            try:
                remaining = max(0.1, deadline - time.monotonic())
                response = self.http.request(method, self.server + '/api/v1' + path,
                                             json=body, timeout=httpx.Timeout(remaining, connect=min(remaining, 5)))
                break
            except httpx.HTTPError as exc:
                if attempt + 1 == attempts or time.monotonic() >= deadline:
                    raise CliError('network_error', 'Connection failed; query the existing proposal before repeating a write', 8) from exc
                time.sleep(0.2)
        if response.is_error or response.is_redirect:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            error = payload.get('error') or payload.get('detail') or {}
            if not isinstance(error, dict):
                error = {'message': str(error)}
            code = error.get('code', 'http_error')
            status = response.status_code
            exit_code = 3 if status == 401 else 4 if status in {403, 404} else 5 if status == 409 else 6 if status == 422 else 8
            raise CliError(code, error.get('message', 'Request failed'), exit_code,
                           **{k: v for k, v in error.items() if k not in {'code', 'message'}})
        if binary:
            if not response.headers.get('content-type', '').startswith('image/png'):
                raise CliError('invalid_preview', 'Server did not return a PNG preview', 7)
            return response.content
        try:
            payload = response.json()
        except ValueError as exc:
            raise CliError('invalid_response', 'Server did not return JSON') from exc
        if not isinstance(payload, dict) or payload.get('protocol_version') != 1 or not payload.get('ok') or 'data' not in payload:
            raise CliError('protocol_mismatch', 'Server does not support collaboration protocol v1')
        return payload['data']
