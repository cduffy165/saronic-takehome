import os
from pathlib import Path

from factory.agents.build_review_orchestrator import _chown_to_host_user


def test_chown_to_host_user_succeeds_for_own_uid(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "file.txt").write_text("x")

    _chown_to_host_user(tmp_path, os.getuid(), os.getgid())

    assert (tmp_path / "sub" / "file.txt").exists()
