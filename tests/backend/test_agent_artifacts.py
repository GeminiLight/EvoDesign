import os
import time
from uuid import uuid4

from app.services.agent_artifact_service import prune_old_previews


def test_preview_cleanup_keeps_current_files_and_does_not_follow_links(tmp_path):
    root = tmp_path / 'previews'
    directory = root / str(uuid4())
    directory.mkdir(parents=True)
    old = directory / (str(uuid4()) + '.png')
    recent = directory / (str(uuid4()) + '.png')
    unrelated = directory / 'user-image.png'
    outside = tmp_path / 'outside.png'
    for path in (old, recent, unrelated, outside):
        path.write_bytes(b'png')
    for path in (old, unrelated, outside):
        os.utime(path, (time.time()-8*86400,)*2)
    linked_file = directory / (str(uuid4()) + '.png')
    linked_file.symlink_to(outside)
    linked_directory = root / str(uuid4())
    linked_directory.symlink_to(tmp_path, target_is_directory=True)
    assert prune_old_previews(root) == 1
    assert not old.exists()
    assert recent.exists() and unrelated.exists() and outside.exists() and linked_file.is_symlink()


def test_preview_cleanup_has_a_removal_limit_and_recognizes_formal_cache(tmp_path):
    directory = tmp_path / 'formal' / str(uuid4())
    directory.mkdir(parents=True)
    for version in range(3):
        path = directory / f'{version}-0123456789abcdef.png'
        path.write_bytes(b'png')
        os.utime(path, (time.time()-8*86400,)*2)
    assert prune_old_previews(tmp_path, limit=2) == 2
    assert len(list(directory.glob('*.png'))) == 1
