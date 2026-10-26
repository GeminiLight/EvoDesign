"""User preference memory package.

The public classes are loaded lazily so lightweight imports such as
``evo_diagram.user_memory.extractors.dna_extractor`` do not initialize the
LLM, VLM, Chroma, or embedding stack.
"""

__all__ = [
    "UserPreferenceMemorySystem",
    "VLMImageObserver",
    "EnhancedDiffExtractor",
    "LLMPreferenceExtractionAgent",
    "Mem0PreferenceStorage",
]


def __getattr__(name: str):
    if name == "UserPreferenceMemorySystem":
        from .main import UserPreferenceMemorySystem

        return UserPreferenceMemorySystem
    if name in {"VLMImageObserver", "EnhancedDiffExtractor", "LLMPreferenceExtractionAgent"}:
        from . import extractors

        return getattr(extractors, name)
    if name == "Mem0PreferenceStorage":
        from .storage.mem0_storage import Mem0PreferenceStorage

        return Mem0PreferenceStorage
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
