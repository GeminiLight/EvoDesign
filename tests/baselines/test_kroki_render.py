"""Kroki rendering: POST transport plus backoff on transient failures."""

from __future__ import annotations

import types

import pytest

from baselines.programmic import kroki_render


class _Response:
    def __init__(self, status_code, content=b"", headers=None, text=""):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.text = text


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(kroki_render.time, "sleep", slept.append)
    return slept


def test_render_posts_the_source_instead_of_encoding_it_into_the_url(monkeypatch, no_sleep):
    calls = []

    def fake_post(url, data=None, headers=None, timeout=None):
        calls.append({"url": url, "data": data, "headers": headers})
        return _Response(200, b"PNG")

    monkeypatch.setattr(kroki_render.requests, "post", fake_post)

    out = kroki_render.KrokiRender(output_format="png").render("graph TD\n  A --> B")

    assert out == b"PNG"
    # A long diagram compressed into a GET URL exceeds the server URL limit
    # (HTTP 414); the source belongs in the body.
    assert calls[0]["url"] == "https://kroki.io/mermaid/png"
    assert calls[0]["data"] == "graph TD\n  A --> B".encode("utf-8")
    assert calls[0]["headers"]["Content-Type"].startswith("text/plain")


def test_render_retries_a_429_and_succeeds(monkeypatch, no_sleep):
    responses = [_Response(429, headers={"Retry-After": "0"}), _Response(429), _Response(200, b"PNG")]
    monkeypatch.setattr(
        kroki_render.requests, "post",
        lambda url, data=None, headers=None, timeout=None: responses.pop(0),
    )

    out = kroki_render.KrokiRender(output_format="png").render("graph TD\n  A --> B")

    assert out == b"PNG"
    assert len(no_sleep) == 2


def test_render_gives_up_after_max_retries(monkeypatch, no_sleep):
    attempts = []
    monkeypatch.setattr(
        kroki_render.requests, "post",
        lambda url, data=None, headers=None, timeout=None: (attempts.append(url), _Response(429))[1],
    )

    with pytest.raises(RuntimeError, match="after 4 attempts"):
        kroki_render.KrokiRender(output_format="png", max_retries=3).render("x")

    assert len(attempts) == 4
    assert len(no_sleep) == 3


def test_render_does_not_retry_a_client_error(monkeypatch, no_sleep):
    attempts = []
    monkeypatch.setattr(
        kroki_render.requests, "post",
        lambda url, data=None, headers=None, timeout=None: (
            attempts.append(url), _Response(400, text="syntax error")
        )[1],
    )

    with pytest.raises(RuntimeError, match="HTTP 400"):
        kroki_render.KrokiRender(output_format="png").render("bad mermaid")

    assert len(attempts) == 1
    assert no_sleep == []


def test_render_retries_a_connection_error(monkeypatch, no_sleep):
    attempts = []

    def flaky(url, data=None, headers=None, timeout=None):
        attempts.append(url)
        if len(attempts) < 3:
            raise kroki_render.requests.exceptions.ConnectionError("reset")
        return _Response(200, b"PNG")

    monkeypatch.setattr(kroki_render.requests, "post", flaky)

    assert kroki_render.KrokiRender(output_format="png").render("x") == b"PNG"
    assert len(attempts) == 3


def test_render_writes_to_a_bare_filename(monkeypatch, tmp_path, no_sleep):
    monkeypatch.setattr(
        kroki_render.requests, "post",
        lambda url, data=None, headers=None, timeout=None: _Response(200, b"PNG"),
    )
    monkeypatch.chdir(tmp_path)

    assert kroki_render.KrokiRender(output_format="png").render("x", "out.png") is None
    assert (tmp_path / "out.png").read_bytes() == b"PNG"


def test_retry_delay_honours_retry_after():
    renderer = kroki_render.KrokiRender(max_backoff=30.0)
    response = _Response(429, headers={"Retry-After": "5"})

    assert renderer._retry_delay(0, response) == 5.0
    # A malformed header falls back to exponential backoff.
    assert renderer._retry_delay(0, _Response(429, headers={"Retry-After": "soon"})) > 0
