from __future__ import annotations

from patina.style.denylist import is_sensitive


def test_password_detected():
    assert is_sensitive("my password=hunter2") is True


def test_bearer_token_detected():
    assert is_sensitive("Bearer sk-ant-abc123xyz") is True


def test_api_key_detected():
    assert is_sensitive("api_key=abcdef12345") is True


def test_ssn_detected():
    assert is_sensitive("SSN is 123-45-6789") is True


def test_credit_card_detected():
    assert is_sensitive("card: 4111 1111 1111 1111") is True


def test_normal_message_safe():
    assert is_sensitive("Normal work message about the project") is False


def test_slack_token_detected():
    assert is_sensitive("use token xoxb-123-456-abc") is True
