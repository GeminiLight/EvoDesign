"""Bounded cleanup of generated private PNG caches."""

from pathlib import Path
import re
import time
from uuid import UUID


def _uuid(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def prune_old_previews(root: Path, *, max_age: float = 7*86400, limit: int = 64) -> int:
    """Remove old generated PNGs without following links or touching other files."""
    if not root.is_dir() or root.is_symlink():
        return 0
    cutoff = time.time() - max_age
    removed = 0
    directories = [(p, False) for p in root.iterdir() if _uuid(p.name)]
    formal = root / 'formal'
    if formal.is_dir() and not formal.is_symlink():
        directories.extend((p, True) for p in formal.iterdir() if _uuid(p.name))
    for directory, is_formal in directories:
        if directory.is_symlink() or not directory.is_dir():
            continue
        for path in directory.glob('*.png'):
            recognized = bool(re.fullmatch(r'[0-9]+-[0-9a-f]{16}\.png', path.name)) if is_formal else _uuid(path.stem)
            try:
                if recognized and not path.is_symlink() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
                    if removed >= limit:
                        return removed
            except OSError:
                continue  # Another request may be collecting the same cache file.
        try:
            directory.rmdir()
        except OSError:
            pass
    return removed
