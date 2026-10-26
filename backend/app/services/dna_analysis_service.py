"""DNA image analysis service boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence

from app.core.exceptions import PublicErrorMixin
from app.core.evo_imports import ensure_evo_diagram_importable


DNA_IMAGE_INVALID_DETAIL = "Uploaded image is invalid"
DNA_IMAGE_EMPTY_DETAIL = "Uploaded image is empty"
DNA_IMAGE_READ_FAILED_DETAIL = "Uploaded image could not be read"
DNA_IMAGE_TOO_LARGE_DETAIL = "Uploaded image is too large"
DNA_IMAGE_UNSUPPORTED_TYPE_DETAIL = "Uploaded image type is not supported"
DNA_ANALYSIS_FAILED_DETAIL = "DNA analysis failed"
DNA_EXTRACTOR_UNAVAILABLE_DETAIL = "DNA extractor is not available"


class DnaAnalysisError(PublicErrorMixin, RuntimeError):
    """Raised when DNA image analysis infrastructure fails."""

    default_public_detail = DNA_ANALYSIS_FAILED_DETAIL


class DnaImageValidationError(PublicErrorMixin, ValueError):
    """Raised when an uploaded image cannot be analyzed."""

    default_public_detail = DNA_IMAGE_INVALID_DETAIL


class DnaImageReadError(DnaImageValidationError):
    """Raised when the upload stream cannot be read."""

    default_public_detail = DNA_IMAGE_READ_FAILED_DETAIL


class DnaImageTooLargeError(DnaImageValidationError):
    """Raised when the upload exceeds the accepted image size."""

    default_public_detail = DNA_IMAGE_TOO_LARGE_DETAIL


class DnaImageUnsupportedTypeError(DnaImageValidationError):
    """Raised when the upload content type is not an accepted image type."""

    default_public_detail = DNA_IMAGE_UNSUPPORTED_TYPE_DETAIL


class DnaExtractorUnavailableError(DnaAnalysisError):
    """Raised when the DNA extractor cannot be constructed."""

    default_public_detail = DNA_EXTRACTOR_UNAVAILABLE_DETAIL


class DnaExtractionError(DnaAnalysisError):
    """Raised when the DNA extractor fails or returns malformed output."""


@dataclass(frozen=True)
class DnaRuleCandidate:
    """Normalized candidate rule extracted from a design reference image."""

    cabin_id: str
    title: str
    preview: str


class DnaRuleExtractor(Protocol):
    """Backend-facing contract for DNA rule extraction engines."""

    def extract_rules(
        self,
        image_bytes: bytes,
        mime_type: str,
    ) -> Sequence[Mapping[str, Any]]:
        """Return raw DNA rule payloads for normalization."""


@dataclass(frozen=True)
class DnaExtractorAdapter:
    """Adapt engine-level DNA extraction failures to backend domain errors."""

    extractor: Any
    extraction_error_type: type[BaseException]

    def extract_rules(
        self,
        image_bytes: bytes,
        mime_type: str,
    ) -> Sequence[Mapping[str, Any]]:
        """Run the engine extractor behind a backend-safe error boundary."""
        try:
            return self.extractor.extract_rules(image_bytes, mime_type)
        except self.extraction_error_type as exc:
            raise DnaExtractionError("DNA extraction failed") from exc


ExtractorFactory = Callable[[], DnaRuleExtractor]


def _default_extractor_factory() -> DnaRuleExtractor:
    try:
        ensure_evo_diagram_importable()
        from evo_diagram.user_memory.extractors.dna_extractor import (
            DnaImageExtractor,
            DnaRuleExtractionError,
        )

        return DnaExtractorAdapter(
            extractor=DnaImageExtractor(),
            extraction_error_type=DnaRuleExtractionError,
        )
    except (ImportError, RuntimeError, TypeError, ValueError) as exc:
        raise DnaExtractorUnavailableError("DNA extractor is not available") from exc


class DnaAnalysisService:
    """Analyze a reference image and return normalized DNA rule candidates."""

    def __init__(self, extractor_factory: ExtractorFactory | None = None):
        self.extractor_factory = extractor_factory or _default_extractor_factory

    def analyze_image(self, image_bytes: bytes, mime_type: str) -> list[DnaRuleCandidate]:
        """Extract rule candidates from image bytes."""
        if not image_bytes:
            raise DnaImageValidationError(
                DNA_IMAGE_EMPTY_DETAIL,
                public_detail=DNA_IMAGE_EMPTY_DETAIL,
            )

        extractor = self.extractor_factory()
        raw_rules = extractor.extract_rules(image_bytes, mime_type)
        return _normalize_rules(raw_rules)


def _normalize_rules(raw_rules: Sequence[Mapping[str, Any]]) -> list[DnaRuleCandidate]:
    if isinstance(raw_rules, (bytes, str)) or not isinstance(raw_rules, Sequence):
        raise DnaExtractionError("DNA extractor returned invalid rules")

    candidates: list[DnaRuleCandidate] = []
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, Mapping):
            raise DnaExtractionError("DNA extractor returned an invalid rule")

        cabin_id = raw_rule.get("cabin")
        title = raw_rule.get("title")
        preview = raw_rule.get("preview")
        if cabin_id not in ("structure", "style", "layout"):
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        if not isinstance(preview, str) or not preview.strip():
            continue
        candidates.append(
            DnaRuleCandidate(
                cabin_id=cabin_id,
                title=title.strip(),
                preview=preview.strip(),
            )
        )
    return candidates
