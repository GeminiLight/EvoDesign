from __future__ import annotations

from types import SimpleNamespace

import pytest

from evo_diagram.user_memory.extractors.dna_extractor import (
    DnaImageExtractor,
    DnaRuleExtractionError,
)


class _FakeVlm:
    def __init__(
        self,
        *,
        content: object = None,
        error: Exception | None = None,
    ):
        self.content = content
        self.error = error
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return SimpleNamespace(content=self.content)


def test_dna_image_extractor_returns_rules_from_valid_response():
    vlm = _FakeVlm(
        content=(
            '{"rules": ['
            '{"cabin": "structure", "title": "Layered flow", "preview": "Use tiers."},'
            '{"cabin": "unknown", "title": "Ignored", "preview": "Wrong cabin."}'
            "]}"
        )
    )
    extractor = DnaImageExtractor(vlm=vlm)

    rules = extractor.extract_rules(b"image", "image/png")

    assert rules == [
        {
            "cabin": "structure",
            "title": "Layered flow",
            "preview": "Use tiers.",
        }
    ]
    assert len(vlm.calls) == 1


def test_dna_image_extractor_allows_valid_empty_rule_list():
    extractor = DnaImageExtractor(vlm=_FakeVlm(content='{"rules": []}'))

    assert extractor.extract_rules(b"image", "image/png") == []


def test_dna_image_extractor_raises_on_vlm_failure_without_echoing_secret():
    extractor = DnaImageExtractor(
        vlm=_FakeVlm(error=RuntimeError("provider secret-token"))
    )

    with pytest.raises(DnaRuleExtractionError) as exc_info:
        extractor.extract_rules(b"image", "image/png")

    assert "secret-token" not in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, RuntimeError)


@pytest.mark.parametrize(
    "content",
    [
        "not-json secret-token",
        '{"rules": "not-a-list"}',
        "[]",
    ],
)
def test_dna_image_extractor_rejects_malformed_responses(content):
    extractor = DnaImageExtractor(vlm=_FakeVlm(content=content))

    with pytest.raises(DnaRuleExtractionError) as exc_info:
        extractor.extract_rules(b"image", "image/png")

    assert "secret-token" not in str(exc_info.value)


def test_dna_image_extractor_rejects_non_text_response_content():
    extractor = DnaImageExtractor(vlm=_FakeVlm(content={"secret": "payload"}))

    with pytest.raises(DnaRuleExtractionError) as exc_info:
        extractor.extract_rules(b"image", "image/png")

    assert str(exc_info.value) == "DNA extractor returned invalid response"
    assert "secret" not in str(exc_info.value)


def test_dna_image_extractor_does_not_wrap_parser_programmer_bugs(monkeypatch):
    extractor = DnaImageExtractor(vlm=_FakeVlm(content='{"rules": []}'))

    def fail_parser(response: str):
        raise RuntimeError("parser programmer bug")

    monkeypatch.setattr(extractor, "_parse_response", fail_parser)

    with pytest.raises(RuntimeError, match="parser programmer bug"):
        extractor.extract_rules(b"image", "image/png")


def test_dna_image_extractor_rejects_non_empty_rules_without_valid_candidates():
    extractor = DnaImageExtractor(
        vlm=_FakeVlm(
            content=(
                '{"rules": ['
                '{"cabin": "unknown", "title": "Ignored", "preview": "Wrong cabin."},'
                '{"cabin": "style", "title": "", "preview": "Missing title."}'
                "]}"
            )
        )
    )

    with pytest.raises(DnaRuleExtractionError, match="no valid rules"):
        extractor.extract_rules(b"image", "image/png")
