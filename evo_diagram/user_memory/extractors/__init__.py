"""Extractors for user preference memory system.

Exports are loaded lazily to keep JSON/diff-only callers independent from the
VLM and LLM dependencies.
"""

__all__ = [
    "VLMImageObserver",
    "EnhancedDiffExtractor",
    "LLMPreferenceExtractionAgent",
]


def __getattr__(name: str):
    if name == "VLMImageObserver":
        from .vlm_observer import VLMImageObserver

        return VLMImageObserver
    if name == "EnhancedDiffExtractor":
        from .diff_extractor import EnhancedDiffExtractor

        return EnhancedDiffExtractor
    if name == "LLMPreferenceExtractionAgent":
        from .llm_preference_agent import LLMPreferenceExtractionAgent

        return LLMPreferenceExtractionAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
