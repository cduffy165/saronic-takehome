from factory.agents.build_review_orchestrator import (
    _check_required_files,
    _feedback_text,
    slugify,
)
from factory.agents.build_review_schema import ReviewFinding


def test_slugify_basic() -> None:
    assert slugify("Office Supply Request Tracker") == "office-supply-request-tracker"


def test_slugify_strips_punctuation() -> None:
    assert slugify("Bob's App!! (v2)") == "bob-s-app-v2"


def test_slugify_empty_falls_back() -> None:
    assert slugify("   ") == "app"


def test_check_required_files_all_present(tmp_path) -> None:
    for name in ("app.py", "Dockerfile", "README.md"):
        (tmp_path / name).write_text("x")

    assert _check_required_files(tmp_path) == []


def test_check_required_files_reports_missing(tmp_path) -> None:
    (tmp_path / "app.py").write_text("x")

    findings = _check_required_files(tmp_path)

    descriptions = [f.description for f in findings]
    assert any("Dockerfile" in d for d in descriptions)
    assert any("README.md" in d for d in descriptions)
    assert not any("app.py" in d for d in descriptions)


def test_feedback_text_formats_findings() -> None:
    findings = [ReviewFinding(severity="high", category="secrets", description="found a key")]

    text = _feedback_text(findings)

    assert "[high] secrets: found a key" in text
