from __future__ import annotations

import pytest

from app.services import dna_analysis_service as dna_service_module
from app.services.dna_analysis_service import (
    DNA_ANALYSIS_FAILED_DETAIL,
    DNA_EXTRACTOR_UNAVAILABLE_DETAIL,
    DNA_IMAGE_EMPTY_DETAIL,
    DNA_IMAGE_INVALID_DETAIL,
    DnaAnalysisError,
    DnaAnalysisService,
    DnaExtractorAdapter,
    DnaExtractorUnavailableError,
    DnaExtractionError,
    DnaImageValidationError,
    _default_extractor_factory,
)
from evo_diagram.user_memory.extractors.dna_extractor import DnaImageExtractor, DnaRuleExtractionError


_DEFAULT_RULES = object()


class _FakeExtractor:
    def __init__(self, rules=_DEFAULT_RULES, error: Exception | None = None):
        self.rules = [] if rules is _DEFAULT_RULES else rules
        self.error = error

    def extract_rules(self, image_bytes: bytes, mime_type: str):
        if self.error:
            raise self.error
        return self.rules


class _FailingVlm:
    def invoke(self, messages):
        raise RuntimeError("provider secret")


@pytest.mark.parametrize(
    ("exception", "public_detail"),
    [
        (
            DnaImageValidationError("internal validation secret"),
            DNA_IMAGE_INVALID_DETAIL,
        ),
        (
            DnaImageValidationError(
                "internal empty secret",
                public_detail=DNA_IMAGE_EMPTY_DETAIL,
            ),
            DNA_IMAGE_EMPTY_DETAIL,
        ),
        (
            DnaAnalysisError("internal analysis secret"),
            DNA_ANALYSIS_FAILED_DETAIL,
        ),
        (
            DnaExtractorUnavailableError("internal extractor secret"),
            DNA_EXTRACTOR_UNAVAILABLE_DETAIL,
        ),
        (
            DnaExtractionError("internal extraction secret"),
            DNA_ANALYSIS_FAILED_DETAIL,
        ),
    ],
)
def test_dna_errors_keep_internal_messages_private(exception, public_detail):
    assert str(exception).startswith("internal")
    assert exception.public_detail == public_detail
    assert "secret" not in exception.public_detail


def test_dna_analysis_service_normalizes_valid_rules():
    service = DnaAnalysisService(
        extractor_factory=lambda: _FakeExtractor(
            [
                {"cabin": "structure", "title": " Layered flow ", "preview": " Use tiers. "},
                {"cabin": "style", "title": "Muted palette", "preview": "Use soft colors."},
            ]
        )
    )

    candidates = service.analyze_image(b"image", "image/png")

    assert [candidate.cabin_id for candidate in candidates] == ["structure", "style"]
    assert candidates[0].title == "Layered flow"
    assert candidates[0].preview == "Use tiers."


def test_dna_analysis_service_filters_invalid_rules():
    service = DnaAnalysisService(
        extractor_factory=lambda: _FakeExtractor(
            [
                {"cabin": "unknown", "title": "Ignore", "preview": "Wrong cabin"},
                {"cabin": "layout", "title": "", "preview": "Missing title"},
                {"cabin": "style", "title": "Valid", "preview": "Keep this."},
            ]
        )
    )

    candidates = service.analyze_image(b"image", "image/png")

    assert len(candidates) == 1
    assert candidates[0].cabin_id == "style"


def test_dna_analysis_service_rejects_empty_image():
    service = DnaAnalysisService(extractor_factory=lambda: _FakeExtractor())

    with pytest.raises(DnaImageValidationError, match="empty"):
        service.analyze_image(b"", "image/png")


def test_default_dna_extractor_factory_wraps_engine_import_failure(monkeypatch):
    def fail_import_boundary():
        raise RuntimeError("engine secret config")

    monkeypatch.setattr(
        dna_service_module,
        "ensure_evo_diagram_importable",
        fail_import_boundary,
    )

    with pytest.raises(DnaExtractorUnavailableError, match="not available") as exc_info:
        _default_extractor_factory()

    assert "engine secret" not in str(exc_info.value)


def test_dna_analysis_service_does_not_wrap_injected_factory_failures():
    service = DnaAnalysisService(
        extractor_factory=lambda: (_ for _ in ()).throw(RuntimeError("missing config"))
    )

    with pytest.raises(RuntimeError, match="missing config"):
        service.analyze_image(b"image", "image/png")


def test_dna_analysis_service_does_not_wrap_injected_factory_value_errors():
    service = DnaAnalysisService(
        extractor_factory=lambda: (_ for _ in ()).throw(ValueError("provider secret"))
    )

    with pytest.raises(ValueError, match="provider secret") as exc_info:
        service.analyze_image(b"image", "image/png")

    assert str(exc_info.value) == "provider secret"


def test_dna_analysis_service_does_not_wrap_injected_extraction_failure():
    service = DnaAnalysisService(
        extractor_factory=lambda: _FakeExtractor(error=RuntimeError("vlm failed"))
    )

    with pytest.raises(RuntimeError, match="vlm failed"):
        service.analyze_image(b"image", "image/png")


def test_dna_analysis_service_does_not_wrap_injected_extraction_value_errors():
    service = DnaAnalysisService(
        extractor_factory=lambda: _FakeExtractor(error=ValueError("provider secret"))
    )

    with pytest.raises(ValueError, match="provider secret") as exc_info:
        service.analyze_image(b"image", "image/png")

    assert str(exc_info.value) == "provider secret"


def test_dna_extractor_adapter_wraps_engine_extraction_errors():
    class EngineExtractionError(RuntimeError):
        pass

    class FailingEngineExtractor:
        def extract_rules(self, image_bytes: bytes, mime_type: str):
            raise EngineExtractionError("provider secret response")

    adapter = DnaExtractorAdapter(
        extractor=FailingEngineExtractor(),
        extraction_error_type=EngineExtractionError,
    )

    service = DnaAnalysisService(extractor_factory=lambda: adapter)

    with pytest.raises(DnaExtractionError, match="failed") as exc_info:
        service.analyze_image(b"image", "image/png")

    assert isinstance(exc_info.value.__cause__, EngineExtractionError)
    assert "provider secret" not in str(exc_info.value)


def test_dna_analysis_service_wraps_real_extractor_failures():
    adapter = DnaExtractorAdapter(
        extractor=DnaImageExtractor(vlm=_FailingVlm()),
        extraction_error_type=DnaRuleExtractionError,
    )
    service = DnaAnalysisService(
        extractor_factory=lambda: adapter
    )

    with pytest.raises(DnaExtractionError, match="failed") as exc_info:
        service.analyze_image(b"image", "image/png")

    assert "provider secret" not in str(exc_info.value)


@pytest.mark.parametrize("raw_rules", [None, {"cabin": "style"}, "bad", b"bad"])
def test_dna_analysis_service_rejects_invalid_extractor_output(raw_rules):
    service = DnaAnalysisService(extractor_factory=lambda: _FakeExtractor(rules=raw_rules))

    with pytest.raises(DnaExtractionError, match="invalid rules"):
        service.analyze_image(b"image", "image/png")


def test_dna_analysis_service_rejects_malformed_extractor_rule_items():
    service = DnaAnalysisService(
        extractor_factory=lambda: _FakeExtractor(rules=["not-a-rule"])
    )

    with pytest.raises(DnaExtractionError, match="invalid rule"):
        service.analyze_image(b"image", "image/png")
