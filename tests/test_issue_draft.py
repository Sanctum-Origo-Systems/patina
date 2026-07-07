from __future__ import annotations

from patina.issue_draft import (
    _SKILL_CONTENT,
    format_draft,
    install_skill,
    save_draft,
    slugify,
    strip_sensitive,
)


def test_slugify_basic():
    assert slugify("Add file-issue skill") == "add-file-issue-skill"


def test_slugify_special_chars():
    assert slugify("fix: handle @mentions & emails!") == "fix-handle-mentions-emails"


def test_slugify_truncates_long_titles():
    long_title = "a" * 100
    result = slugify(long_title)
    assert len(result) <= 60


def test_slugify_strips_trailing_hyphen():
    assert not slugify("hello world !!!").endswith("-")


def test_strip_sensitive_removes_emails():
    text = "Contact alice@example.com for details"
    result = strip_sensitive(text)
    assert "alice@example.com" not in result
    assert "[REDACTED]" in result


def test_strip_sensitive_removes_multiple_emails():
    text = "CC bob@corp.io and carol@test.org"
    result = strip_sensitive(text)
    assert "bob@corp.io" not in result
    assert "carol@test.org" not in result


def test_strip_sensitive_removes_slack_handles():
    text = "Ask @john.doe or @alice-smith in Slack"
    result = strip_sensitive(text)
    assert "@john.doe" not in result
    assert "@alice-smith" not in result


def test_strip_sensitive_removes_custom_names():
    text = "Acme Corp reported the bug, talk to Jane Doe"
    result = strip_sensitive(text, names=["Acme Corp", "Jane Doe"])
    assert "Acme Corp" not in result
    assert "Jane Doe" not in result
    assert result.count("[REDACTED]") == 2


def test_strip_sensitive_case_insensitive_names():
    text = "ACME CORP is a customer"
    result = strip_sensitive(text, names=["Acme Corp"])
    assert "ACME CORP" not in result


def test_strip_sensitive_ignores_empty_names():
    text = "Normal text here"
    result = strip_sensitive(text, names=["", "  "])
    assert result == text


def test_strip_sensitive_preserves_safe_text():
    text = "The login page crashes when submitting the form"
    assert strip_sensitive(text) == text


def test_format_draft_has_all_sections():
    content = format_draft(
        title="Fix login crash",
        problem="Login page crashes on submit",
        issue_type="bug",
        files=["src/auth.py", "src/forms.py"],
        expected_behavior="Login should succeed with valid credentials",
        acceptance_criteria=["Login works", "Error shown for bad password"],
    )
    assert "# Fix login crash" in content
    assert "## Summary" in content
    assert "Login page crashes on submit" in content
    assert "## Type" in content
    assert "bug" in content
    assert "## Files to Modify" in content
    assert "- src/auth.py" in content
    assert "- src/forms.py" in content
    assert "## Expected Behavior" in content
    assert "Login should succeed with valid credentials" in content
    assert "## Acceptance Criteria" in content
    assert "- [ ] Login works" in content
    assert "- [ ] Error shown for bad password" in content


def test_format_draft_single_file():
    content = format_draft(
        title="T",
        problem="P",
        issue_type="feat",
        files=["one.py"],
        expected_behavior="E",
        acceptance_criteria=["C"],
    )
    assert "- one.py" in content
    assert "- [ ] C" in content


def test_save_draft_creates_file(tmp_path):
    content = "# Test\n\nBody"
    path = save_draft("My Draft Title", content, proposed_dir=tmp_path)
    assert path.exists()
    assert path.read_text() == content
    assert path.parent == tmp_path


def test_save_draft_filename_format(tmp_path):
    path = save_draft("Fix login crash", "body", proposed_dir=tmp_path)
    name = path.name
    assert name.endswith(".md")
    parts = name.split("-", 2)
    assert len(parts[0]) == 8  # YYYYMMDD
    assert parts[0].isdigit()


def test_save_draft_creates_directory(tmp_path):
    nested = tmp_path / "sub" / "dir"
    path = save_draft("Title", "body", proposed_dir=nested)
    assert path.exists()
    assert nested.exists()


def test_save_draft_uses_default_dir(tmp_path, monkeypatch):
    import patina.store as store_module

    monkeypatch.setattr(store_module, "DEFAULT_HOME", tmp_path)
    path = save_draft("Title", "body")
    assert path.parent == tmp_path / "proposed"
    assert path.exists()


def test_install_skill_creates_file(tmp_path):
    path = install_skill(project_root=tmp_path)
    assert path.exists()
    assert path.parent.name == "skills"
    assert path.name == "file-issue.md"
    content = path.read_text()
    assert "## When to use" in content
    assert "Strip sensitive data" in content
    assert "gh issue create" in content
    assert "Implementation Detail" in content
    assert "Decline" in content


def test_install_skill_overwrites_existing(tmp_path):
    path = install_skill(project_root=tmp_path)
    path.write_text("old content")
    path2 = install_skill(project_root=tmp_path)
    assert path2.read_text() == _SKILL_CONTENT


def test_skill_content_has_required_steps():
    assert "Step 1" in _SKILL_CONTENT
    assert "Step 2" in _SKILL_CONTENT
    assert "Step 3" in _SKILL_CONTENT
    assert "Step 4" in _SKILL_CONTENT
    assert "Step 5a" in _SKILL_CONTENT
    assert "Step 5b" in _SKILL_CONTENT
    assert "Step 5c" in _SKILL_CONTENT


def test_end_to_end_draft_with_stripping(tmp_path):
    content = format_draft(
        title="Fix auth flow",
        problem="User alice@example.com reported crash when @admin clicks save",
        issue_type="bug",
        files=["src/auth.py"],
        expected_behavior="Save should work without crashing",
        acceptance_criteria=["Save works", "No crash on click"],
    )
    sanitized = strip_sensitive(content)
    path = save_draft("Fix auth flow", sanitized, proposed_dir=tmp_path)

    saved = path.read_text()
    assert "alice@example.com" not in saved
    assert "@admin" not in saved
    assert "## Summary" in saved
    assert "Save should work without crashing" in saved
