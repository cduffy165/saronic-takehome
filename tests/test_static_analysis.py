from pathlib import Path

from factory.agents.static_analysis import scan_directory


def test_scan_clean_directory_finds_nothing(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("import streamlit as st\nst.write('hello')\n")

    assert scan_directory(tmp_path) == []


def test_scan_detects_shell_true_with_untrusted_input(tmp_path: Path) -> None:
    # Bandit grades severity by whether the shell command is dynamic: a plain
    # string literal comes back "low" ("seems safe"), concatenated/untrusted
    # input comes back "high" — this exercises the high-severity path.
    (tmp_path / "app.py").write_text(
        "import subprocess\n"
        "user_input = input()\n"
        "subprocess.call('echo ' + user_input, shell=True)\n"
    )

    findings = scan_directory(tmp_path)

    assert any(f.severity == "high" and "shell=True" in f.description for f in findings)


def test_scan_detects_hardcoded_password_string(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('password = "hardcoded_password_123"\n')

    findings = scan_directory(tmp_path)

    assert any("hardcoded" in f.description.lower() for f in findings)


def test_scan_findings_are_categorized_as_static_analysis(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("import subprocess\nsubprocess.call('echo hi', shell=True)\n")

    findings = scan_directory(tmp_path)

    assert all(f.category == "static_analysis" for f in findings)
