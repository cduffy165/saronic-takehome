from pathlib import Path

from factory.agents.secrets_scanner import scan_directory


def test_scan_clean_directory_finds_nothing(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("import streamlit as st\nst.write('hello')\n")

    assert scan_directory(tmp_path) == []


def test_scan_detects_aws_access_key(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('AWS_KEY = "AKIAABCDEFGHIJKLMNOP"\n')

    findings = scan_directory(tmp_path)

    assert any(f.category == "secrets" and "aws-access-token" in f.description for f in findings)


def test_scan_detects_realistic_private_key_block(tmp_path: Path) -> None:
    (tmp_path / "key.pem").write_text(
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEA1c7+9z5Pad7OejecsQ0bu3aumnAtVogeGpP1JGXY8VMWO4c9\n"
        "qhoV4wqrbA+xg/7ic6bhFPtc1kZk6yGRW+ZKS4XLKmy8lQwwWtLnZ6+qUbAG5Uxx\n"
        "-----END RSA PRIVATE KEY-----\n"
    )

    findings = scan_directory(tmp_path)

    assert any("private-key" in f.description for f in findings)


def test_scan_detects_generic_keyword_adjacent_high_entropy_secret(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('api_key = "aZ8k3Qw9pL2rT6mN0xV4bC7dF1gH5jK9sU3yW8eR2q"\n')

    findings = scan_directory(tmp_path)

    assert any("generic-api-key" in f.description for f in findings)


def test_scan_detects_literal_factory_env_value_even_when_gitleaks_misses_it(
    tmp_path: Path, monkeypatch
) -> None:
    """gitleaks has no Anthropic-specific rule and its generic-api-key regex does
    not match the sk-ant-... shape (verified directly) — this is exactly why the
    bespoke literal-value check exists independent of the scanner's own coverage."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real-factory-secret-value-xyz")
    (tmp_path / "app.py").write_text(
        'API_KEY = "sk-ant-real-factory-secret-value-xyz"  # leaked from the factory env\n'
    )

    findings = scan_directory(tmp_path)

    assert any(
        "literal value from the factory's own environment" in f.description for f in findings
    )


def test_scan_ignores_git_and_venv_directories_for_literal_check(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real-factory-secret-value-xyz")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("sk-ant-real-factory-secret-value-xyz")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("sk-ant-real-factory-secret-value-xyz")

    assert scan_directory(tmp_path) == []
