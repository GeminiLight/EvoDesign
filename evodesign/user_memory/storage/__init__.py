"""Storage backends for user preference memory."""

__all__ = ["Mem0PreferenceStorage"]


def __getattr__(name: str):
    if name == "Mem0PreferenceStorage":
        from .mem0_storage import Mem0PreferenceStorage

        return Mem0PreferenceStorage
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
