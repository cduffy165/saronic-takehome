import asyncio
from pathlib import Path

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from factory.agents.build_session import _make_path_guard


def _check(app_dir: Path, tool_name: str, file_path: str):
    guard = _make_path_guard(app_dir)
    return asyncio.run(guard(tool_name, {"file_path": file_path}, None))


def test_allows_relative_path_inside_app_dir(tmp_path: Path) -> None:
    result = _check(tmp_path, "Write", "app.py")
    assert isinstance(result, PermissionResultAllow)


def test_allows_absolute_path_inside_app_dir(tmp_path: Path) -> None:
    result = _check(tmp_path, "Write", str(tmp_path / "subdir" / "app.py"))
    assert isinstance(result, PermissionResultAllow)


def test_denies_parent_directory_escape(tmp_path: Path) -> None:
    result = _check(tmp_path, "Write", "../outside.py")
    assert isinstance(result, PermissionResultDeny)


def test_denies_absolute_path_outside_app_dir(tmp_path: Path) -> None:
    result = _check(tmp_path, "Edit", "/etc/passwd")
    assert isinstance(result, PermissionResultDeny)


def test_denies_deep_parent_escape(tmp_path: Path) -> None:
    result = _check(tmp_path, "Write", "a/b/../../../etc/passwd")
    assert isinstance(result, PermissionResultDeny)


def test_ignores_non_write_edit_tools(tmp_path: Path) -> None:
    result = _check(tmp_path, "Read", "/etc/passwd")
    assert isinstance(result, PermissionResultAllow)
